#!/usr/bin/env python3
"""게이트 기반 우선순위 중재 — 이 시스템의 심장.

순서는 이 스크립트가 결정론적으로 계산하고, 문장은 오케스트레이터(LLM)가 쓴다.
같은 입력이면 항상 같은 출력이 나온다 — 그것이 이 스크립트가 존재하는 유일한 이유다.
에이전트가 낸 제안(proposals)을 인정/유예/차단만 한다. 산문을 쓰지 않고 추천을
만들지도 않는다.

CLI:
  python3 arbitrate.py --in proposals.json [--policy arbitration-v1]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wealth_common as wc

POLICY_VERSION = "arbitration-v1"

# 레벨 1이 최우선. 문서 §6/§7/§28의 순서 그대로다.
CATEGORY_LEVEL = {
    "STABILITY": 1, "LIQUIDITY": 2, "DEBT_RISK": 3,
    "NEAR_TERM_GOAL": 4, "INSURANCE": 5, "INVESTMENT_OPPORTUNITY": 6,
}
LEVEL_NAME = {v: k for k, v in CATEGORY_LEVEL.items()}

# 고금리부채 임계값. 15.4% 금융소득세 차감 후 어떤 방어 가능한 장기 주식 기대수익도
# 넘어서는 확정·무위험 수익률(0.07/(1-0.154) ≈ 8.3% 세전 허들)에서 근거한다.
# 데이터로 두고 버전을 붙여 반박 가능하게 한다 — arbitrate.py 안의 유일한 매직넘버.
HIGH_INTEREST_RATE_THRESHOLD = 0.07
EMERGENCY_FUND_TARGET_MONTHS = 3
CERTAINTY_ORDER = {"CERTAIN": 0, "EXPECTED": 1, "SPECULATIVE": 2}
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"


def _circle(i: int) -> str:
    return CIRCLED[i] if i < len(CIRCLED) else f"({i + 1})"


def evaluate_gates(state: dict) -> list[dict]:
    gates = []

    ef_months = state.get("emergencyFundMonths")
    if ef_months is None:
        g1 = {"id": "G1", "level": 1, "name": "소득중단 대비", "status": "UNKNOWN",
              "observed": None, "threshold": EMERGENCY_FUND_TARGET_MONTHS,
              "reason": "emergencyFundMonths를 알 수 없다"}
    elif ef_months < EMERGENCY_FUND_TARGET_MONTHS:
        g1 = {"id": "G1", "level": 1, "name": "소득중단 대비", "status": "BREACHED",
              "observed": ef_months, "threshold": EMERGENCY_FUND_TARGET_MONTHS,
              "reason": f"비상자금 {ef_months}개월 (목표 {EMERGENCY_FUND_TARGET_MONTHS}개월 미달)"}
    else:
        g1 = {"id": "G1", "level": 1, "name": "소득중단 대비", "status": "OPEN",
              "observed": ef_months, "threshold": EMERGENCY_FUND_TARGET_MONTHS, "reason": None}
    gates.append(g1)

    surplus, cash, fixed = state.get("monthlySurplus"), state.get("cashBalance"), state.get("monthlyFixed")
    if surplus is None or cash is None or fixed is None:
        g2 = {"id": "G2", "level": 2, "name": "유동성", "status": "UNKNOWN",
              "observed": None, "threshold": None, "reason": "잉여현금 또는 현금잔액을 알 수 없다"}
    elif surplus <= 0 or cash < fixed:
        g2 = {"id": "G2", "level": 2, "name": "유동성", "status": "BREACHED",
              "observed": {"surplus": surplus, "cash": cash, "monthlyFixed": fixed}, "threshold": None,
              "reason": f"잉여 {surplus:,}원 또는 현금잔액 {cash:,}원이 고정비 {fixed:,}원에 못 미친다"
              if surplus > 0 else f"잉여현금이 음수다 ({surplus:,}원)"}
    else:
        g2 = {"id": "G2", "level": 2, "name": "유동성", "status": "OPEN",
              "observed": {"surplus": surplus, "cash": cash}, "threshold": None, "reason": None}
    gates.append(g2)

    max_rate = state.get("maxDebtRate")
    coverage_liab = (state.get("coverage") or {}).get("liabilities", 1.0)
    if coverage_liab is not None and coverage_liab < 1.0:
        g3 = {"id": "G3", "level": 3, "name": "고위험부채", "status": "UNKNOWN",
              "observed": max_rate, "threshold": HIGH_INTEREST_RATE_THRESHOLD,
              "reason": f"부채 정보 커버리지가 {coverage_liab:.0%}다 — 미확인 부채에 고금리가 "
                        f"있을 수 있어 모르는 것 자체가 위험이다"}
    elif max_rate is None:
        g3 = {"id": "G3", "level": 3, "name": "고위험부채", "status": "UNKNOWN",
              "observed": None, "threshold": HIGH_INTEREST_RATE_THRESHOLD, "reason": "최고금리 부채를 알 수 없다"}
    elif max_rate >= HIGH_INTEREST_RATE_THRESHOLD:
        g3 = {"id": "G3", "level": 3, "name": "고위험부채", "status": "BREACHED",
              "observed": max_rate, "threshold": HIGH_INTEREST_RATE_THRESHOLD,
              "reason": f"연 {max_rate * 100:.1f}% 부채 잔액 {state.get('highInterestBalance', 0):,}원 잔존"}
    else:
        g3 = {"id": "G3", "level": 3, "name": "고위험부채", "status": "OPEN",
              "observed": max_rate, "threshold": HIGH_INTEREST_RATE_THRESHOLD, "reason": None}
    gates.append(g3)

    near_goals = state.get("nearTermGoals")
    if near_goals is None:
        g4 = {"id": "G4", "level": 4, "name": "임박목표", "status": "UNKNOWN",
              "observed": None, "threshold": None, "reason": "임박 목표 정보가 없다"}
    else:
        breaching = [g for g in near_goals if g.get("dueMonths") is not None and g["dueMonths"] <= 12
                    and g.get("feasibility") in ("OFF_TRACK", "INFEASIBLE")]
        if breaching:
            names = ", ".join(f"{g.get('id')}({g.get('dueMonths')}개월, {g.get('feasibility')})"
                              for g in breaching)
            g4 = {"id": "G4", "level": 4, "name": "임박목표", "status": "BREACHED",
                  "observed": breaching, "threshold": "12개월 이내 & OFF_TRACK/INFEASIBLE",
                  "reason": f"임박 목표 궤도 이탈: {names}"}
        else:
            g4 = {"id": "G4", "level": 4, "name": "임박목표", "status": "OPEN",
                  "observed": near_goals, "threshold": None, "reason": None}
    gates.append(g4)

    gap_critical = state.get("insuranceGapCritical")
    if gap_critical is None:
        g5 = {"id": "G5", "level": 5, "name": "보장공백", "status": "UNKNOWN",
              "observed": None, "threshold": None, "reason": "보장공백 심각도를 알 수 없다"}
    elif gap_critical:
        g5 = {"id": "G5", "level": 5, "name": "보장공백", "status": "BREACHED",
              "observed": True, "threshold": None, "reason": "CRITICAL 보장공백이 있다"}
    else:
        g5 = {"id": "G5", "level": 5, "name": "보장공백", "status": "OPEN",
              "observed": False, "threshold": None, "reason": None}
    gates.append(g5)

    return gates


def _blocks(gate: dict) -> bool:
    """이 게이트가 (자기 레벨보다 높은 레벨의 제안을) 실제로 차단하는가.

    UNKNOWN은 게이트 1~3에서 BREACHED로 취급한다(모르는 유동성·부채는 그 자체가
    위험이다). 4~5는 UNKNOWN이어도 차단하지 않는다(모르는 투자 상방은 비상사태가
    아니다) — 다만 게이트 자체의 status는 UNKNOWN으로 그대로 보고한다.
    """
    if gate["status"] == "OPEN":
        return False
    if gate["status"] == "BREACHED":
        return True
    return gate["level"] in (1, 2, 3)  # UNKNOWN


def _tie_key(p: dict):
    due = p.get("dueMonths")
    return (due if due is not None else 10 ** 6,
            CERTAINTY_ORDER.get(p.get("certainty"), 9),
            p.get("monthlyAmount", 0),
            p.get("id", ""))


def arbitrate(proposals_in: dict) -> dict:
    state = proposals_in.get("state", {})
    proposals = proposals_in.get("proposals", [])
    override = proposals_in.get("userOverride")
    override_id = override.get("proposalId") if isinstance(override, dict) else None

    gates = evaluate_gates(state)
    gates_by_level = {g["level"]: g for g in gates}

    enriched = []
    for p in proposals:
        level = CATEGORY_LEVEL.get(p.get("category"))
        if level is None:
            enriched.append({**p, "_level": None, "_blockedBy": [],
                             "_error": f"알 수 없는 category: {p.get('category')}"})
            continue
        blocked_by = [g["id"] for lv in range(1, level) for g in [gates_by_level[lv]] if _blocks(g)]
        enriched.append({**p, "_level": level, "_blockedBy": blocked_by})

    enriched.sort(key=lambda p: (p.get("_level") or 999, *_tie_key(p)))

    remaining = state.get("monthlySurplus") or 0
    decisions, by_level = [], {}
    for p in enriched:
        pid, level = p.get("id"), p.get("_level")
        if level is None:
            decisions.append({"proposalId": pid, "verdict": "BLOCKED", "levelRank": None,
                              "fundedMonthly": 0, "blockedBy": [],
                              "unblockCondition": p.get("_error")})
            continue

        is_overridden = pid == override_id
        blocked_by = p["_blockedBy"]

        if blocked_by and not is_overridden:
            reasons = [g["reason"] or f'{g["id"]} 미해소' for g in gates if g["id"] in blocked_by]
            unblock = " ".join(f"{_circle(i)} {r}" for i, r in enumerate(reasons))
            decisions.append({"proposalId": pid, "verdict": "BLOCKED", "levelRank": level,
                              "fundedMonthly": 0, "blockedBy": blocked_by, "unblockCondition": unblock})
            continue

        want = p.get("monthlyAmount", 0)
        funded = max(0, min(want, remaining))
        remaining -= funded
        by_level[LEVEL_NAME[level]] = by_level.get(LEVEL_NAME[level], 0) + funded

        if funded <= 0:
            verdict = "DEFERRED"
        elif is_overridden and blocked_by:
            verdict = "ADMITTED_WITH_OVERRIDE"
        elif funded < want:
            verdict = "PARTIAL"
        else:
            verdict = "ADMITTED"

        entry = {"proposalId": pid, "verdict": verdict, "levelRank": level,
                 "fundedMonthly": funded, "blockedBy": blocked_by if is_overridden else []}
        if is_overridden and blocked_by:
            entry["overrideAcknowledgedRisk"] = override.get("acknowledgedRisk")
            entry["overrideAt"] = override.get("at")
        if verdict == "DEFERRED" and want > 0:
            entry["reason"] = "예산 소진 — 게이트가 아니라 잉여 부족으로 유예"
        decisions.append(entry)

    total_allocated = sum(d.get("fundedMonthly", 0) for d in decisions)
    surplus0 = state.get("monthlySurplus") or 0
    result = {
        "gates": gates,
        "decisions": decisions,
        "allocation": {"surplus": surplus0, "allocated": total_allocated,
                       "unallocated": surplus0 - total_allocated, "byLevel": by_level,
                       "note": "미배분분은 아직 채워지지 않은 가장 낮은 레벨(G1 비상자금 등)에 "
                               "우선 귀속되는 것으로 본다 — 명시적 제안이 없으면 배분하지 않는다."},
        "orderOfOperations": [{"step": i + 1, "proposalId": d["proposalId"]}
                              for i, d in enumerate(decisions) if d.get("fundedMonthly", 0) > 0],
        "policyVersion": POLICY_VERSION,
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_file", required=True)
    ap.add_argument("--policy", default=POLICY_VERSION)
    args = ap.parse_args()

    proposals_in = wc.load_json(args.in_file)
    result = arbitrate(proposals_in)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
