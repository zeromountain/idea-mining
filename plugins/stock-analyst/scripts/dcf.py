#!/usr/bin/env python3
"""DCF 밸류에이션 (문서 §14~15) — 계산은 여기서만 한다.

에이전트는 **가정만** JSON으로 제출하고, 이 스크립트가 NOPAT → FCF → TV → EV →
Equity → 주당 적정가치를 계산한다. LLM이 직접 곱셈을 하면 검증할 수 없기 때문이다.

CLI: python3 dcf.py <assumptions.json|->
"""
from __future__ import annotations

import json
import sys

REQUIRED = ("baseRevenue", "sharesOutstanding")


def project(base_revenue: float, growth: list[float], margin, fcf_conversion,
            tax_rate: float, wacc: float, terminal_growth: float) -> dict:
    """단일 시나리오 현금흐름 투영."""
    if wacc <= terminal_growth:
        raise ValueError(f"WACC({wacc})는 영구성장률({terminal_growth})보다 커야 한다")
    years = len(growth)
    margins = margin if isinstance(margin, list) else [margin] * years
    convs = fcf_conversion if isinstance(fcf_conversion, list) else [fcf_conversion] * years
    if len(margins) != years or len(convs) != years:
        raise ValueError("operatingMargin / fcfConversion 길이가 revenueGrowth와 다르다")

    rows, pv_sum, revenue = [], 0.0, base_revenue
    for i in range(years):
        revenue *= (1 + growth[i])
        ebit = revenue * margins[i]
        nopat = ebit * (1 - tax_rate)
        fcf = nopat * convs[i]
        discount = (1 + wacc) ** (i + 1)
        pv = fcf / discount
        pv_sum += pv
        rows.append({
            "year": i + 1, "revenue": revenue, "growth": growth[i],
            "operatingMargin": margins[i], "ebit": ebit, "nopat": nopat,
            "fcf": fcf, "discountFactor": 1 / discount, "presentValue": pv,
        })

    terminal_fcf = rows[-1]["fcf"] * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1 + wacc) ** years)
    ev = pv_sum + pv_terminal
    return {
        "projection": rows,
        "pvExplicit": pv_sum,
        "terminalValue": terminal_value,
        "pvTerminal": pv_terminal,
        "enterpriseValue": ev,
        "terminalShare": pv_terminal / ev if ev else None,
    }


def scenario_value(assumptions: dict, s: dict, tax_rate: float) -> dict:
    core = project(
        assumptions["baseRevenue"], s["revenueGrowth"], s["operatingMargin"],
        s.get("fcfConversion", 1.0), s.get("taxRate", tax_rate),
        s["wacc"], s["terminalGrowth"],
    )
    net_debt = assumptions.get("netDebt", 0.0) or 0.0
    equity = core["enterpriseValue"] - net_debt
    shares = assumptions["sharesOutstanding"]
    fair = equity / shares
    price = assumptions.get("currentPrice")
    core.update({
        "equityValue": equity,
        "fairValuePerShare": fair,
        "upside": (fair / price - 1) if price else None,
        "probability": s.get("probability"),
        "assumptions": {
            "revenueGrowth": s["revenueGrowth"], "operatingMargin": s["operatingMargin"],
            "fcfConversion": s.get("fcfConversion", 1.0), "wacc": s["wacc"],
            "terminalGrowth": s["terminalGrowth"], "taxRate": s.get("taxRate", tax_rate),
        },
    })
    return core


def sensitivity(assumptions: dict, s: dict, tax_rate: float) -> dict:
    """WACC × 영구성장률 민감도 — DCF를 정답처럼 읽지 않게 만드는 장치 (문서 §70)."""
    waccs = [round(s["wacc"] + d, 4) for d in (-0.02, -0.01, 0.0, 0.01, 0.02)]
    tgs = [round(s["terminalGrowth"] + d, 4) for d in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    grid = []
    for w in waccs:
        row = []
        for g in tgs:
            if w <= g:
                row.append(None)
                continue
            alt = dict(s, wacc=w, terminalGrowth=g)
            row.append(round(scenario_value(assumptions, alt, tax_rate)["fairValuePerShare"], 2))
        grid.append(row)
    return {"waccAxis": waccs, "terminalGrowthAxis": tgs, "fairValueGrid": grid}


def run(assumptions: dict) -> dict:
    missing = [k for k in REQUIRED if assumptions.get(k) in (None, 0)]
    if missing:
        return {"ok": False, "error": "insufficient-input",
                "message": f"DCF 필수 입력 누락: {', '.join(missing)}"}
    scenarios = assumptions.get("scenarios") or {}
    if not scenarios:
        return {"ok": False, "error": "insufficient-input", "message": "scenarios가 비어 있다"}

    tax_rate = assumptions.get("taxRate", 0.21)
    out, warnings = {}, []
    for name, s in scenarios.items():
        try:
            out[name] = scenario_value(assumptions, s, tax_rate)
        except (ValueError, KeyError, ZeroDivisionError) as exc:
            out[name] = {"error": str(exc)}
            warnings.append(f"{name} 시나리오 계산 실패: {exc}")

    valid = {k: v for k, v in out.items() if "fairValuePerShare" in v}
    weighted = None
    probs = sum(v.get("probability") or 0 for v in valid.values())
    if valid and abs(probs - 1.0) > 0.01:
        warnings.append(f"시나리오 확률 합이 {probs:.2f}다 (1.0이어야 한다). 가중평균은 정규화해 계산했다.")
    if valid and probs > 0:
        weighted = sum(v["fairValuePerShare"] * (v.get("probability") or 0) for v in valid.values()) / probs

    for name, v in valid.items():
        if v.get("terminalShare") and v["terminalShare"] > 0.75:
            warnings.append(
                f"{name}: 기업가치의 {v['terminalShare']:.0%}가 잔존가치에서 나온다 — "
                "영구성장률 가정에 결과가 지배당한다."
            )

    price = assumptions.get("currentPrice")
    result = {
        "ok": True,
        "ticker": assumptions.get("ticker"),
        "currentPrice": price,
        "scenarios": out,
        "probabilityWeightedFairValue": weighted,
        "weightedUpside": (weighted / price - 1) if (weighted and price) else None,
        "warnings": warnings,
        "labeling": "ASSUMPTION",
        "disclaimer": (
            "DCF 결과는 사실이 아니라 가정의 함수다. 아래 가정표와 민감도표를 함께 제시하지 않고 "
            "적정주가만 인용해서는 안 된다 (문서 §15, §70)."
        ),
    }
    if "base" in valid:
        result["sensitivity"] = sensitivity(assumptions, scenarios["base"], tax_rate)
    return result


def main() -> int:
    src = sys.stdin.read() if (len(sys.argv) < 2 or sys.argv[1] == "-") else open(sys.argv[1]).read()
    json.dump(run(json.loads(src)), sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
