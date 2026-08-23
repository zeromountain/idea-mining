#!/usr/bin/env python3
"""소비 패턴 탐지 — 스크립트는 거래에 대해 무엇이 참인지 정하고, 에이전트는
그것이 사람에 대해 무엇을 뜻하는지 정한다.

spike는 표준편차가 아니라 MAD(중위절대편차)로 잡는다 — 이사비 한 건이 표준편차를
부풀려 이후 6개월의 진짜 급증을 전부 숨긴다. lifestyleInflation은 12개월 미만이면
notComputable이라고 정직하게 말한다. impulse는 탐지 불가능하므로 그 이름의 필드를
내지 않는다 — 명세서에 충동구매와 계획구매를 가르는 신호가 없다.

CLI:
  python3 spending.py ingest  --raw transactions/raw/2026-07-shinhan.csv \
                              --rules categories.json [-o transactions/2026-07.normalized.json]
  python3 spending.py analyze --months 2025-09..2026-08 --dir ~/wealth/transactions
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wealth_common as wc

CONVENIENCE_MAX_TXN = 30000  # 이 이하 소액 + 고빈도만 편의성 소비 후보로 본다


def cmd_ingest(args) -> int:
    rules = wc.load_json(args.rules) if args.rules and Path(args.rules).exists() else {"patterns": []}
    patterns = [(re.compile(p["match"], re.I), p["category"], p.get("convenience", False))
                for p in rules.get("patterns", [])]

    normalized, uncategorized_total = [], 0
    with open(args.raw, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            merchant = (row.get("merchant") or row.get("가맹점") or "").strip()
            amount = row.get("amount") or row.get("금액") or "0"
            amount = int(re.sub(r"[^\d-]", "", amount) or 0)
            date_ = row.get("date") or row.get("일시") or row.get("거래일시") or ""
            category, convenience = None, False
            for pat, cat, conv in patterns:
                if pat.search(merchant):
                    category, convenience = cat, conv
                    break
            if category is None:
                uncategorized_total += amount
            normalized.append({"date": date_, "merchant": merchant, "amount": amount,
                               "category": category, "convenience": convenience})

    out = {"count": len(normalized), "uncategorizedTotal": uncategorized_total, "transactions": normalized}
    if args.out:
        wc.write_json(args.out, out)
        print(wc.json.dumps({"ok": True, "out": args.out, "count": len(normalized),
                             "uncategorizedTotal": uncategorized_total}, ensure_ascii=False, indent=2))
    else:
        wc.emit(wc.envelope("spending.py ingest", out))
    return 0


def _mad_spike(monthly_totals: list[float], current: float) -> tuple[bool, float]:
    """median + 2*MAD 초과 여부. MAD 0이면(값이 다 같으면) 폴백으로 median*0.3을 쓴다."""
    if len(monthly_totals) < 3:
        return False, 0.0
    med = statistics.median(monthly_totals)
    mad = statistics.median([abs(x - med) for x in monthly_totals]) or (med * 0.15)
    threshold = med + 2 * mad
    return current > threshold, threshold


def cmd_analyze(args) -> int:
    tx_dir = Path(args.dir)
    files = sorted(tx_dir.glob("*.normalized.json")) if tx_dir.exists() else []
    if args.months:
        files = files[-args.months:]
    if len(files) < 2:
        wc.emit(wc.envelope("spending.py analyze",
                            {"note": "분석할 월별 거래 파일이 부족하다 (최소 2개월 필요)"},
                            not_computable_list=["patterns", "lifestyleInflation"]))
        return 0

    by_month = []
    for f in files:
        data = wc.load_json(f)
        month = f.name.split(".")[0]
        by_cat, discretionary, total = {}, 0, 0
        for tx in data.get("transactions", []):
            cat = tx.get("category") or "UNCATEGORIZED"
            by_cat[cat] = by_cat.get(cat, 0) + tx["amount"]
            total += tx["amount"]
            if cat not in ("HOUSING", "UTILITIES", "DEBT_SERVICE", "INSURANCE"):
                discretionary += tx["amount"]
        by_month.append({"month": month, "byCategory": by_cat, "total": total, "discretionary": discretionary,
                         "raw": data.get("transactions", [])})

    # ---- recurring (구독) ----
    merchant_hits: dict[str, list] = {}
    for row in by_month:
        for tx in row["raw"]:
            merchant_hits.setdefault(tx["merchant"], []).append((row["month"], tx["amount"]))
    recurring = []
    for merchant, hits in merchant_hits.items():
        if len(hits) >= 3:
            amounts = [a for _, a in hits]
            cv = (statistics.pstdev(amounts) / statistics.mean(amounts)) if statistics.mean(amounts) else 1
            if cv <= 0.05:
                first_seen_recent = hits[0][0] == by_month[0]["month"] and len(by_month) > 1
                price_step_up = len(amounts) >= 4 and amounts[-1] > amounts[-4] * 1.05
                recurring.append({"merchant": merchant, "monthlyAmount": round(statistics.mean(amounts)),
                                  "occurrences": len(hits), "firstSeenWithinWindow": not first_seen_recent,
                                  "priceStepUp": price_step_up})

    # ---- lifestyle inflation ----
    if len(by_month) >= 12:
        recent_q = sum(r["discretionary"] for r in by_month[-3:]) / 3
        prior_q = sum(r["discretionary"] for r in by_month[-12:-9]) / 3
        lifestyle_inflation = wc.computed({"recentQuarterAvg": round(recent_q), "yearAgoQuarterAvg": round(prior_q),
                                           "deltaPct": round((recent_q - prior_q) / prior_q, 4) if prior_q else None,
                                           "rising": recent_q > prior_q})
    else:
        lifestyle_inflation = wc.not_computable(
            f"12개월 이력이 필요한데 현재 {len(by_month)}개월뿐이다 — 판단하지 않는다")

    # ---- spike (MAD 기준) ----
    spikes = []
    all_cats = {c for row in by_month for c in row["byCategory"]}
    for cat in all_cats:
        series = [row["byCategory"].get(cat, 0) for row in by_month]
        if len(series) < 4:
            continue
        trailing, current = series[-7:-1] if len(series) >= 7 else series[:-1], series[-1]
        is_spike, threshold = _mad_spike(trailing, current)
        if is_spike:
            spikes.append({"category": cat, "month": by_month[-1]["month"], "amount": current,
                          "threshold": round(threshold), "trailingMedian": round(statistics.median(trailing))})

    # ---- convenience proxy ----
    last = by_month[-1]
    conv_txns = [tx for tx in last["raw"] if tx.get("convenience") and tx["amount"] <= CONVENIENCE_MAX_TXN]
    convenience_proxy = {"count": len(conv_txns), "total": sum(t["amount"] for t in conv_txns),
                        "shareOfDiscretionary": round(sum(t["amount"] for t in conv_txns) /
                                                      last["discretionary"], 4) if last["discretionary"] else None}

    uncategorized = last["byCategory"].get("UNCATEGORIZED", 0)

    data = {
        "patterns": {"recurring": recurring, "spikes": spikes, "convenienceProxy": convenience_proxy},
        "lifestyleInflation": lifestyle_inflation,
        "uncategorized": {"month": last["month"], "amount": uncategorized,
                          "shareOfTotal": round(uncategorized / last["total"], 4) if last["total"] else None},
        "note": "impulse는 이 스크립트가 판단하지 않는다 — 명세서에 계획구매와 충동구매를 가르는 "
                "신호가 없다. 첫구매여부·야간시각 같은 correlate만 raw 거래에 있으면 활용한다.",
    }
    wc.emit(wc.envelope("spending.py analyze", data))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("ingest")
    p1.add_argument("--raw", required=True)
    p1.add_argument("--rules")
    p1.add_argument("-o", "--out")
    p1.set_defaults(func=cmd_ingest)

    p2 = sub.add_parser("analyze")
    p2.add_argument("--dir", required=True)
    p2.add_argument("--months", type=int)
    p2.set_defaults(func=cmd_analyze)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
