#!/usr/bin/env python3
"""리포트 렌더러 — report JSON → HTML / Markdown / 터미널 요약.

에이전트는 판단이 담긴 JSON만 낸다. 배치·길이·숫자 포맷은 전부 여기서 결정한다.
그래야 매번 같은 모양이 나오고, quick이 155줄로 부푸는 일이 없다.

  python3 render.py html  report.json -o out.html
  python3 render.py md    report.json -o out.md
  python3 render.py brief report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fmt

# 모드별 상한. quick에 7번째 섹션을 넣으면 잘라내고 경고를 남긴다.
# sections/risks/sources는 개수 상한, body는 섹션 본문 글자 예산이다.
# quick이 deep 수준으로 부푸는 걸 막는 게 이 표의 목적이다.
MODE_SPEC = {
    "quick":           {"sections": 4,    "risks": 3, "sources": 5,  "body": 420,  "scenarios": True},
    "deep":            {"sections": None, "risks": 9, "sources": 20, "body": None, "scenarios": True},
    "valuation":       {"sections": 4,    "risks": 3, "sources": 8,  "body": 700,  "scenarios": True},
    "technical":       {"sections": 3,    "risks": 3, "sources": 4,  "body": 500,  "scenarios": False},
    "earnings":        {"sections": 4,    "risks": 4, "sources": 8,  "body": 600,  "scenarios": False},
    "news":            {"sections": 3,    "risks": 3, "sources": 10, "body": 600,  "scenarios": False},
    "market_movement": {"sections": 3,    "risks": 3, "sources": 8,  "body": 450,  "scenarios": False},
    "compare":         {"sections": 4,    "risks": 5, "sources": 12, "body": 600,  "scenarios": False},
    "portfolio":       {"sections": 4,    "risks": 6, "sources": 8,  "body": 600,  "scenarios": False},
    "recheck":         {"sections": 3,    "risks": 4, "sources": 8,  "body": 450,  "scenarios": False},
}
DEFAULT_SPEC = MODE_SPEC["quick"]

MODE_LABEL = {
    "quick": "Quick", "deep": "Deep", "valuation": "Valuation", "technical": "Technical",
    "earnings": "Earnings", "news": "News", "market_movement": "Market Movement",
    "compare": "Compare", "portfolio": "Portfolio", "recheck": "Thesis Recheck",
}


def spec_for(mode: str) -> dict:
    return MODE_SPEC.get(mode, DEFAULT_SPEC)


def trim_body(body: str, budget: int | None) -> tuple[str, bool]:
    """예산을 넘는 본문을 **문단 경계에서만** 자른다.

    문장 중간을 자르면 분석이 훼손되므로 하지 않는다. 첫 문단만으로 예산을 넘으면
    그 문단은 통째로 남기고 잘렸다는 사실만 보고한다.
    """
    text = (body or "").strip()
    if not budget or len(text) <= budget:
        return text, False
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    kept, total = [], 0
    for para in paras:
        if kept and total + len(para) > budget:
            break
        kept.append(para)
        total += len(para)
    return "\n\n".join(kept), len(kept) < len(paras)


def normalize(report: dict) -> tuple[dict, list[str]]:
    """상한을 적용하고 파생값을 채운다. 잘라낸 것은 경고로 남긴다 (조용히 버리지 않는다)."""
    r = json.loads(json.dumps(report))  # 원본 훼손 방지
    warnings: list[str] = []
    mode = r.get("mode", "quick")
    spec = spec_for(mode)

    limit = spec["sections"]
    sections = r.get("sections") or []
    if limit and len(sections) > limit:
        dropped = [s.get("title", "?") for s in sections[limit:]]
        r["sections"] = sections[:limit]
        warnings.append(
            f"{mode} 모드는 섹션 {limit}개까지다. {len(dropped)}개를 잘라냈다: {', '.join(dropped)}. "
            f"더 담으려면 deep 모드를 쓴다.")

    budget = spec.get("body")
    trimmed = []
    for sec in r.get("sections") or []:
        sec["body"], cut = trim_body(sec.get("body", ""), budget)
        if cut:
            trimmed.append(sec.get("title", "?"))
    if trimmed:
        warnings.append(
            f"본문이 {mode} 예산({budget}자)을 넘어 문단 단위로 줄였다: {', '.join(trimmed)}. "
            f"전문은 deep 모드에서 본다.")

    for key, cap in (("risks", spec["risks"]), ("sources", spec["sources"])):
        items = r.get(key) or []
        if cap and len(items) > cap:
            r[key] = items[:cap]
            warnings.append(f"{key} {len(items) - cap}개를 잘라냈다 ({mode} 상한 {cap}개).")

    if not spec["scenarios"] and r.get("scenarios"):
        r["scenarios"] = []
        warnings.append(f"{mode} 모드는 시나리오 블록을 쓰지 않는다.")

    cur = r.get("currency") or ("KRW" if str(r.get("ticker", "")).endswith((".KS", ".KQ")) else "USD")
    r["currency"] = cur

    snap = r.get("snapshot") or {}
    w52 = snap.get("week52") or []
    if len(w52) == 2:
        snap["week52Position"] = fmt.week52_position(snap.get("price"), w52[0], w52[1])
    r["snapshot"] = snap

    # 시나리오 막대를 공통 축에 올린다 — 이게 있어야 상하방 크기를 눈으로 비교할 수 있다
    scen = r.get("scenarios") or []
    values = [s.get("fairValue") for s in scen if isinstance(s.get("fairValue"), (int, float))]
    price_v = snap.get("price")
    if values:
        lo = min(values + ([price_v] if price_v else []))
        hi = max(values + ([price_v] if price_v else []))
        pad = (hi - lo) * 0.12 or (hi * 0.1 or 1)
        axis_lo, axis_hi = lo - pad, hi + pad
        for s in scen:
            s["_pos"] = fmt.bar_pct(s.get("fairValue"), axis_lo, axis_hi)
        r["_axis"] = {"lo": axis_lo, "hi": axis_hi,
                      "pricePos": fmt.bar_pct(price_v, axis_lo, axis_hi) if price_v else None}
    r["scenarios"] = scen

    r["_warnings"] = warnings
    r["_modeLabel"] = MODE_LABEL.get(mode, mode)
    return r, warnings


def _quality_vs_price(r: dict) -> tuple[dict | None, dict | None]:
    """'좋은 회사 ≠ 좋은 투자'를 보여주는 두 축을 꺼낸다 (문서 §2.2)."""
    by_area = {str(s.get("area", "")).lower(): s for s in (r.get("scores") or [])}
    return by_area.get("business"), by_area.get("valuation")


# ------------------------------------------------------------------ 터미널 요약

def brief(report: dict) -> str:
    r, warnings = normalize(report)
    cur = r["currency"]
    v = r.get("verdict") or {}
    snap = r.get("snapshot") or {}
    conf = v.get("confidence") or {}
    biz, val = _quality_vs_price(r)

    lines = [
        f"{r.get('name', '')} {r.get('ticker', '')}   {v.get('rating', fmt.DASH)}   "
        f"{fmt.num(v.get('score'), 1)}/10   Confidence {conf.get('level', fmt.DASH)}",
        f"  {fmt.price(snap.get('price'), cur)}  {fmt.pct(snap.get('changePct'))}"
        f"   시총 {fmt.money(snap.get('marketCap'), cur)}",
    ]
    if biz or val:
        lines.append(f"  Business {fmt.num((biz or {}).get('value'), 1)} · "
                     f"Valuation {fmt.num((val or {}).get('value'), 1)}"
                     f"   — 좋은 회사와 좋은 가격은 다른 문제다")
    if v.get("headline"):
        lines += ["", f"  {v['headline']}"]

    cmm = (r.get("changeMyMind") or [])[:2]
    if cmm:
        lines.append("")
        lines.append("  판단이 바뀌는 조건")
        lines += [f"    - {c}" for c in cmm]

    gaps = r.get("unavailable") or []
    if gaps:
        lines.append(f"  분석 불가: {', '.join(g.get('section', '?') for g in gaps)}")
    for w in warnings:
        lines.append(f"  ! {w}")
    return "\n".join(lines)


# --------------------------------------------------------------------- 마크다운

def markdown(report: dict) -> str:
    r, warnings = normalize(report)
    cur = r["currency"]
    v = r.get("verdict") or {}
    snap = r.get("snapshot") or {}
    conf = v.get("confidence") or {}
    biz, val = _quality_vs_price(r)
    out: list[str] = []

    out.append(f"# {r.get('name', '')} ({r.get('ticker', '')}) — {r['_modeLabel']}")
    out.append("")
    conf_score = conf.get("score")
    conf_text = f"Confidence {conf.get('level', fmt.DASH)}"
    if conf_score is not None:
        conf_text += f" ({conf_score}/100)"
    out.append(f"**{v.get('rating', fmt.DASH)}**  ·  {fmt.num(v.get('score'), 2)}/10  ·  {conf_text}")
    out.append("")
    out.append(f"{fmt.price(snap.get('price'), cur)} {fmt.pct(snap.get('changePct'))} · "
               f"시총 {fmt.money(snap.get('marketCap'), cur)} · "
               f"기준일 {snap.get('asOf', r.get('analysisDate', ''))}")
    if v.get("proposedRating") and v["proposedRating"] != v.get("rating"):
        out.append("")
        out.append(f"> 제안 등급 **{v['proposedRating']}** → 최종 **{v.get('rating')}**. "
                   f"{v.get('reason', '')}")
    if v.get("headline"):
        out.append("")
        out.append(f"**{v['headline']}**")

    if biz or val:
        out += ["", f"`Business {fmt.num((biz or {}).get('value'), 1)}` "
                    f"`Valuation {fmt.num((val or {}).get('value'), 1)}` "
                    f"— 좋은 회사와 좋은 가격은 다른 문제다."]

    gaps = r.get("unavailable") or []
    if gaps:
        out += ["", "**분석 불가** — " + " · ".join(
            f"{g.get('section', '?')}({g.get('reason', '')})" for g in gaps)]

    scores = r.get("scores") or []
    if scores:
        if r.get("mode") == "deep":
            out += ["", "## 점수", "", "```"]
            for sc in scores:
                out.append(f"{str(sc.get('area', ''))[:10]:<10} {fmt.num(sc.get('value'), 1):>4}  "
                           f"{fmt.ascii_bar(sc.get('value'), 14)}  w{fmt.num(sc.get('weight'), 2)}")
            out += ["```"]
        else:
            out += ["", "**점수** " + " · ".join(
                f"{sc.get('area', '')} {fmt.num(sc.get('value'), 1)}" for sc in scores)]

    for sec in r.get("sections") or []:
        out += ["", f"## {sec.get('title', '')}", "", (sec.get("body") or "").strip()]

    scen = r.get("scenarios") or []
    if scen:
        out += ["", "## 시나리오", "", "| 시나리오 | 적정가 | 현재가 대비 |", "|---|---:|---:|"]
        for s in scen:
            out.append(f"| {s.get('name', '')} | {fmt.price(s.get('fairValue'), cur)} | "
                       f"{fmt.pct(s.get('upside'))} |")
        out.append("")
        out.append("> 시나리오는 정답이 아니라 가정의 결과다. `ASSUMPTION`")

    risks = r.get("risks") or []
    if risks:
        out += ["", "## 리스크", ""]
        if r.get("mode") == "deep":
            for k in risks:
                sev = str(k.get("severity", "unknown")).upper()
                out.append(f"- **{sev}** {k.get('name', '')} — {k.get('note', '')}")
        else:
            out.append(" · ".join(
                f"**{str(k.get('severity', '?')).upper()}** {k.get('name', '')}" for k in risks))
    flags = {k: val_ for k, val_ in (r.get("criticalFlags") or {}).items()}
    if flags:
        hot = [k for k, s in flags.items() if str(s).lower() == "high"]
        out.append("")
        out.append(f"치명적 플래그: {'발동 없음' if not hot else '**' + ', '.join(hot) + '** 발동'} "
                   f"({len(flags)}종 판정 완료)")

    cmm = r.get("changeMyMind") or []
    if cmm:
        out += ["", "## 무엇이 이 판단을 바꾸는가", ""]
        out += [f"{i}. {c}" for i, c in enumerate(cmm, 1)]

    src = r.get("sources") or []
    if src:
        out += ["", "## 출처", ""]
        if r.get("mode") == "deep":
            for s in src:
                url = s.get("url") or ""
                name = s.get("name", "")
                label = f"[{name}]({url})" if url else name
                out.append(f"- `T{s.get('tier', '?')}` {label} — {s.get('asOf', '')}")
        else:
            out.append(" · ".join(
                f"`T{s.get('tier', '?')}` [{s.get('name', '')}]({s['url']})" if s.get("url")
                else f"`T{s.get('tier', '?')}` {s.get('name', '')}" for s in src))

    if warnings:
        out += ["", "---", ""] + [f"*렌더 경고: {w}*" for w in warnings]

    out += ["", "---",
            f"*이 분석은 투자 판단 참고자료이며 투자 권유가 아니다. "
            f"분석 시점 {fmt.price(snap.get('price'), cur)}, 데이터 기준일 "
            f"{snap.get('asOf', r.get('analysisDate', ''))}.*"]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="stock-analyst 리포트 렌더러")
    ap.add_argument("format", choices=["html", "md", "brief"])
    ap.add_argument("file", nargs="?", default="-", help="report JSON (기본: stdin)")
    ap.add_argument("-o", "--out", help="출력 파일 (없으면 stdout)")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
    report = json.loads(raw)

    if args.format == "brief":
        text = brief(report)
    elif args.format == "md":
        text = markdown(report)
    else:
        import report_html
        text = report_html.render(*normalize(report))

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
        print(args.out)
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
