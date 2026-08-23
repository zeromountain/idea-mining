#!/usr/bin/env python3
"""에이전트 출력 검증 + Fact Checker.

stock-analyst/scripts/validate.py와 같은 역할을 한다 — 스키마 검증과 citedFigures
교차검증. 크로스플러그인 import는 마켓플레이스 캐시 설치 경로에서 깨지므로
가져오지 않고 통째로 복제한다.

_lookup에 stock-analyst판에는 없는 두 세그먼트 형태를 추가했다: '#id'(리스트 원소를
id로 찾기, 권장)와 '[n]'(숫자 인덱스). liabilities·goals가 리스트라서 필요하다.

CLI:
  python3 validate.py --agent debt-manager out.json
  python3 validate.py --agent context ~/wealth/financial-context.json
"""
from __future__ import annotations

import argparse
import json
import sys

NUM = (int, float)

# 8개 신규 에이전트 + report + arbitration + context 공통 필수 코어.
# unknownImpact를 필수로 둔 것이 "UNKNOWN 데이터의 영향을 명확히 알린다"를
# 소망에서 검증 에러로 바꾸는 장치다.
_COMMON = {
    "dataBasis": (list, True),
    "citedFigures": (list, False),
    "confidence": (NUM, True),
    "unknownImpact": (list, True),
}

SCHEMAS: dict[str, dict] = {
    "cashflow-analyst": {
        **_COMMON,
        "assessment": (str, True),
        "metrics": (dict, True),
        "surplusVerdict": (str, True),
        "structuralIssues": (list, True),
    },
    "savings-strategist": {
        **_COMMON,
        "currentSavingsRate": (NUM, True),
        "targetSavingsRate": (NUM, True),
        "allocationPlan": (list, True),
        "emergencyFundStatus": (dict, True),
        "sequencing": (list, True),
    },
    "spending-analyst": {
        **_COMMON,
        "patterns": (list, True),
        "topLeaks": (list, True),
        "nonNegotiables": (list, True),
        "reductionPotential": (dict, True),
    },
    "debt-manager": {
        **_COMMON,
        "debtInventory": (list, True),
        "payoffOrder": (list, True),
        "refinanceOpportunities": (list, False),
        "prepayVsInvest": (dict, False),
        "riskFlags": (dict, True),
    },
    "insurance-manager": {
        **_COMMON,
        "premiumBurden": (dict, True),
        "coverageGaps": (list, True),
        "duplicates": (list, True),
        "overInsured": (list, True),
        "recommendations": (list, True),
    },
    "goal-manager": {
        **_COMMON,
        "goals": (list, True),
        "conflicts": (list, True),
        "sequencingProposal": (list, True),
        "infeasible": (list, True),
        "tradeoffs": (list, True),
    },
    "financial-risk-manager": {
        **_COMMON,
        "matrix": (dict, True),
        "criticalFlags": (dict, True),
        "stressResults": (list, True),
        "score": (NUM, True),
        "scoreDirectionNote": (str, True),
    },
    "real-estate-liaison": {
        **_COMMON,
        "question": (str, True),
        "apiCalls": (list, True),
        "findings": (dict, True),
        "approvalNote": (str, True),
        "notComputable": (list, False),
    },
    "report": {
        "mode": (str, True),
        "asOf": (str, True),
        "verdict": (dict, True),
        "snapshot": (dict, True),
        "decisionTable": (dict, False),
        "sections": (list, True),
        "actions": (list, True),
        "risks": (list, False),
        "unknowns": (list, True),
        "dataBasis": (list, True),
    },
    "arbitration": {
        "gates": (list, True),
        "decisions": (list, True),
        "allocation": (dict, True),
        "policyVersion": (str, True),
    },
    "context": {
        "schemaVersion": (int, True),
        "profile": (dict, False),
        "income": (dict, False),
        "assets": (dict, False),
        "liabilities": (list, False),
        "monthlyExpenses": (dict, False),
        "insurance": (dict, False),
        "goals": (list, False),
        "riskProfile": (dict, False),
        "upcomingEvents": (list, False),
    },
}

CLOSED_VOCAB = {
    "surplusVerdict": {"SURPLUS", "BREAKEVEN", "DEFICIT", "NOT_COMPUTABLE"},
    "recommendations[].type": {"REVIEW", "REDUCE_RIDER", "ADD_COVERAGE", "CONSULT_PROFESSIONAL"},
}
SEVERITY = {"low", "medium", "high", "unknown"}
GATE_STATUS = {"OPEN", "BREACHED", "UNKNOWN"}
VERDICTS = {"ADMITTED", "PARTIAL", "DEFERRED", "BLOCKED", "ADMITTED_WITH_OVERRIDE"}


def validate_schema(agent: str, obj) -> dict:
    schema = SCHEMAS.get(agent)
    if schema is None:
        return {"ok": False, "errors": [f"알 수 없는 에이전트: {agent}"], "knownAgents": sorted(SCHEMAS)}
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

    conf = obj.get("confidence")
    if isinstance(conf, NUM) and not 0 <= conf <= 1:
        errors.append(f"confidence는 0~1이어야 한다 (받은 값: {conf})")

    # 확신을 주장하려면 데이터가 있어야 한다: unknownImpact가 비었는데 confidence>0.8이면
    # coverage.overall==1.0으로 --ref-coverage를 넘기지 않는 한 에러다.
    if agent in ("cashflow-analyst", "savings-strategist", "spending-analyst", "debt-manager",
                 "insurance-manager", "goal-manager", "financial-risk-manager", "real-estate-liaison"):
        ui = obj.get("unknownImpact")
        if isinstance(ui, list) and not ui and isinstance(conf, NUM) and conf > 0.8:
            errors.append("unknownImpact가 비어 있으면서 confidence > 0.8이다 — "
                           "확신을 주장하려면 데이터가 있어야 한다 (coverage.overall==1.0이면 예외)")

    if agent == "cashflow-analyst":
        sv = obj.get("surplusVerdict")
        if sv and sv not in CLOSED_VOCAB["surplusVerdict"]:
            errors.append(f"surplusVerdict가 허용 목록에 없다: {sv}")

    if agent == "debt-manager":
        pvi = obj.get("prepayVsInvest")
        if isinstance(pvi, dict):
            certain, uncertain = pvi.get("certain"), pvi.get("uncertain")
            if not isinstance(certain, dict) or not isinstance(uncertain, dict):
                errors.append("prepayVsInvest에는 certain과 uncertain이 둘 다 객체로 있어야 한다")
            else:
                if certain.get("kind") == uncertain.get("kind"):
                    errors.append("prepayVsInvest.certain과 uncertain의 kind가 같다 — "
                                  "확정 이자절감과 기대 투자수익은 다른 kind여야 한다")
                if "netBenefit" in pvi or isinstance(pvi.get("verdict"), str):
                    errors.append("prepayVsInvest에 netBenefit 스칼라나 verdict 문자열이 있다 — "
                                  "금지된 형태다 (문서 §33). dominance만 허용한다")

    if agent == "insurance-manager":
        for rec in obj.get("recommendations") or []:
            if isinstance(rec, dict) and rec.get("type") not in CLOSED_VOCAB["recommendations[].type"]:
                errors.append(f"recommendations[].type이 닫힌 집합 밖이다: {rec.get('type')}")

    if agent == "financial-risk-manager":
        matrix = obj.get("matrix") or {}
        for k, v in matrix.items():
            if k == "evidence":
                continue
            if str(v).lower() not in SEVERITY:
                errors.append(f"matrix.{k} 값이 low/medium/high/unknown이 아니다: {v}")
        for k, v in (obj.get("criticalFlags") or {}).items():
            if str(v).lower() not in SEVERITY:
                errors.append(f"criticalFlags.{k} 값이 low/medium/high/unknown이 아니다: {v}")

    if agent == "real-estate-liaison":
        if not (obj.get("approvalNote") or "").strip():
            errors.append("approvalNote가 비어 있다 — API 원문을 그대로 날라야 한다 (문서 §17)")

    if agent == "report":
        for a in obj.get("actions") or []:
            if not isinstance(a, (str, dict)):
                errors.append("actions 항목이 문자열/객체가 아니다")
        if isinstance(obj.get("unknowns"), list) and not obj.get("unknowns") and \
                isinstance(obj.get("verdict"), dict) and obj["verdict"].get("confidence") == "HIGH":
            warnings.append("unknowns가 비어 있는데 confidence가 HIGH다 — 재확인한다")

    if agent == "arbitration":
        for g in obj.get("gates") or []:
            if isinstance(g, dict) and g.get("status") not in GATE_STATUS:
                errors.append(f"gates[].status가 허용 목록에 없다: {g.get('status')}")
        for d in obj.get("decisions") or []:
            if isinstance(d, dict) and d.get("verdict") not in VERDICTS:
                errors.append(f"decisions[].verdict가 허용 목록에 없다: {d.get('verdict')}")
            if isinstance(d, dict) and d.get("verdict") == "BLOCKED" and not d.get("unblockCondition"):
                errors.append(f"decisions[{d.get('proposalId', '?')}]가 BLOCKED인데 "
                              f"unblockCondition이 없다 — 차단은 항상 해제 조건을 동반한다")

    extra = [k for k in obj if k not in schema]
    if extra:
        warnings.append(f"스키마에 없는 필드: {', '.join(sorted(extra))}")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _lookup(ref, path: str):
    """dict/list 혼합 구조를 점경로로 찾는다. '#id'와 '[n]' 세그먼트를 지원한다.

    stock-analyst판과 달리 리스트를 주소지정할 수 있다 — liabilities#jeonse-loan.balance.
    숫자 인덱스([n])는 리스트가 재정렬되면 조용히 다른 항목을 가리키므로 #id를 권장한다.
    """
    cur = ref
    for part in path.split("."):
        if "#" in part:
            key, ident = part.split("#", 1)
            cur = cur.get(key) if isinstance(cur, dict) else None
            if not isinstance(cur, list):
                return None
            cur = next((x for x in cur if isinstance(x, dict) and str(x.get("id")) == ident), None)
        elif part.startswith("[") and part.endswith("]") and part[1:-1].lstrip("-").isdigit():
            if not isinstance(cur, list):
                return None
            try:
                cur = cur[int(part[1:-1])]
            except IndexError:
                return None
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def factcheck(obj: dict, ref: dict, tolerance: float = 0.01) -> dict:
    figures = obj.get("citedFigures") or []
    if not isinstance(figures, list):
        return {"ok": False, "checked": 0, "conflicts": [], "note": "citedFigures가 배열이 아니다"}

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
            ok, diff = value == 0, None
        else:
            diff = abs(value - actual) / abs(actual)
            ok = diff <= tolerance
        entry = {"path": path, "claimed": value, "actual": actual,
                 "relativeDiff": round(diff, 4) if diff is not None else None, "label": fig.get("label")}
        (verified if ok else conflicts).append(entry)

    return {"ok": not conflicts, "checked": len(figures), "verified": verified,
            "conflicts": conflicts, "unverifiable": unverifiable,
            "flag": "CONFLICTED DATA" if conflicts else None, "tolerance": tolerance}


def main() -> int:
    ap = argparse.ArgumentParser(description="wealth-manager 에이전트 출력 스키마 검증 + 숫자 교차검증")
    ap.add_argument("file", nargs="?", default="-")
    ap.add_argument("--agent", required=True, help=f"({', '.join(sorted(SCHEMAS))})")
    ap.add_argument("--ref", help="교차검증 기준이 될 JSON (예: financial-context.resolved.json)")
    ap.add_argument("--tolerance", type=float, default=0.01)
    args = ap.parse_args()

    raw = sys.stdin.read() if args.file == "-" else open(args.file).read()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        json.dump({"ok": False, "stage": "parse", "errors": [f"JSON 파싱 실패: {exc}"],
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
            + "; ".join(result["schema"]["errors"]))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
