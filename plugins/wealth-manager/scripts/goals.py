#!/usr/bin/env python3
"""목표 실현가능성 + 목표 충돌(월 그리드 기반).

두 목표는 "전체 필요액 합 vs 잉여"가 아니라 **자금 조달 창이 시간상 겹치는 구간에서만**
충돌한다. 순차 목표(2027-06 전세, 2029-01 차)를 거짓 충돌로 잡지 않기 위해서다.
이 월 그리드가 scenario.py의 기반이기도 하다.

CLI:
  python3 goals.py --context ~/wealth/financial-context.resolved.json \
                    --cashflow /tmp/cashflow.json [--horizon-months 120]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wealth_common as wc


def month_diff(from_ym: str, to_ym: str) -> int:
    """to_ym이 from_ym보다 몇 개월 뒤인지. 음수면 이미 지난 기한."""
    fy, fm = int(from_ym[:4]), int(from_ym[5:7])
    ty, tm = int(to_ym[:4]), int(to_ym[5:7])
    return (ty - fy) * 12 + (tm - fm)


def add_months(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    total = (y * 12 + (m - 1)) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def classify_feasibility(required, allocated, months_remaining) -> str:
    if months_remaining is None or required is None:
        return "NOT_COMPUTABLE"
    if months_remaining <= 0:
        return "INFEASIBLE" if required > 0 else "ON_TRACK"
    if allocated is None:
        return "NOT_COMPUTABLE"
    if required <= 0:
        return "ON_TRACK"
    ratio = allocated / required
    if ratio >= 0.95:
        return "ON_TRACK"
    if ratio >= 0.7:
        return "TIGHT"
    if ratio > 0:
        return "OFF_TRACK"
    return "INFEASIBLE"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", required=True)
    ap.add_argument("--cashflow", required=True)
    ap.add_argument("--horizon-months", type=int)
    args = ap.parse_args()

    ctx = wc.load_json(args.context)
    cashflow = wc.load_json(args.cashflow)
    now_ym = date.today().strftime("%Y-%m")

    available = None
    cm = cashflow.get("data", {}).get("metrics", {})
    for key in ("investableAmount", "surplus"):
        v = cm.get(key)
        if isinstance(v, dict) and v.get("computable"):
            available = v["value"]
            break
    surplus_source = "investableAmount" if cm.get("investableAmount", {}).get("computable") else "surplus"

    raw_goals = ctx.get("goals") or []
    out_goals = []
    for g in raw_goals:
        gid = g.get("id")
        deadline = g.get("deadline")
        target = g.get("targetAmount") or 0
        current = g.get("currentAmount") or 0
        allocated = g.get("monthlyContribution")
        months_remaining = month_diff(now_ym, deadline) if deadline else None

        remaining_amount = max(target - current, 0)
        if months_remaining is not None and months_remaining > 0:
            required_monthly = wc.computed(math.ceil(remaining_amount / months_remaining))
        elif months_remaining is not None and months_remaining <= 0:
            required_monthly = wc.computed(remaining_amount) if remaining_amount > 0 else wc.computed(0)
        else:
            required_monthly = wc.not_computable(f"goal '{gid}'에 deadline이 없다")

        req_v = required_monthly["value"] if required_monthly.get("computable") else None
        feasibility = classify_feasibility(req_v, allocated, months_remaining)

        if allocated and allocated > 0 and req_v is not None:
            months_to_complete = math.ceil(remaining_amount / allocated) if allocated > 0 else None
            projected_completion = add_months(now_ym, months_to_complete) if months_to_complete is not None else None
            shortfall_at_deadline = (max(0, (months_remaining or 0)) * allocated + current) - target \
                if months_remaining is not None else None
            shortfall_at_deadline = -shortfall_at_deadline if shortfall_at_deadline is not None and shortfall_at_deadline < 0 else 0
        else:
            projected_completion = None
            shortfall_at_deadline = remaining_amount if req_v is not None else None

        out_goals.append({
            "id": gid, "label": g.get("label"), "targetAmount": target, "deadline": deadline,
            "currentAmount": current, "monthsRemaining": months_remaining,
            "requiredMonthly": required_monthly, "allocatedMonthly": allocated,
            "gapMonthly": (req_v - allocated) if (req_v is not None and allocated is not None) else None,
            "projectedCompletion": projected_completion,
            "shortfallAtDeadline": shortfall_at_deadline,
            "feasibility": feasibility,
            "priorityClass": g.get("priorityClass"),
            "liquidityRequired": g.get("liquidityRequired", False),
            "_monthsRemaining": months_remaining, "_requiredMonthly": req_v,
        })

    # ---- 월 그리드 기반 충돌 탐지 ----
    horizon = args.horizon_months or max((g["_monthsRemaining"] or 0 for g in out_goals), default=1) or 1
    horizon = max(horizon, 1)
    month_grid = []
    for m in range(1, horizon + 1):
        active = [g for g in out_goals if g["_monthsRemaining"] is not None
                  and g["_requiredMonthly"] is not None and g["_monthsRemaining"] >= m]
        required_sum = sum(g["_requiredMonthly"] for g in active)
        avail = available if available is not None else 0
        deficit = max(0, required_sum - avail)
        month_grid.append({"m": m, "ym": add_months(now_ym, m), "activeGoalIds": [g["id"] for g in active],
                           "required": required_sum, "available": avail, "deficit": deficit})

    overcommitted = [row for row in month_grid if row["deficit"] > 0]
    peak = max(overcommitted, key=lambda r: r["deficit"], default=None)

    # 연속된 동일 활성집합을 하나의 competingSet으로 묶는다
    competing_sets = []
    prev_key = None
    for row in overcommitted:
        key = tuple(sorted(row["activeGoalIds"]))
        if key == prev_key and competing_sets:
            competing_sets[-1]["overlapMonths"] += 1
            competing_sets[-1]["contestedMonthly"] = max(competing_sets[-1]["contestedMonthly"], row["required"])
        else:
            competing_sets.append({"goalIds": list(key), "overlapMonths": 1,
                                   "contestedMonthly": row["required"], "availableMonthly": row["available"]})
        prev_key = key

    goal_by_id = {g["id"]: g for g in out_goals}
    for cs in competing_sets:
        total_req = sum(goal_by_id[gid]["_requiredMonthly"] or 0 for gid in cs["goalIds"])
        options = []
        for gid in cs["goalIds"]:
            g = goal_by_id[gid]
            fair_share = cs["availableMonthly"] * ((g["_requiredMonthly"] or 0) / total_req) if total_req else 0
            months_rem = g["_monthsRemaining"] or 1
            new_months = math.ceil((g["targetAmount"] - g["currentAmount"]) / fair_share) if fair_share > 0 else None
            delay_months = max(0, (new_months - months_rem)) if new_months is not None else None
            reduce_amount = max(0, round((g["_requiredMonthly"] or 0) - fair_share) * months_rem)
            options.append({"type": "DELAY", "goalId": gid, "byMonths": delay_months,
                            "feasible": delay_months is not None})
            options.append({"type": "REDUCE_TARGET", "goalId": gid, "byAmount": reduce_amount,
                            "feasible": reduce_amount < g["targetAmount"]})
        options.append({"type": "REPRIORITIZE",
                        "order": sorted(cs["goalIds"],
                                        key=lambda gid: (goal_by_id[gid]["priorityClass"] or "ZZZ",
                                                         goal_by_id[gid]["_monthsRemaining"] or 999))})
        cs["resolutionOptions"] = options

    for g in out_goals:
        g.pop("_monthsRemaining", None)
        g.pop("_requiredMonthly", None)

    data = {
        "goals": out_goals,
        "contention": {
            "surplusAvailable": available, "surplusSource": surplus_source,
            "monthGrid": month_grid, "overcommittedMonths": [r["m"] for r in overcommitted],
            "peakDeficit": peak["deficit"] if peak else 0,
            "peakDeficitMonth": peak["ym"] if peak else None,
            "competingSets": competing_sets,
        },
    }

    assumptions = []
    if competing_sets:
        assumptions.append({"key": "resolutionOptions의 DELAY/REDUCE_TARGET은 잉여를 요구액 비례로 "
                            "나눴을 때의 근사치다 — 실제 선택은 우선순위에 따라 달라진다",
                            "confidence": "ESTIMATED"})

    payload = wc.envelope("goals.py", data, assumptions=assumptions,
                          input_confidence=wc.block_confidence(ctx, ctx.get("effectiveConfidence") or {}, "goals"),
                          context_hash=ctx.get("contextHash"))
    wc.emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
