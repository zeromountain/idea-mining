#!/usr/bin/env python3
"""시나리오 시뮬레이터 — 하나의 엔진, 닫힌 이벤트 어휘 11종.

문서 §31의 13가지 시나리오(차량구매·주택구매·이직·조기상환···)는 전부 "날짜 붙은
델타를 대차대조표·현금흐름에 적용하고 같은 지표로 다시 돌리는 것"이라는 같은 일이다.
케이스별 스크립트를 만들지 않는다 — 이벤트 조합으로 표현한다.

가격을 예측하지 않는다. 자산은 명시적 valuation.annualChangeRate가 없으면 취득가를
유지하고, 주면 assumptions[]에 강제 기록되며 confidence가 ESTIMATED로 상한된다.

이벤트 타입: INCOME_CHANGE · EXPENSE_RECURRING_ADD · EXPENSE_RECURRING_REMOVE ·
EXPENSE_ONEOFF · ASSET_ACQUIRE · ASSET_DISPOSE · ASSET_MARKDOWN · NEW_LOAN ·
LOAN_PREPAY · LOAN_REFINANCE · TRANSFER

CLI:
  python3 scenario.py --context C.resolved.json --scenario scenarios/car-2027.json
                       [--horizon-months 60] [--compare baseline]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wealth_common as wc

EMERGENCY_FUND_TARGET_MONTHS = 3
DSR_STRESS_THRESHOLD = 0.40


def _monthly_payment(loan: dict) -> float:
    r = loan["rate"] / 12
    n = loan.get("termMonths") or loan.get("remainingMonths") or 1
    if loan.get("repaymentType") == "INTEREST_ONLY":
        return loan["balance"] * r
    if r == 0:
        return loan["balance"] / n
    return loan["balance"] * r * (1 + r) ** n / ((1 + r) ** n - 1)


def add_months(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    total = (y * 12 + (m - 1)) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def build_baseline_state(ctx: dict) -> dict:
    totals = (ctx.get("_derived") or {}).get("totals") or {}
    income_t, exp_t, liab_t, assets_t = (totals.get(k, {}) for k in
                                          ("income", "monthlyExpenses", "liabilities", "assets"))
    loans = []
    for l in ctx.get("liabilities") or []:
        loans.append({"id": l["id"], "balance": l["balance"], "rate": l.get("annualRate", 0),
                     "repaymentType": l.get("repaymentType", "EQUAL_PAYMENT"),
                     "remainingMonths": l.get("remainingMonths"),
                     "payment": l.get("monthlyPayment") or 0})
    return {
        "cash": assets_t.get("liquidAssets", 0),
        "otherAssets": assets_t.get("totalAssets", 0) - assets_t.get("liquidAssets", 0),
        "income": income_t.get("monthlyNetTotal", 0),
        "fixed": exp_t.get("fixedTotal", 0),
        "variable": exp_t.get("variableTotal", 0),
        "loans": loans,
    }


def simulate(start_state: dict, events: list[dict], horizon: int) -> dict:
    st = json.loads(json.dumps(start_state))
    events_by_month = {}
    for e in events:
        events_by_month.setdefault(e["at"], []).append(e)

    now_ym = wc.today()[:7]
    months, assumptions = [], []
    min_cash, min_cash_month = st["cash"], None
    first_negative_surplus, emergency_breach, insolvency = None, None, None
    dsr_peak, dsr_peak_month = 0.0, None
    cumulative_surplus, total_interest = 0, 0
    one_off_this_month = 0

    for m in range(1, horizon + 1):
        ym = add_months(now_ym, m)
        one_off_this_month = 0
        for ev in events_by_month.get(ym, []):
            t = ev["type"]
            if t == "INCOME_CHANGE":
                st["income"] = ev.get("newMonthlyIncome", st["income"] + ev.get("delta", 0))
            elif t == "EXPENSE_RECURRING_ADD":
                st["fixed"] += ev.get("monthlyAmount", 0)
            elif t == "EXPENSE_RECURRING_REMOVE":
                st["fixed"] = max(0, st["fixed"] - ev.get("monthlyAmount", 0))
            elif t == "EXPENSE_ONEOFF":
                one_off_this_month += ev.get("amount", 0)
            elif t == "ASSET_ACQUIRE":
                one_off_this_month += sum(f.get("amount", 0) for f in ev.get("fundedBy", [])
                                          if f.get("source") != "NEW_LOAN")
                loan_funding = [f for f in ev.get("fundedBy", []) if f.get("source") == "NEW_LOAN"]
                for lf in loan_funding:
                    loan = {"id": lf["id"], "balance": lf["amount"], "rate": lf["rate"],
                            "repaymentType": lf.get("repaymentType", "EQUAL_PAYMENT"),
                            "termMonths": lf.get("termMonths"), "remainingMonths": lf.get("termMonths")}
                    loan["payment"] = _monthly_payment(loan)
                    st["loans"].append(loan)
                acquired_value = ev.get("amount", 0)
                st["otherAssets"] += acquired_value
                if ev.get("valuation", {}).get("annualChangeRate") is not None:
                    assumptions.append({"key": f"{ev.get('label', ev.get('type'))} 가치 변동률 "
                                        f"{ev['valuation']['annualChangeRate']*100:.1f}%/년 가정",
                                        "confidence": "ESTIMATED"})
            elif t == "ASSET_DISPOSE":
                one_off_this_month -= ev.get("amount", 0)  # 현금 유입이므로 음수(지출 차감)
                st["otherAssets"] -= ev.get("amount", 0)
            elif t == "ASSET_MARKDOWN":
                markdown = st["otherAssets"] * ev.get("rate", 0)
                st["otherAssets"] -= markdown
                assumptions.append({"key": f"자산 마크다운 {ev.get('rate', 0)*100:.0f}% (스트레스 테스트)",
                                    "confidence": "ESTIMATED"})
            elif t == "NEW_LOAN":
                loan = {"id": ev["id"], "balance": ev["amount"], "rate": ev["rate"],
                        "repaymentType": ev.get("repaymentType", "EQUAL_PAYMENT"),
                        "termMonths": ev.get("termMonths"), "remainingMonths": ev.get("termMonths")}
                loan["payment"] = _monthly_payment(loan)
                st["loans"].append(loan)
                one_off_this_month -= ev["amount"]  # 대출금 유입 (지출 차감)
            elif t == "LOAN_PREPAY":
                for loan in st["loans"]:
                    if loan["id"] == ev["loanId"]:
                        amt = loan["balance"] if ev.get("amount") == "PAYOFF" else ev.get("amount", 0)
                        one_off_this_month += min(amt, loan["balance"])
                        loan["balance"] = max(0, loan["balance"] - amt)
            elif t == "LOAN_REFINANCE":
                for i, loan in enumerate(st["loans"]):
                    if loan["id"] == ev["loanId"]:
                        one_off_this_month += ev.get("switchingCosts", 0)
                        new_loan = {"id": ev.get("newId", loan["id"]), "balance": loan["balance"],
                                   "rate": ev["newRate"], "repaymentType": ev.get("repaymentType",
                                   loan.get("repaymentType", "EQUAL_PAYMENT")),
                                   "termMonths": ev.get("newTermMonths"),
                                   "remainingMonths": ev.get("newTermMonths")}
                        new_loan["payment"] = _monthly_payment(new_loan)
                        st["loans"][i] = new_loan
            elif t == "TRANSFER":
                pass  # v1: 버킷 간 이동은 cash 총액에 중립이므로 생략

        # 만기 도래 이자만 대출 — 별도 조치가 없었다면 만기에 잔액을 일시상환한다고 가정
        for loan in st["loans"]:
            if loan.get("repaymentType") == "INTEREST_ONLY" and loan.get("remainingMonths") == 0 \
                    and loan["balance"] > 0:
                one_off_this_month += loan["balance"]
                loan["balance"] = 0
                assumptions.append({"key": f"'{loan['id']}' 만기 도래 — 잔액을 현금으로 즉시 상환한다고 가정 "
                                    f"(재대출/재계약 미고려)", "confidence": "ASSUMPTION"})

        debt_service = 0
        for loan in st["loans"]:
            if loan["balance"] <= 0:
                continue
            r = loan["rate"] / 12
            interest = loan["balance"] * r
            payment = loan["payment"]
            if loan.get("repaymentType") == "INTEREST_ONLY":
                principal = 0
            else:
                principal = min(max(payment - interest, 0), loan["balance"])
            loan["balance"] = max(0, loan["balance"] - principal)
            if loan.get("remainingMonths") is not None:
                loan["remainingMonths"] = max(0, loan["remainingMonths"] - 1)
            total_interest += interest
            debt_service += (interest + principal) if loan.get("repaymentType") != "INTEREST_ONLY" else interest

        surplus = st["income"] - st["fixed"] - st["variable"] - debt_service - one_off_this_month
        st["cash"] += surplus
        cumulative_surplus += surplus

        essential = st["fixed"] + debt_service
        ef_months = round(st["cash"] / essential, 2) if essential > 0 else None
        dsr = round(debt_service / st["income"], 4) if st["income"] > 0 else None

        if surplus < 0 and first_negative_surplus is None:
            first_negative_surplus = m
        if st["cash"] < min_cash:
            min_cash, min_cash_month = st["cash"], m
        if ef_months is not None and ef_months < EMERGENCY_FUND_TARGET_MONTHS and emergency_breach is None:
            emergency_breach = m
        if st["cash"] < 0 and insolvency is None:
            insolvency = m
        if dsr is not None and dsr > dsr_peak:
            dsr_peak, dsr_peak_month = dsr, m

        net_worth = st["cash"] + st["otherAssets"] - sum(l["balance"] for l in st["loans"])
        months.append({"ym": ym, "income": round(st["income"]), "fixed": round(st["fixed"]),
                       "variable": round(st["variable"]), "debtService": round(debt_service),
                       "surplus": round(surplus), "cashBalance": round(st["cash"]),
                       "liquidAssets": round(st["cash"]), "netWorth": round(net_worth),
                       "activeLoans": [{"id": l["id"], "balance": round(l["balance"]),
                                       "payment": round(l["payment"])} for l in st["loans"] if l["balance"] > 0]})

    if insolvency is not None:
        binding = "CASH"
    elif emergency_breach is not None:
        binding = "EMERGENCY_FUND"
    elif dsr_peak > DSR_STRESS_THRESHOLD:
        binding = "DSR"
    else:
        binding = "NONE"

    feasibility = "INFEASIBLE" if insolvency is not None else \
        ("FEASIBLE_WITH_STRAIN" if emergency_breach is not None else "FEASIBLE")

    return {
        "months": months,
        "breakPoints": {"firstNegativeSurplusMonth": first_negative_surplus,
                        "minCashMonth": min_cash_month, "minCashAmount": round(min_cash),
                        "emergencyFundBreachMonth": emergency_breach, "dsrPeakMonth": dsr_peak_month,
                        "dsrPeak": round(dsr_peak, 4), "insolvencyMonth": insolvency, "goalsMissed": []},
        "summary": {"netWorthAtHorizon": months[-1]["netWorth"] if months else None,
                   "cumulativeSurplus": round(cumulative_surplus), "totalInterestPaid": round(total_interest),
                   "emergencyMonthsAtHorizon": (months[-1]["cashBalance"] /
                       (st["fixed"] + (months[-1]["debtService"] if months else 0))
                       if months and (st["fixed"] + months[-1]["debtService"]) > 0 else None)},
        "feasibility": feasibility, "bindingConstraint": binding, "assumptions": assumptions,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--horizon-months", type=int)
    ap.add_argument("--compare", choices=["baseline"], default="baseline")
    args = ap.parse_args()

    ctx = wc.load_json(args.context)
    scenario = wc.load_json(args.scenario)
    horizon = args.horizon_months or scenario.get("horizonMonths", 60)

    start = build_baseline_state(ctx)
    with_events = simulate(start, scenario.get("events", []), horizon)
    baseline = simulate(start, [], horizon) if args.compare == "baseline" else None

    data = {"scenario": scenario.get("id"), "label": scenario.get("label"), "horizonMonths": horizon,
            "months": with_events["months"], "breakPoints": with_events["breakPoints"],
            "feasibility": with_events["feasibility"], "bindingConstraint": with_events["bindingConstraint"]}
    if baseline:
        data["vsBaseline"] = {
            "netWorthAtHorizon": {"scenario": with_events["summary"]["netWorthAtHorizon"],
                                  "baseline": baseline["summary"]["netWorthAtHorizon"],
                                  "delta": (with_events["summary"]["netWorthAtHorizon"] or 0) -
                                           (baseline["summary"]["netWorthAtHorizon"] or 0)},
            "cumulativeSurplus": with_events["summary"]["cumulativeSurplus"],
            "totalInterestPaid": with_events["summary"]["totalInterestPaid"],
            "emergencyMonthsAtHorizon": with_events["summary"]["emergencyMonthsAtHorizon"],
        }

    assumptions = with_events["assumptions"] + list(scenario.get("assumptions") or [])
    payload = wc.envelope("scenario.py", data, assumptions=assumptions, context_hash=ctx.get("contextHash"))
    wc.emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
