#!/usr/bin/env python3
"""Investment Committee 점수 집계 (문서 §26~28).

이 스크립트는 **제안 Rating(proposedRating)만** 낸다. 최종 Rating은 Committee
에이전트가 확정한다 — 점수만으로 자동 결정하지 않는다 (문서 §27).

CLI: python3 score.py <input.json|->
"""
from __future__ import annotations

import json
import sys

# 문서 §26 기본 가중치
WEIGHTS = {
    "business": 0.20,
    "growth": 0.15,
    "financial": 0.15,
    "valuation": 0.20,
    "technical": 0.10,
    "catalyst": 0.10,
    "risk": 0.10,
}

# 문서 §27 Rating 밴드 (하한 포함)
BANDS = [
    (9.0, "STRONG BUY"),
    (8.0, "BUY"),
    (7.0, "ACCUMULATE"),
    (5.5, "HOLD"),
    (4.0, "REDUCE"),
    (0.0, "AVOID"),
]

# 문서 §27 치명적 리스크 — 점수와 무관하게 Rating 하향을 강제 검토시킨다
CRITICAL_FLAGS = {
    "accounting": "회계 이슈",
    "goingConcern": "계속기업 불확실성",
    "fraud": "사기 리스크",
    "leverage": "극단적 레버리지",
    "regulation": "중대 규제 리스크",
    "dataReliability": "데이터 신뢰성 문제",
    "extremeValuation": "극단적 밸류에이션",
}

# 하향 트리거가 걸렸을 때 제안 Rating의 상한
FLAG_CAP = "HOLD"
RATING_ORDER = ["AVOID", "REDUCE", "HOLD", "ACCUMULATE", "BUY", "STRONG BUY"]


def band_for(score: float) -> str:
    for floor, label in BANDS:
        if score >= floor:
            return label
    return "AVOID"


def weighted_score(scores: dict) -> dict:
    """실행되지 않은 영역은 빼고 남은 가중치를 정규화한다."""
    used = {k: v for k, v in scores.items() if k in WEIGHTS and isinstance(v, (int, float))}
    if not used:
        return {"score": None, "weights": {}, "skipped": list(WEIGHTS)}
    total_w = sum(WEIGHTS[k] for k in used)
    norm = {k: WEIGHTS[k] / total_w for k in used}
    score = sum(used[k] * norm[k] for k in used)
    return {
        "score": round(score, 2),
        "weights": {k: round(v, 4) for k, v in norm.items()},
        "skipped": [k for k in WEIGHTS if k not in used],
        "contributions": {k: round(used[k] * norm[k], 3) for k in used},
    }


def confidence(inputs: dict) -> dict:
    """문서 §28 — 데이터 품질·신선도·애널리스트 일치도·밸류에이션 불확실성·이벤트 리스크."""
    spec = {
        "dataQuality": (0.30, False),
        "dataFreshness": (0.20, False),
        "analystAgreement": (0.20, False),
        "valuationUncertainty": (0.15, True),   # 높을수록 신뢰도를 깎는다
        "eventRisk": (0.15, True),
    }
    parts, total_w = {}, 0.0
    for key, (w, invert) in spec.items():
        v = inputs.get(key)
        if not isinstance(v, (int, float)):
            continue
        v = max(0.0, min(1.0, float(v)))
        parts[key] = round((1 - v) if invert else v, 3)
        total_w += w
    if not parts:
        return {"score": None, "level": "LOW", "breakdown": {},
                "note": "confidenceInputs가 비어 있어 신뢰도를 계산할 수 없다"}
    raw = sum(parts[k] * spec[k][0] for k in parts) / total_w
    pct = round(raw * 100)
    level = "HIGH" if pct >= 70 else "MEDIUM" if pct >= 45 else "LOW"
    return {"score": pct, "level": level, "breakdown": parts,
            "missingInputs": [k for k in spec if k not in parts]}


def check_flags(flags: dict) -> dict:
    triggered = [
        {"flag": k, "label": CRITICAL_FLAGS[k], "severity": v}
        for k, v in (flags or {}).items()
        if k in CRITICAL_FLAGS and str(v).lower() == "high"
    ]
    return {
        "triggered": triggered,
        "downgradeReviewRequired": bool(triggered),
        "suggestedCap": FLAG_CAP if triggered else None,
    }


def run(payload: dict) -> dict:
    scores = payload.get("scores") or {}
    coverage = payload.get("coverage") or {}
    agg = weighted_score(scores)
    conf = confidence(payload.get("confidenceInputs") or {})
    flags = check_flags(payload.get("riskFlags") or {})

    ratio = coverage.get("ratio")
    missing_sections = coverage.get("missingSections") or []
    insufficient = (
        agg["score"] is None
        or (isinstance(ratio, (int, float)) and ratio < 0.6)
        or len(agg["skipped"]) > 3
    )

    if insufficient:
        proposed = "INSUFFICIENT DATA"
        reason = "핵심 데이터 커버리지가 기준(60%) 미만이거나 평가 영역이 4개 이상 비어 있다 (문서 §68)."
    else:
        proposed = band_for(agg["score"])
        reason = f"가중 점수 {agg['score']}점 → {proposed} 밴드 (문서 §27)."
        if flags["triggered"] and RATING_ORDER.index(proposed) > RATING_ORDER.index(FLAG_CAP):
            reason += (
                f" 단 치명적 리스크 {len(flags['triggered'])}건이 high로 표시되어 "
                f"{FLAG_CAP} 이하로 하향할지 Committee가 반드시 검토해야 한다."
            )

    return {
        "ok": True,
        "ticker": payload.get("ticker"),
        "weightedScore": agg["score"],
        "weightsApplied": agg["weights"],
        "contributions": agg.get("contributions", {}),
        "skippedSections": agg["skipped"],
        "missingSections": missing_sections,
        "proposedRating": proposed,
        "proposedRatingReason": reason,
        "criticalRiskFlags": flags,
        "confidence": conf,
        "committeeInstruction": (
            "이 값은 제안일 뿐이다. Investment Committee 에이전트는 제안 Rating을 그대로 채택하거나 "
            "하향할 수 있으며, 어느 쪽이든 근거를 문장으로 남겨야 한다. 종합 점수가 높다는 이유로 "
            "high 등급 리스크를 무시해서는 안 된다 (문서 §54)."
        ),
    }


def main() -> int:
    src = sys.stdin.read() if (len(sys.argv) < 2 or sys.argv[1] == "-") else open(sys.argv[1]).read()
    json.dump(run(json.loads(src)), sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
