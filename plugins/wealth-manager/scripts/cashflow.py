#!/usr/bin/env python3
"""현금흐름 지표 — 잉여현금, 부담률 두 가지(가계 기준·규제 DSR), 비상자금 개월수.

--context는 financial-context.resolved.json을 가리킨다 (wealth_context.py resolve로 생성).
정본(financial-context.json)이 아니라 파생 파일을 읽는 이유는 _derived.totals와
effectiveConfidence가 여기 있기 때문이다 — 합계를 이 스크립트가 다시 계산하지 않는다.

householdDebtBurden(월순소득 분모)과 regulatoryDsr(연소득 분모, :3001 위임)은
분모가 다른 다른 수다 — 하나를 다른 것으로 인용하면 factcheck 경로가 달라 걸린다.

CLI:
  python3 cashflow.py --context ~/wealth/financial-context.resolved.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wealth_common as wc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", required=True)
    ap.add_argument("--spending", help="transactions/<YYYY-MM>.normalized.json (선택)")
    ap.add_argument("--months", type=int, default=3)
    args = ap.parse_args()

    ctx = wc.load_json(args.context)
    totals = (ctx.get("_derived") or {}).get("totals") or {}
    eff = ctx.get("effectiveConfidence") or {}

    income_t = totals.get("income", {})
    assets_t = totals.get("assets", {})
    liab_t = totals.get("liabilities", {})
    exp_t = totals.get("monthlyExpenses", {})

    monthly_net = income_t.get("monthlyNetTotal", 0)
    liquid_assets = assets_t.get("liquidAssets", 0)
    fixed_total = exp_t.get("fixedTotal", 0)
    variable_total = exp_t.get("variableTotal", 0)
    savings_auto_total = exp_t.get("savingsAutoTotal", 0)
    lumpy_equiv = exp_t.get("annualLumpyMonthlyEquivalent", 0)
    debt_service = liab_t.get("monthlyDebtService", 0)

    income_conf = wc.block_confidence(ctx, eff, "income.primary.monthlyNet")
    expense_conf = wc.min_conf(wc.block_confidence(ctx, eff, "monthlyExpenses.fixed"),
                                wc.block_confidence(ctx, eff, "monthlyExpenses.variable"))
    liab_conf = wc.block_confidence(ctx, eff, "liabilities")
    asset_conf = wc.block_confidence(ctx, eff, "assets")

    assumptions, warnings = [], []

    outflow_total = fixed_total + variable_total + debt_service + savings_auto_total + lumpy_equiv
    if monthly_net == 0 and income_conf == "UNKNOWN":
        surplus = wc.not_computable("income.primary.monthlyNet가 UNKNOWN이다 — 잉여현금을 계산할 수 없다")
    else:
        surplus = wc.computed(monthly_net - outflow_total)

    essential = fixed_total + debt_service
    if essential <= 0:
        emergency_months = wc.not_computable("고정비+상환이 0이다 — 필수지출 기준 개월수를 계산할 수 없다")
    else:
        emergency_months = wc.computed(round(liquid_assets / essential, 2))

    total_burn = fixed_total + variable_total + debt_service
    if total_burn <= 0:
        runway = wc.not_computable("월 지출 합계가 0이다")
    else:
        runway = wc.computed(round(liquid_assets / total_burn, 2))

    if monthly_net <= 0:
        fixed_cost_ratio = wc.not_computable("monthlyNetTotal이 0 이하다")
        household_debt_burden = wc.not_computable("monthlyNetTotal이 0 이하다")
        savings_rate = wc.not_computable("monthlyNetTotal이 0 이하다")
        investable = wc.not_computable("monthlyNetTotal이 0 이하다")
    else:
        fixed_cost_ratio = wc.computed(round((fixed_total + debt_service) / monthly_net, 4))
        household_debt_burden = wc.computed(round(debt_service / monthly_net, 4))
        savings_rate = wc.computed(round((savings_auto_total + max(monthly_net - outflow_total, 0))
                                         / monthly_net, 4))
        emergency_target = 6  # 개월. 문서 §7 Rule 5 / arbitrate.py G1과 동일 기준.
        emergency_top_up = 0
        if emergency_months.get("computable") and emergency_months["value"] < emergency_target:
            gap_months = emergency_target - emergency_months["value"]
            emergency_top_up = round(gap_months * essential / 6)  # 6개월에 걸쳐 채우는 것으로 가정
            assumptions.append({"key": "비상자금 보충 속도: 부족분을 6개월에 나눠 채운다고 가정",
                                "confidence": "ESTIMATED"})
        surplus_v = surplus["value"] if surplus.get("computable") else 0
        investable = wc.computed(max(surplus_v - emergency_top_up, 0)) if surplus.get("computable") \
            else wc.not_computable("surplus가 NOT_COMPUTABLE이라 investableAmount도 계산할 수 없다")

    # 규제 DSR — :3001에 위임. 실패해도 로컬로 재구현하지 않는다.
    liabilities = ctx.get("liabilities") or []
    annual_gross = (ctx.get("income") or {}).get("primary", {}).get("annualGross")
    debts = [{"balance": l.get("balance"), "annualRatePercent": l.get("annualRate", 0) * 100,
              "monthlyPayment": l.get("monthlyPayment"), "remainingMonths": l.get("remainingMonths"),
              "isMortgage": l.get("isMortgage", False)} for l in liabilities]
    regulatory_dsr = wc.re_api_dsr(annual_gross, debts) if liabilities else \
        wc.computed({"ratioPercent": 0.0, "lines": [], "note": "부채 없음"})

    if income_conf == "UNKNOWN":
        warnings.append("소득 confidence가 UNKNOWN이라 surplus·savingsRate 신뢰도가 낮다")
    if liab_conf == "UNKNOWN":
        warnings.append("부채 confidence가 UNKNOWN이라 householdDebtBurden·DSR 신뢰도가 낮다")

    unknown_impact = []
    if income_conf == "UNKNOWN":
        unknown_impact.append({"path": "income.primary.monthlyNet",
                               "affects": ["surplus", "fixedCostRatio", "savingsRate", "investableAmount"]})
    if liab_conf == "UNKNOWN":
        unknown_impact.append({"path": "liabilities", "affects": ["householdDebtBurden", "regulatoryDsr"]})

    data = {
        "income": {"monthlyNetTotal": monthly_net, "annualGross": annual_gross,
                   "irregularMonthlyEquivalent": income_t.get("irregularMonthlyEquivalent", 0)},
        "outflow": {"fixedTotal": fixed_total, "variableTotal": variable_total,
                    "debtServiceTotal": debt_service, "savingsAutoTotal": savings_auto_total,
                    "lumpyMonthlyEquivalent": lumpy_equiv, "total": outflow_total},
        "metrics": {
            "surplus": surplus,
            "fixedCostRatio": fixed_cost_ratio,
            "savingsRate": savings_rate,
            "investableAmount": investable,
            "householdDebtBurden": household_debt_burden,
            "regulatoryDsr": regulatory_dsr,
            "emergencyFundMonths": emergency_months,
            "runwayMonthsIfIncomeStops": runway,
        },
    }

    payload = wc.envelope(
        "cashflow.py", data, assumptions=assumptions, warnings=warnings,
        input_confidence=wc.min_conf(income_conf, expense_conf, liab_conf, asset_conf),
        input_confidence_by_field={"income": income_conf, "expenses": expense_conf,
                                   "liabilities": liab_conf, "assets": asset_conf},
        context_hash=ctx.get("contextHash"))
    payload["unknownImpact"] = unknown_impact
    wc.emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
