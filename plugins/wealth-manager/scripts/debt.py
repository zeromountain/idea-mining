#!/usr/bin/env python3
"""부채 스케줄·상환순서·대환·조기상환 vs 투자.

원리금균등 공식은 규제 판단이 개입하지 않는 순수 수식이라(§DSR과 달리) 로컬 계산이
:3001과 다를 수 없다 — 그래서 이 파일은 표준 상환 공식을 직접 구현한다. 규정 해석이
필요한 값(DSR 등)만 re_api로 위임한다. 이 구분을 넘지 않는다.

CLI:
  python3 debt.py schedule --context C [--id jeonse-loan] [--extra 500000]
  python3 debt.py order --context C --method both [--extra 500000]
  python3 debt.py refinance --in refi.json
  python3 debt.py prepay-vs-invest --in pvi.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wealth_common as wc

TAX_RATE = 0.154            # 이자·배당소득세 15.4% — 조기상환 허들 계산의 유일한 세금 상수
STOCK_RETURN_STD = 0.15     # 연 기대수익 표준편차 가정. ASSUMPTION으로 명시한다.
Z90 = 1.2816


def equal_payment(principal: float, annual_rate: float, months: int) -> float:
    if months <= 0:
        return 0.0
    r = annual_rate / 12
    if r == 0:
        return principal / months
    return principal * r * (1 + r) ** months / ((1 + r) ** months - 1)


def amortize(principal: float, annual_rate: float, months: int, repayment_type: str = "EQUAL_PAYMENT",
             extra_monthly: float = 0.0) -> dict:
    """단일 대출을 만기까지 시뮬레이션한다. 이자만/원금균등/원리금균등을 지원한다."""
    r = annual_rate / 12
    balance = principal
    total_interest = 0.0
    m = 0
    base_principal = principal / months if months > 0 else 0
    base_payment = equal_payment(principal, annual_rate, months) if repayment_type == "EQUAL_PAYMENT" else None
    while balance > 0.5 and m < 1200:
        m += 1
        interest = balance * r
        if repayment_type == "INTEREST_ONLY" and m < months:
            principal_pay = 0.0
        elif repayment_type == "PRINCIPAL_EQUAL":
            principal_pay = base_principal
        else:
            principal_pay = (base_payment or 0) - interest
        principal_pay += extra_monthly
        principal_pay = max(0.0, min(principal_pay, balance))
        balance -= principal_pay
        total_interest += interest
        if repayment_type == "INTEREST_ONLY" and m >= months and balance > 0.5:
            balance = 0.0  # 만기일시 — 잔여 원금은 별도 처리(문맥상 여기선 완료로 표기)
    return {"months": m, "totalInterest": round(total_interest), "payoffMonth": m}


def cmd_schedule(args) -> int:
    ctx = wc.load_json(args.context)
    liabilities = ctx.get("liabilities") or []
    if args.id:
        liabilities = [l for l in liabilities if l.get("id") == args.id]
    results = []
    for l in liabilities:
        balance, rate, months = l.get("balance"), l.get("annualRate"), l.get("remainingMonths")
        if balance is None or rate is None or months is None:
            results.append({"id": l.get("id"), "schedule": wc.not_computable(
                "balance/annualRate/remainingMonths 중 누락이 있다")})
            continue
        rtype = l.get("repaymentType", "EQUAL_PAYMENT")
        sim = amortize(balance, rate, months, rtype, extra_monthly=args.extra or 0)
        api_ref = wc.re_api_repayment(balance, rate, months, rtype)
        results.append({"id": l.get("id"), "principal": balance, "annualRate": rate,
                        "repaymentType": rtype, "extraMonthly": args.extra or 0,
                        "schedule": wc.computed(sim), "reApiCrossCheck": api_ref})
    wc.emit(wc.envelope("debt.py schedule", {"results": results}, context_hash=ctx.get("contextHash")))
    return 0


def cmd_order(args) -> int:
    ctx = wc.load_json(args.context)
    liabilities = [l for l in (ctx.get("liabilities") or [])
                   if l.get("balance") and l.get("annualRate") is not None and l.get("monthlyPayment")]

    def simulate(strategy: str, extra: float) -> dict:
        remaining = {l["id"]: float(l["balance"]) for l in liabilities}
        rate = {l["id"]: l["annualRate"] for l in liabilities}
        min_pay = {l["id"]: float(l["monthlyPayment"]) for l in liabilities}
        order = sorted(remaining, key=lambda i: (-rate[i] if strategy == "avalanche" else remaining[i]))
        payoff_month, total_interest, month, pool_extra = {}, 0.0, 0, extra
        while any(v > 0.5 for v in remaining.values()) and month < 600:
            month += 1
            pool = pool_extra
            for i in list(remaining):
                if remaining[i] <= 0:
                    continue
                interest = remaining[i] * (rate[i] / 12)
                total_interest += interest
                remaining[i] = max(0.0, remaining[i] + interest - min_pay[i])
            for i in order:
                if remaining[i] <= 0 or pool <= 0:
                    continue
                pay = min(pool, remaining[i])
                remaining[i] -= pay
                pool -= pay
            for i in list(remaining):
                if remaining[i] <= 0 and i not in payoff_month:
                    payoff_month[i] = month
                    pool_extra += min_pay[i]  # 스노우볼: 다 갚은 대출의 최소상환액이 다음 대상으로 넘어간다
        return {"strategy": strategy, "totalMonths": month, "totalInterest": round(total_interest),
                "payoffOrder": [i for i in sorted(payoff_month, key=payoff_month.get)],
                "payoffMonth": payoff_month, "firstPayoffMonth": min(payoff_month.values(), default=None)}

    if not liabilities:
        wc.emit(wc.envelope("debt.py order", {"note": "상환 스케줄을 계산할 부채가 없다"}))
        return 0

    extra = args.extra or 0
    avalanche = simulate("avalanche", extra)
    snowball = simulate("snowball", extra)
    warnings = []
    io_ids = [l["id"] for l in liabilities if l.get("repaymentType") == "INTEREST_ONLY"]
    if io_ids:
        warnings.append(
            f"{', '.join(io_ids)}는 만기일시(이자만) 상환이다 — 이 시뮬레이션은 여윳돈을 이 대출의 "
            f"원금에 바로 적용한다고 가정하지만, 실제 만기일시 대출은 중도상환이 은행 동의나 수수료가 "
            f"필요할 수 있고 전세대출이면 만기(remainingMonths)에 보증금으로 상환하는 것이 일반적이다. "
            f"이 결과를 그 대출에 적용하기 전에 실제 중도상환 가능 여부를 확인한다.")
    data = {"avalanche": avalanche, "snowball": snowball,
            "interestDifference": round(snowball["totalInterest"] - avalanche["totalInterest"]),
            "note": "avalanche는 총이자 최소화, snowball은 첫 완제(행동 동기) 최소화 — 어느 쪽을 "
                    "쓸지는 debt-manager의 판단이다. 이 스크립트는 둘 다 낼 뿐 고르지 않는다."}
    wc.emit(wc.envelope("debt.py order", data, warnings=warnings, context_hash=ctx.get("contextHash")))
    return 0


def cmd_refinance(args) -> int:
    inp = wc.load_json(args.in_file)
    old = inp["current"]
    new = inp["proposed"]
    months = old["remainingMonths"]
    old_payment = equal_payment(old["balance"], old["annualRate"], months)
    new_payment = equal_payment(new["balance"], new["annualRate"], new.get("termMonths", months))
    monthly_saving = old_payment - new_payment

    switching_costs = 0
    penalty = old.get("prepaymentPenalty")
    if penalty:
        if old.get("monthsSinceOrigination") is not None and \
                old["monthsSinceOrigination"] < penalty.get("untilMonth", 0):
            switching_costs += old["balance"] * penalty.get("rate", 0)
    switching_costs += inp.get("otherSwitchingCosts", 0)

    if monthly_saving <= 0:
        data = {"breakEvenMonth": None, "netSavings": None, "monthlySaving": round(monthly_saving),
                "switchingCosts": switching_costs, "assumesHeldToMaturity": True,
                "verdict": "월 상환액이 줄지 않는다 — 대환 실익 없음"}
    else:
        break_even = switching_costs / monthly_saving if monthly_saving > 0 else None
        horizon = min(months, new.get("termMonths", months))
        net_savings = round(monthly_saving * horizon - switching_costs)
        data = {"breakEvenMonth": round(break_even, 1) if break_even is not None else None,
                "netSavings": net_savings, "monthlySaving": round(monthly_saving),
                "switchingCosts": switching_costs, "assumesHeldToMaturity": True,
                "verdict": None}
    wc.emit(wc.envelope("debt.py refinance", data))
    return 0


def cmd_prepay_vs_invest(args) -> int:
    inp = wc.load_json(args.in_file)
    loan = inp["loan"]
    extra_amount = inp["extraAmount"]
    balance, rate, months = loan["balance"], loan["annualRate"], loan["remainingMonths"]
    rtype = loan.get("repaymentType", "EQUAL_PAYMENT")
    assumed_return = inp.get("assumedAnnualReturn", 0.07)
    liquid_before = inp.get("liquidAssetsBefore")
    essential = inp.get("essentialMonthlyOutflow")

    base = amortize(balance, rate, months, rtype)
    with_prepay = amortize(max(balance - extra_amount, 0), rate, months, rtype)
    interest_saved = base["totalInterest"] - with_prepay["totalInterest"]

    def fv(annual_return: float) -> float:
        return extra_amount * ((1 + annual_return / 12) ** months) - extra_amount

    p10 = fv(assumed_return - Z90 * STOCK_RETURN_STD)
    p50 = fv(assumed_return)
    p90 = fv(assumed_return + Z90 * STOCK_RETURN_STD)

    required_pretax = rate / (1 - TAX_RATE)
    dominance = "PREPAY_DOMINATES" if (rate >= 0.07 or required_pretax >= (assumed_return + Z90 * STOCK_RETURN_STD)) \
        else "AMBIGUOUS"

    data = {
        "certain": {"kind": "CERTAIN", "interestSaved": round(interest_saved),
                    "basis": f"계약금리 {rate * 100:.2f}% × 잔여 {months}개월 스케줄",
                    "confidence": "VERIFIED"},
        "uncertain": {"kind": "EXPECTED", "assumedAnnualReturn": assumed_return,
                     "expectedValue": round(p50), "requiresAssumption": True,
                     "distribution": {"p10": round(p10), "p50": round(p50), "p90": round(p90)},
                     "distributionBasis": f"연 표준편차 {STOCK_RETURN_STD * 100:.0f}% 가정 (ASSUMPTION)",
                     "confidence": "ESTIMATED"},
        "hurdle": {"loanRate": rate, "taxRate": TAX_RATE, "requiredPretaxReturn": round(required_pretax, 4),
                  "statement": f"투자가 이기려면 세전 연 {required_pretax * 100:.2f}%를 확정적으로 넘어야 한다"},
        "liquidity": {
            "emergencyFundMonthsBefore": round(liquid_before / essential, 2) if liquid_before and essential else None,
            "emergencyFundMonthsAfter": round((liquid_before - extra_amount) / essential, 2)
                if liquid_before and essential else None,
        },
        "dominance": dominance,
        "decisionRule": "loanRate ≥ 0.07 이거나 requiredPretaxReturn ≥ p90 → PREPAY_DOMINATES, 그 외 AMBIGUOUS",
    }
    wc.emit(wc.envelope("debt.py prepay-vs-invest", data,
                        assumptions=[{"key": data["uncertain"]["distributionBasis"], "confidence": "ESTIMATED"}]))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("schedule")
    p1.add_argument("--context", required=True)
    p1.add_argument("--id")
    p1.add_argument("--extra", type=float)
    p1.set_defaults(func=cmd_schedule)

    p2 = sub.add_parser("order")
    p2.add_argument("--context", required=True)
    p2.add_argument("--method", choices=["avalanche", "snowball", "both"], default="both")
    p2.add_argument("--extra", type=float, default=0)
    p2.set_defaults(func=cmd_order)

    p3 = sub.add_parser("refinance")
    p3.add_argument("--in", dest="in_file", required=True)
    p3.set_defaults(func=cmd_refinance)

    p4 = sub.add_parser("prepay-vs-invest")
    p4.add_argument("--in", dest="in_file", required=True)
    p4.set_defaults(func=cmd_prepay_vs_invest)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
