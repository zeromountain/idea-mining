#!/usr/bin/env python3
"""순자산 스냅샷 — take(append-only)·delta(증감 분해)·series.

정정은 새 레코드에 corrects를 다는 것이지 기존 파일을 고치는 것이 아니다.
소급 수정되는 시계열은 "언제 판단이 바뀌었나"에 답할 수 없다.

CLI:
  python3 snapshot.py take --context ~/wealth/financial-context.resolved.json [--month 2026-08]
  python3 snapshot.py delta --from 2026-07 --to 2026-08
  python3 snapshot.py series [--months 24]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wealth_common as wc

SNAP_DIR = wc.ROOT / "snapshots"


def cmd_take(args) -> int:
    ctx = wc.load_json(args.context)
    totals = (ctx.get("_derived") or {}).get("totals") or {}
    month = args.month or wc.today()[:7]

    goal_progress = {g.get("id"): g.get("currentAmount") for g in (ctx.get("goals") or [])}
    eff = ctx.get("effectiveConfidence") or {}
    overall_conf = wc.min_conf(*(eff.values())) if eff else "UNKNOWN"

    snap = {
        "month": month, "takenAt": wc.now_iso(),
        "assets": {"byCategory": totals.get("assets", {}).get("byCategory", {}),
                  "total": totals.get("assets", {}).get("totalAssets", 0),
                  "liquid": totals.get("assets", {}).get("liquidAssets", 0)},
        "liabilities": {"total": totals.get("liabilities", {}).get("totalBalance", 0)},
        "netWorth": totals.get("netWorth", 0),
        "liquidAssets": totals.get("assets", {}).get("liquidAssets", 0),
        "goalProgress": goal_progress,
        "confidence": {"overall": overall_conf, "byBlock": {
            b: wc.block_confidence(ctx, eff, b) for b in
            ("income", "assets", "liabilities", "monthlyExpenses", "insurance", "goals")}},
        "contextHash": ctx.get("contextHash"),
    }
    if args.corrects:
        snap["corrects"] = args.corrects

    path = SNAP_DIR / f"{month}.json"
    if path.exists() and not args.corrects:
        print(f'{{"ok": false, "error": "{month} 스냅샷이 이미 있다 — 정정하려면 '
              f'--corrects {month}과 함께 다른 파일명을 쓰거나 새 월을 쓴다"}}')
        return 1
    if args.corrects:
        path = SNAP_DIR / f"{month}-correction-{wc.today()}.json"
    wc.write_json(path, snap)
    print(wc.json.dumps({"ok": True, "path": str(path), "netWorth": snap["netWorth"]},
                        ensure_ascii=False, indent=2))
    return 0


def _load_month(month: str) -> dict | None:
    exact = SNAP_DIR / f"{month}.json"
    if exact.exists():
        return wc.load_json(exact)
    # 정정본이 있으면 가장 최근 것을 쓴다
    corrections = sorted(SNAP_DIR.glob(f"{month}-correction-*.json"))
    return wc.load_json(corrections[-1]) if corrections else None


def cmd_delta(args) -> int:
    a, b = _load_month(args.from_month), _load_month(args.to_month)
    if not a or not b:
        missing = args.from_month if not a else args.to_month
        print(wc.json.dumps({"ok": False, "error": f"{missing} 스냅샷이 없다"}, ensure_ascii=False))
        return 1

    net_worth_delta = b["netWorth"] - a["netWorth"]
    liab_delta = a["liabilities"]["total"] - b["liabilities"]["total"]  # 감소가 양수
    debt_principal_paid = max(0, liab_delta)

    # 자산 카테고리별로 asOf가 최근에 갱신됐는데 거래 근거가 없어 보이는 변화는
    # dataCorrection으로 본다 — confidence 등급이 바뀐 경우가 그 신호다.
    conf_a, conf_b = a.get("confidence", {}).get("byBlock", {}), b.get("confidence", {}).get("byBlock", {})
    data_correction = 0
    if conf_a.get("assets") != conf_b.get("assets"):
        data_correction = 0  # 정보 신뢰도만 바뀐 경우는 별도 표시하되 금액을 임의 배분하지 않는다

    contribution = 0  # savingsAuto 누적 등 — v1은 컨텍스트만으로 소득에서 온 기여를 특정할 수 없다
    market_move = 0   # 투자자산 평가액 변동 — v1은 자산 카테고리 스냅샷 차이만으로 시장변동을 특정할 수 없다
    accounted = debt_principal_paid + contribution + market_move + data_correction
    unexplained = net_worth_delta - accounted

    data = {
        "from": args.from_month, "to": args.to_month, "netWorthDelta": net_worth_delta,
        "byCause": {"contribution": contribution, "debtPrincipalPaid": debt_principal_paid,
                    "marketMove": market_move, "dataCorrection": data_correction,
                    "unexplained": unexplained},
        "note": "contribution·marketMove는 v1에서 스냅샷 총액만으로는 분해할 수 없다 — "
                "정직하게 unexplained로 남긴다. 자산별 이력을 남기면(v2) 분해 가능해진다.",
    }
    print(wc.json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_series(args) -> int:
    files = sorted(SNAP_DIR.glob("*.json"))
    files = [f for f in files if "-correction-" not in f.name]
    if args.months:
        files = files[-args.months:]
    series = [wc.load_json(f) for f in files]
    print(wc.json.dumps({"count": len(series), "series": [
        {"month": s["month"], "netWorth": s["netWorth"], "liquidAssets": s["liquidAssets"]}
        for s in series]}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("take")
    p1.add_argument("--context", required=True)
    p1.add_argument("--month")
    p1.add_argument("--corrects", help="정정 대상 월 (YYYY-MM)")
    p1.set_defaults(func=cmd_take)

    p2 = sub.add_parser("delta")
    p2.add_argument("--from", dest="from_month", required=True)
    p2.add_argument("--to", dest="to_month", required=True)
    p2.set_defaults(func=cmd_delta)

    p3 = sub.add_parser("series")
    p3.add_argument("--months", type=int)
    p3.set_defaults(func=cmd_series)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
