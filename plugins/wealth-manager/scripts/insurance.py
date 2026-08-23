#!/usr/bin/env python3
"""보험료 부담·중복특약·보장공백.

중복은 indemnityType으로 가른다 — FIXED_BENEFIT(정액형, 중복지급)은 정당한 중첩이고
PROPORTIONAL(실손형, 비례보상)의 중복은 거의 순수 낭비다. 둘을 같은 무게로 플래그하면
사용자가 잘못된 보험을 해지하게 만든다.

보장공백은 insurance.assumptions가 없으면 계산하지 않는다 — 기본값 3억 같은 걸
만들지 않는다.

CLI:
  python3 insurance.py --context ~/wealth/financial-context.resolved.json
"""
from __future__ import annotations

import argparse
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wealth_common as wc

GUIDELINE_BAND = [0.08, 0.10]
DEATH_LIKE_CLASSES = {"DEATH"}
CI_CLASSES = {"CANCER_DIAGNOSIS", "CANCER", "CI", "CRITICAL_ILLNESS"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", required=True)
    ap.add_argument("--cashflow")
    args = ap.parse_args()

    ctx = wc.load_json(args.context)
    totals = (ctx.get("_derived") or {}).get("totals") or {}
    ins = ctx.get("insurance") or {}
    policies = ins.get("policies") or []
    assumptions_block = ins.get("assumptions") or {}

    premium_total = totals.get("insurance", {}).get("monthlyPremiumTotal",
                    sum(p.get("monthlyPremium", 0) for p in policies))
    monthly_net = totals.get("income", {}).get("monthlyNetTotal")
    annual_gross_monthly = None
    if args.cashflow:
        cf = wc.load_json(args.cashflow)
        ag = cf.get("data", {}).get("income", {}).get("annualGross")
        annual_gross_monthly = round(ag / 12) if ag else None

    premium_burden = {
        "monthlyPremiumTotal": premium_total,
        "vsMonthlyNet": round(premium_total / monthly_net, 4) if monthly_net else None,
        "vsAnnualGrossMonthly": round(premium_total / annual_gross_monthly, 4) if annual_gross_monthly else None,
        "guidelineBand": GUIDELINE_BAND, "guidelineBasis": "ASSUMPTION — 통념, 법규 아님",
    }

    # ---- 중복 탐지 ----
    riders_by_class: dict[str, list] = {}
    for p in policies:
        for r in p.get("riders") or []:
            riders_by_class.setdefault(r.get("class", "UNKNOWN"), []).append(
                {"policyId": p.get("id"), "policyLabel": p.get("label"),
                 "indemnityType": r.get("indemnityType", "UNKNOWN"), "benefitAmount": r.get("benefitAmount"),
                 "name": r.get("name")})

    duplicates = []
    for cls, riders in riders_by_class.items():
        if len(riders) < 2:
            continue
        policy_ids = {r["policyId"] for r in riders}
        if len(policy_ids) < 2:
            continue  # 같은 보험 안의 특약은 중복이 아니다
        indemnity_types = {r["indemnityType"] for r in riders}
        is_proportional = "PROPORTIONAL" in indemnity_types
        duplicates.append({
            "class": cls, "policyIds": sorted(policy_ids),
            "indemnityType": "PROPORTIONAL" if is_proportional else
                            ("FIXED_BENEFIT" if indemnity_types == {"FIXED_BENEFIT"} else "MIXED"),
            "combinedMonthlyPremium": None,
            "wasteLikelihood": "HIGH" if is_proportional else "LOW",
        })

    # ---- 보장공백 (assumptions 필수) ----
    coverage_gaps, unknown_impact = [], []
    required_fields = ["survivorMonthlyNeed", "survivorNeedMonths"]
    missing = [f for f in required_fields if assumptions_block.get(f) is None]
    if missing:
        coverage_gaps.append({"need": "사망보장", "computable": False,
                             "reason": f"insurance.assumptions에 {', '.join(missing)}가 없다"})
        unknown_impact.append({"path": "insurance.assumptions", "affects": ["coverageGaps"]})
    else:
        existing_death = sum(r.get("benefitAmount") or 0 for r in riders_by_class.get("DEATH", []))
        remaining_debt = totals.get("liabilities", {}).get("totalBalance", 0)
        liquid_assets = totals.get("assets", {}).get("liquidAssets", 0)
        need = assumptions_block["survivorMonthlyNeed"] * assumptions_block["survivorNeedMonths"] \
            + remaining_debt - liquid_assets - existing_death
        coverage_gaps.append({"need": "사망보장", "computable": True,
                             "required": assumptions_block["survivorMonthlyNeed"] * assumptions_block["survivorNeedMonths"]
                                        + remaining_debt - liquid_assets,
                             "existing": existing_death, "gap": max(0, round(need)),
                             "severity": "CRITICAL" if need > 0 and existing_death == 0 else
                                        ("MODERATE" if need > 0 else "NONE"),
                             "computedFrom": ["insurance.assumptions.survivorMonthlyNeed",
                                              "insurance.assumptions.survivorNeedMonths",
                                              "liabilities", "assets.liquidAssets", "insurance.policies"]})

    if assumptions_block.get("criticalIllnessTreatmentCost") is not None:
        existing_ci = sum(r.get("benefitAmount") or 0 for r in riders_by_class.get("CANCER_DIAGNOSIS", []))
        gap = max(0, assumptions_block["criticalIllnessTreatmentCost"] - existing_ci)
        coverage_gaps.append({"need": "중대질병 치료비", "computable": True,
                             "required": assumptions_block["criticalIllnessTreatmentCost"],
                             "existing": existing_ci, "gap": gap,
                             "severity": "CRITICAL" if gap > assumptions_block["criticalIllnessTreatmentCost"] * 0.5
                                        else ("MODERATE" if gap > 0 else "NONE"),
                             "computedFrom": ["insurance.assumptions.criticalIllnessTreatmentCost"]})
    else:
        coverage_gaps.append({"need": "중대질병 치료비", "computable": False,
                             "reason": "insurance.assumptions.criticalIllnessTreatmentCost가 없다"})
        unknown_impact.append({"path": "insurance.assumptions.criticalIllnessTreatmentCost",
                              "affects": ["coverageGaps"]})

    over_insured = [{"class": cls, "existing": sum(r.get("benefitAmount") or 0 for r in riders),
                    "note": "정액형 다수 보유 — 필요 이상인지 확인 필요"}
                   for cls, riders in riders_by_class.items()
                   if len(riders) >= 3 and all(r["indemnityType"] == "FIXED_BENEFIT" for r in riders)]

    recommendations = []
    for d in duplicates:
        rtype = "REDUCE_RIDER" if d["wasteLikelihood"] == "HIGH" else "REVIEW"
        recommendations.append({"type": rtype, "target": d["class"], "policyIds": d["policyIds"],
                               "note": f"{d['class']} 특약이 {len(d['policyIds'])}개 보험에 중복 — "
                                       f"{'실손형이라 비례보상되므로 낭비 가능성 높음' if d['wasteLikelihood']=='HIGH' else '정액형이라 정당한 중첩일 수 있음'}"})
    for g in coverage_gaps:
        if g.get("computable") and g.get("gap", 0) > 0:
            recommendations.append({"type": "ADD_COVERAGE", "target": g["need"], "amount": g["gap"],
                                   "note": f"{g['need']} 공백 {g['gap']:,}원 — 특약 조정 전 CONSULT_PROFESSIONAL 권장"})
    if any(d["wasteLikelihood"] == "HIGH" for d in duplicates) or any(g.get("severity") == "CRITICAL"
           for g in coverage_gaps if g.get("computable")):
        recommendations.append({"type": "CONSULT_PROFESSIONAL", "target": "전체 보험 포트폴리오",
                               "note": "해지·감액은 해지환급금·납입기간·재가입 가능성을 확인한 뒤 전문가와 결정한다"})
    if not recommendations:
        recommendations.append({"type": "REVIEW", "target": "전체 보험 포트폴리오",
                               "note": "현재 데이터로는 중복·공백이 뚜렷하지 않다"})

    data = {"premiumBurden": premium_burden, "duplicates": duplicates, "coverageGaps": coverage_gaps,
            "overInsured": over_insured, "recommendations": recommendations}
    payload = wc.envelope("insurance.py", data, context_hash=ctx.get("contextHash"))
    payload["unknownImpact"] = unknown_impact
    wc.emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
