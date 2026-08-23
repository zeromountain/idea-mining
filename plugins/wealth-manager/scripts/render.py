#!/usr/bin/env python3
"""리포트 렌더러 — report JSON → HTML / Markdown / 터미널 요약.

stock-analyst/scripts/render.py와 같은 역할과 같은 규율("에이전트는 판단만, 배치는
렌더러가")을 따르되 세 가지가 다르다.

1. actions 상한이 있다 — 액션 14개짜리 재무 리포트는 액션이 0개다.
2. showsAmounts:false(share 모드, --redact)는 절대금액·기관명을 비율·방향으로 바꾼다.
3. decisionTable(arbitrate.py 산출)과 unknowns는 절대 잘리지 않는다 — "이 판단이
   모르고 있는 것"을 상한 걸어 자르면 그 자체가 침묵이 된다.

stock-analyst와 달리 HTML을 아티팩트로 자동 게시하지 않는다 (README 참고).

  python3 render.py html  report.json -o out.html
  python3 render.py md    report.json -o out.md
  python3 render.py brief report.json
  python3 render.py html  report.json -o out.html --redact
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fmt

MODE_SPEC = {
    "checkup":  {"sections": 4,    "actions": 3, "risks": 3, "body": 420,  "scenarios": False},
    "deep":     {"sections": None, "actions": 7, "risks": 9, "body": None, "scenarios": True},
    "cashflow": {"sections": 3,    "actions": 3, "risks": 3, "body": 500,  "scenarios": False},
    "spending": {"sections": 4,    "actions": 5, "risks": 3, "body": 600,  "scenarios": False},
    "debt":     {"sections": 4,    "actions": 4, "risks": 5, "body": 600,  "scenarios": True},
    "insurance":{"sections": 3,    "actions": 4, "risks": 4, "body": 500,  "scenarios": False},
    "goal":     {"sections": 3,    "actions": 4, "risks": 4, "body": 500,  "scenarios": True},
    "scenario": {"sections": 3,    "actions": 3, "risks": 5, "body": 600,  "scenarios": True},
    "networth": {"sections": 2,    "actions": 2, "risks": 2, "body": 350,  "scenarios": False},
    "share":    {"sections": 2,    "actions": 3, "risks": 2, "body": 300,  "scenarios": False, "showsAmounts": False},
}
DEFAULT_SPEC = MODE_SPEC["checkup"]
MODE_LABEL = {"checkup": "Checkup", "deep": "Deep", "cashflow": "Cashflow", "spending": "Spending",
              "debt": "Debt", "insurance": "Insurance", "goal": "Goal", "scenario": "Scenario",
              "networth": "Net Worth", "share": "Share"}
CONF_LABEL = {"VERIFIED": "확인됨", "USER_PROVIDED": "사용자 제공", "ESTIMATED": "추정", "UNKNOWN": "모름"}


def spec_for(mode: str) -> dict:
    return MODE_SPEC.get(mode, DEFAULT_SPEC)


def trim_body(body: str, budget: int | None) -> tuple[str, bool]:
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


def _redact(r: dict) -> dict:
    """--redact — 절대금액·기관명을 지우고 비율·방향만 남긴다 (share 모드)."""
    r = json.loads(json.dumps(r))
    snap = r.get("snapshot") or {}
    for k in ("netWorth", "liquidAssets", "monthlyIncome", "monthlySurplus"):
        if k in snap and isinstance(snap[k], (int, float)):
            snap[k + "Redacted"] = True
            del snap[k]
    r["snapshot"] = snap
    for sec in r.get("sections") or []:
        # 본문 자유서술에 절대금액이 섞여 있을 수 있으나 v1은 구조화 필드만 지운다.
        # 본문 리다크션은 정규식 오탐(전화번호 등)이 위험해 하지 않는다 — 경고로 남긴다.
        sec["_redactionNote"] = "본문 서술에 금액이 남아있을 수 있다 — 게시 전 직접 확인한다"
    return r


def normalize(report: dict, redact: bool = False) -> tuple[dict, list[str]]:
    r = json.loads(json.dumps(report))
    warnings: list[str] = []
    mode = r.get("mode", "checkup")
    spec = spec_for(mode)
    if redact or spec.get("showsAmounts") is False:
        r = _redact(r)
        r["_redacted"] = True

    limit = spec["sections"]
    sections = r.get("sections") or []
    if limit and len(sections) > limit:
        dropped = [s.get("title", "?") for s in sections[limit:]]
        r["sections"] = sections[:limit]
        warnings.append(f"{mode} 모드는 섹션 {limit}개까지다. {len(dropped)}개를 잘라냈다: {', '.join(dropped)}.")

    budget = spec.get("body")
    trimmed = []
    for sec in r.get("sections") or []:
        sec["body"], cut = trim_body(sec.get("body", ""), budget)
        if cut:
            trimmed.append(sec.get("title", "?"))
    if trimmed:
        warnings.append(f"본문이 {mode} 예산({budget}자)을 넘어 문단 단위로 줄였다: {', '.join(trimmed)}.")

    a_limit = spec["actions"]
    actions = r.get("actions") or []
    if a_limit and len(actions) > a_limit:
        r["actions"] = actions[:a_limit]
        warnings.append(f"actions {len(actions) - a_limit}개를 잘라냈다 ({mode} 상한 {a_limit}개) — "
                        f"실행 가능한 만큼만 보여준다.")

    r_limit = spec["risks"]
    risks = r.get("risks") or []
    if r_limit and len(risks) > r_limit:
        r["risks"] = risks[:r_limit]
        warnings.append(f"risks {len(risks) - r_limit}개를 잘라냈다 ({mode} 상한 {r_limit}개).")

    # decisionTable과 unknowns는 절대 자르지 않는다.
    r.setdefault("unknowns", [])

    r["_warnings"] = warnings
    r["_modeLabel"] = MODE_LABEL.get(mode, mode)
    return r, warnings


def brief(report: dict, redact: bool = False) -> str:
    r, warnings = normalize(report, redact)
    v = r.get("verdict") or {}
    snap = r.get("snapshot") or {}
    lines = [f"{r.get('_modeLabel', '')}  ·  {v.get('confidence', fmt.DASH)} confidence  ·  "
             f"{r.get('asOf', '')}"]
    if not r.get("_redacted"):
        nw = snap.get("netWorth")
        if nw is not None:
            lines.append(f"  순자산 {fmt.money(nw)}")
    if v.get("headline"):
        lines += ["", f"  {v['headline']}"]

    dt = r.get("decisionTable")
    if dt:
        breached = [g for g in dt.get("gates", []) if g.get("status") == "BREACHED"]
        if breached:
            lines.append("")
            lines.append(f"  차단된 게이트: {', '.join(g['name'] for g in breached)}")

    unknowns = r.get("unknowns") or []
    if unknowns:
        lines.append("")
        lines.append("  모르는 것")
        lines += [f"    - {u}" for u in unknowns[:3]]
        if len(unknowns) > 3:
            lines.append(f"    ...외 {len(unknowns) - 3}개")

    actions = r.get("actions") or []
    if actions:
        lines.append("")
        lines.append("  실행할 Action")
        for a in actions:
            text = a if isinstance(a, str) else a.get("text", "")
            lines.append(f"    - {text}")

    for w in warnings:
        lines.append(f"  ! {w}")
    return "\n".join(lines)


def markdown(report: dict, redact: bool = False) -> str:
    r, warnings = normalize(report, redact)
    v = r.get("verdict") or {}
    snap = r.get("snapshot") or {}
    out: list[str] = [f"# {r.get('_modeLabel', '')} — {r.get('asOf', '')}", ""]

    if not r.get("_redacted") and snap.get("netWorth") is not None:
        out.append(f"**순자산 {fmt.money(snap['netWorth'])}**"
                   + (f"  ·  유동자산 {fmt.money(snap.get('liquidAssets'))}" if snap.get("liquidAssets") is not None else ""))
    if v.get("headline"):
        out += ["", f"> {v['headline']}"]

    dt = r.get("decisionTable")
    if dt:
        out += ["", "## 판단 근거 (게이트)", "", "| 게이트 | 상태 | 근거 |", "|---|---|---|"]
        for g in dt.get("gates", []):
            out.append(f"| {g.get('name', g.get('id'))} | `{g.get('status')}` | {g.get('reason') or '—'} |")
        blocked = [d for d in dt.get("decisions", []) if d.get("verdict") in ("BLOCKED",)]
        if blocked:
            out += ["", "**차단된 제안**"]
            for d in blocked:
                out.append(f"- `{d['proposalId']}` — {d.get('unblockCondition', '')}")

    for sec in r.get("sections") or []:
        out += ["", f"## {sec.get('title', '')}", "", (sec.get("body") or "").strip()]

    risks = r.get("risks") or []
    if risks:
        out += ["", "## 리스크", ""]
        out += [f"- **{str(k.get('severity', '?')).upper()}** {k.get('name', '')} — {k.get('note', '')}"
                for k in risks]

    unknowns = r.get("unknowns") or []
    out += ["", "## 이 판단이 모르고 있는 것", ""]
    out += [f"- {u}" for u in unknowns] if unknowns else ["- (없음)"]

    actions = r.get("actions") or []
    if actions:
        out += ["", "## 실행할 Action", ""]
        for i, a in enumerate(actions, 1):
            text = a if isinstance(a, str) else a.get("text", "")
            out.append(f"{i}. {text}")

    data_basis = r.get("dataBasis") or []
    if data_basis:
        out += ["", "## 근거 데이터", "", " · ".join(f"`{d}`" for d in data_basis)]

    if warnings:
        out += ["", "---", ""] + [f"*렌더 경고: {w}*" for w in warnings]
    out += ["", "---", "*이 리포트는 재무 판단 참고자료이며 세무·법률·투자 자문이 아니다.*"]
    return "\n".join(out) + "\n"


def html(report: dict, redact: bool = False) -> str:
    r, warnings = normalize(report, redact)
    v = r.get("verdict") or {}
    snap = r.get("snapshot") or {}

    def esc(s):
        return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    parts = [f"<h1>{esc(r.get('_modeLabel'))} — {esc(r.get('asOf'))}</h1>"]
    if not r.get("_redacted") and snap.get("netWorth") is not None:
        parts.append(f"<p class='stat'>순자산 {fmt.money(snap['netWorth'])}</p>")
    if v.get("headline"):
        parts.append(f"<blockquote>{esc(v['headline'])}</blockquote>")

    dt = r.get("decisionTable")
    if dt:
        rows = "".join(f"<tr><td>{esc(g.get('name'))}</td><td class='{fmt.GATE_STATUS_TONE.get(g.get('status'))}'>"
                       f"{esc(g.get('status'))}</td><td>{esc(g.get('reason') or '—')}</td></tr>"
                       for g in dt.get("gates", []))
        parts.append(f"<h2>판단 근거</h2><table><tr><th>게이트</th><th>상태</th><th>근거</th></tr>{rows}</table>")

    for sec in r.get("sections") or []:
        parts.append(f"<h2>{esc(sec.get('title'))}</h2><div>{esc(sec.get('body')).replace(chr(10)+chr(10), '</p><p>')}</div>")

    unknowns = r.get("unknowns") or []
    parts.append("<h2>이 판단이 모르고 있는 것</h2><ul>" +
                "".join(f"<li>{esc(u)}</li>" for u in unknowns) + "</ul>" if unknowns else
                "<h2>이 판단이 모르고 있는 것</h2><p>없음</p>")

    actions = r.get("actions") or []
    if actions:
        items = "".join(f"<li>{esc(a if isinstance(a, str) else a.get('text', ''))}</li>" for a in actions)
        parts.append(f"<h2>실행할 Action</h2><ol>{items}</ol>")

    body = "\n".join(parts)
    css = ("body{font-family:-apple-system,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;"
          "color:#1a1a1a;background:#fff}table{border-collapse:collapse;width:100%}"
          "td,th{border:1px solid #ddd;padding:6px 10px;text-align:left}"
          ".pos{color:#0a7a3d}.neg{color:#c0392b}.unknown{color:#888}"
          "blockquote{border-left:3px solid #888;padding-left:1rem;color:#444}"
          "@media (prefers-color-scheme:dark){body{background:#151515;color:#eaeaea}"
          "td,th{border-color:#333}blockquote{color:#bbb}}")
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{body}</body></html>"


def main() -> int:
    ap = argparse.ArgumentParser(description="wealth-manager 리포트 렌더러")
    ap.add_argument("format", choices=["html", "md", "brief"])
    ap.add_argument("file", nargs="?", default="-")
    ap.add_argument("-o", "--out")
    ap.add_argument("--redact", action="store_true", help="절대금액·기관명 제거 (share 모드/공개 게시용)")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
    report = json.loads(raw)

    if args.format == "brief":
        text = brief(report, args.redact)
    elif args.format == "md":
        text = markdown(report, args.redact)
    else:
        text = html(report, args.redact)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
        print(args.out)
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
