#!/usr/bin/env python3
"""에이전트 출력 검증 + Fact Checker (문서 §24, §51, Scenario D).

두 가지를 한다.
1. 스키마 검증 — 에이전트가 약속한 JSON 모양대로 냈는지 확인한다.
2. 숫자 교차검증 — 에이전트가 인용한 수치(citedFigures)를 캐시된 원본과 대조해
   허용오차를 벗어나면 CONFLICTED DATA로 표시한다.

Fact Checker를 LLM이 아니라 스크립트로 두는 이유는, 숫자 대조는 결정론적이어야
싸고 정확하기 때문이다.

CLI:
  python3 validate.py --agent fundamental out.json
  python3 validate.py --agent valuation out.json --ref ~/stock-research/cache/NVDA/financials.json
"""
from __future__ import annotations

import argparse
import json
import sys

NUM = (int, float)

# 에이전트별 출력 계약. 값은 (파이썬 타입, 필수 여부).
SCHEMAS: dict[str, dict] = {
    "fundamental": {
        "businessModel": (str, True),
        "revenueSegments": (list, False),
        "moat": (dict, True),
        "scores": (dict, True),
        "citedFigures": (list, False),
        "confidence": (NUM, True),
        "sources": (list, True),
    },
    "financial": {
        "growth": (dict, True),
        "profitability": (dict, True),
        "stability": (dict, True),
        "cashFlow": (dict, True),
        "scores": (dict, True),
        "citedFigures": (list, False),
        "confidence": (NUM, True),
        "sources": (list, True),
    },
    "valuation": {
        "currentMultiples": (dict, True),
        "vsHistory": (dict, True),
        "vsPeers": (dict, True),
        "dcfAssumptions": (dict, False),
        "verdict": (str, True),
        "score": (NUM, True),
        "citedFigures": (list, False),
        "confidence": (NUM, True),
        "sources": (list, True),
    },
    "technical": {
        "trend": (str, True),
        "levels": (dict, True),
        "observations": (list, True),
        "score": (NUM, True),
        "confidence": (NUM, True),
        "sources": (list, False),
    },
    "news": {
        "items": (list, True),
        "netAssessment": (str, True),
        "catalysts": (list, True),
        "score": (NUM, True),
        "confidence": (NUM, True),
        "sources": (list, True),
    },
    "macro": {
        "indicators": (dict, True),
        "linkage": (list, True),
        "netAssessment": (str, True),
        "confidence": (NUM, True),
        "sources": (list, True),
    },
    "bull": {
        "thesis": (list, True),
        "catalysts": (list, True),
        "priceTarget": (NUM, False),
        "probability": (NUM, False),
        "confidence": (NUM, True),
        "sources": (list, True),
    },
    "bear": {
        "thesis": (list, True),
        "pricedInExpectations": (list, True),
        "thesisBreakers": (list, True),
        "downsideScenario": (dict, True),
        "overlookedRisks": (list, True),
        "priceTarget": (NUM, False),
        "confidence": (NUM, True),
        "sources": (list, True),
    },
    "risk": {
        "matrix": (dict, True),
        "criticalFlags": (dict, True),
        "score": (NUM, True),
        "confidence": (NUM, True),
        "sources": (list, False),
    },
    "committee": {
        "finalRating": (str, True),
        "ratingRationale": (str, True),
        "strongestBullArgument": (str, True),
        "strongestBearArgument": (str, True),
        "pricedIn": (str, True),
        "whatWouldChangeMyMind": (list, True),
        "metricsToMonitor": (list, True),
        "confidence": (NUM, True),
    },
    "comparison": {
        "table": (list, True),
        "bestBusiness": (str, True),
        "bestGrowth": (str, True),
        "bestValuation": (str, True),
        "lowestRisk": (str, True),
        "bestOverall": (str, True),
        "rationale": (str, True),
    },
    # 렌더러(render.py)에 넘길 최종 리포트. 이 스키마를 통과해야 HTML/MD가 만들어진다.
    "report": {
        "ticker": (str, True),
        "name": (str, True),
        "mode": (str, True),
        "currency": (str, False),
        "market": (str, False),
        "analysisDate": (str, True),
        "verdict": (dict, True),
        "snapshot": (dict, True),
        "scores": (list, False),
        "sections": (list, True),
        "scenarios": (list, False),
        "risks": (list, False),
        "criticalFlags": (dict, False),
        "changeMyMind": (list, True),
        "unavailable": (list, False),
        "sources": (list, True),
    },
    "portfolio": {
        "concentration": (dict, True),
        "singleStockRisk": (list, True),
        "overlap": (list, True),
        "observations": (list, True),
        "positionSizingWithheld": (bool, True),
    },
}

VALID_RATINGS = {"STRONG BUY", "BUY", "ACCUMULATE", "HOLD", "REDUCE", "AVOID", "INSUFFICIENT DATA"}
SEVERITY = {"low", "medium", "high", "unknown"}


def validate_schema(agent: str, obj) -> dict:
    schema = SCHEMAS.get(agent)
    if schema is None:
        return {"ok": False, "errors": [f"알 수 없는 에이전트: {agent}"],
                "knownAgents": sorted(SCHEMAS)}
    if not isinstance(obj, dict):
        return {"ok": False, "errors": ["최상위가 JSON 객체가 아니다"]}

    errors, warnings = [], []
    for field, (typ, required) in schema.items():
        if field not in obj or obj[field] is None:
            (errors if required else warnings).append(
                f"{'필수' if required else '선택'} 필드 누락: {field}")
            continue
        if not isinstance(obj[field], typ):
            want = typ.__name__ if not isinstance(typ, tuple) else "/".join(t.__name__ for t in typ)
            errors.append(f"{field} 타입 불일치: {type(obj[field]).__name__} (기대: {want})")

    extra = [k for k in obj if k not in schema]
    if extra:
        warnings.append(f"스키마에 없는 필드: {', '.join(sorted(extra))}")

    conf = obj.get("confidence")
    if isinstance(conf, NUM) and not 0 <= conf <= 1:
        errors.append(f"confidence는 0~1이어야 한다 (받은 값: {conf})")

    if agent == "committee":
        rating = obj.get("finalRating")
        if rating and rating not in VALID_RATINGS:
            errors.append(f"finalRating이 허용 목록에 없다: {rating}")
        if isinstance(obj.get("whatWouldChangeMyMind"), list) and len(obj["whatWouldChangeMyMind"]) < 2:
            errors.append("whatWouldChangeMyMind는 최소 2개 이상이어야 한다 (문서 §34)")

    if agent == "risk":
        for k, v in (obj.get("criticalFlags") or {}).items():
            if str(v).lower() not in SEVERITY:
                errors.append(f"criticalFlags.{k} 값이 low/medium/high/unknown이 아니다: {v}")

    if agent == "report":
        v = obj.get("verdict") or {}
        if v.get("rating") and v["rating"] not in VALID_RATINGS:
            errors.append(f"verdict.rating이 허용 목록에 없다: {v['rating']}")
        if not v.get("headline"):
            errors.append("verdict.headline이 없다 — 결론 한 문장은 리포트 최상단에 반드시 들어간다")
        for sec in obj.get("sections") or []:
            if not isinstance(sec, dict):
                errors.append("sections 항목이 객체가 아니다")
                continue
            for f in ("title", "body"):
                if not sec.get(f):
                    errors.append(f"섹션 '{sec.get('title', '?')}'에 {f}가 없다")
            if not sec.get("takeaway"):
                warnings.append(f"섹션 '{sec.get('title', '?')}'에 takeaway가 없다 "
                                f"— 접힌 상태에서 요약이 보이지 않는다")
        if isinstance(obj.get("changeMyMind"), list) and len(obj["changeMyMind"]) < 2:
            errors.append("changeMyMind는 최소 2개다 (문서 §34)")
        snap = obj.get("snapshot") or {}
        if snap.get("price") is None:
            errors.append("snapshot.price가 없다 — 분석 시점 주가 없이 리포트를 내지 않는다")

    if agent == "bear":
        for field in ("thesis", "thesisBreakers"):
            if isinstance(obj.get(field), list) and not obj[field]:
                errors.append(f"{field}가 비어 있다 — Bear Case는 생략할 수 없다 (문서 §2.3)")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _lookup(ref: dict, path: str):
    cur = ref
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def factcheck(obj: dict, ref: dict, tolerance: float = 0.01) -> dict:
    """citedFigures를 캐시 원본과 대조한다.

    에이전트는 인용한 수치를 다음 형태로 함께 내야 한다:
      {"path": "latest.revenue", "value": 215900000000, "label": "FY2026 매출"}
    path가 원본에 없으면 검증 불가로 표시하고, 값이 다르면 CONFLICTED로 표시한다.
    """
    figures = obj.get("citedFigures") or []
    if not isinstance(figures, list):
        return {"ok": False, "checked": 0, "conflicts": [],
                "note": "citedFigures가 배열이 아니다"}

    conflicts, unverifiable, verified = [], [], []
    for fig in figures:
        if not isinstance(fig, dict):
            unverifiable.append({"figure": fig, "reason": "객체가 아님"})
            continue
        path, value = fig.get("path"), fig.get("value")
        if not path or not isinstance(value, NUM):
            unverifiable.append({"figure": fig, "reason": "path 또는 수치 value 없음"})
            continue
        actual = _lookup(ref, path)
        if not isinstance(actual, NUM):
            unverifiable.append({"figure": fig, "reason": f"원본에 {path} 없음"})
            continue
        if actual == 0:
            ok = value == 0
            diff = None
        else:
            diff = abs(value - actual) / abs(actual)
            ok = diff <= tolerance
        entry = {"path": path, "claimed": value, "actual": actual,
                 "relativeDiff": round(diff, 4) if diff is not None else None,
                 "label": fig.get("label")}
        (verified if ok else conflicts).append(entry)

    return {
        "ok": not conflicts,
        "checked": len(figures),
        "verified": verified,
        "conflicts": conflicts,
        "unverifiable": unverifiable,
        "flag": "CONFLICTED DATA" if conflicts else None,
        "tolerance": tolerance,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="에이전트 출력 스키마 검증 + 숫자 교차검증")
    ap.add_argument("file", nargs="?", default="-", help="에이전트 출력 JSON (기본: stdin)")
    ap.add_argument("--agent", required=True, help=f"에이전트 이름 ({', '.join(sorted(SCHEMAS))})")
    ap.add_argument("--ref", help="교차검증 기준이 될 캐시 JSON (예: financials.json)")
    ap.add_argument("--tolerance", type=float, default=0.01, help="허용 상대오차 (기본 1%%)")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.file == "-" else open(args.file).read()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        json.dump({"ok": False, "stage": "parse",
                   "errors": [f"JSON 파싱 실패: {exc}"],
                   "repairInstruction": "코드펜스 없이 유효한 JSON 객체 하나만 다시 출력하라."},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 1

    result = {"agent": args.agent, "schema": validate_schema(args.agent, obj)}
    if args.ref:
        ref_payload = json.loads(open(args.ref).read())
        ref = ref_payload.get("data", ref_payload)
        result["factcheck"] = factcheck(obj, ref, args.tolerance)

    result["ok"] = result["schema"]["ok"] and result.get("factcheck", {"ok": True})["ok"]
    if not result["schema"]["ok"]:
        result["repairInstruction"] = (
            "다음 오류만 고쳐서 같은 JSON을 다시 출력하라 (분석 내용은 바꾸지 말 것): "
            + "; ".join(result["schema"]["errors"])
        )
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
