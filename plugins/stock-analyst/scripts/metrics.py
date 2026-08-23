"""SEC XBRL 팩트 → 정규화된 재무제표 + 성장률/수익성/안정성 지표.

이 모듈은 네트워크를 타지 않는 순수 함수만 담는다 (단위 테스트 대상).
문서 §7, §11의 수집·계산 항목을 그대로 구현한다.
"""
from __future__ import annotations

from datetime import date

# us-gaap 태그는 기업마다 다르게 쓴다. 우선순위 목록으로 폴백한다.
TAGS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "grossProfit": ["GrossProfit"],
    "operatingIncome": ["OperatingIncomeLoss"],
    "netIncome": ["NetIncomeLoss", "ProfitLoss"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
    "operatingCashFlow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "interestExpense": ["InterestExpense", "InterestIncomeExpenseNet", "InterestExpenseDebt"],
    "researchDevelopment": ["ResearchAndDevelopmentExpense"],
    "stockComp": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    # 시점 항목 (instant)
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsAndShortTermInvestments"],
    "shortTermInvestments": [
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
        "MarketableSecurities",
    ],
    "totalAssets": ["Assets"],
    "currentAssets": ["AssetsCurrent"],
    "inventory": ["InventoryNet"],
    "totalLiabilities": ["Liabilities"],
    "currentLiabilities": ["LiabilitiesCurrent"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "longTermDebt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "shortTermDebt": ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings"],
    "sharesOutstanding": ["CommonStockSharesOutstanding"],
    "dilutedShares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}

INSTANT = {"cash", "shortTermInvestments", "totalAssets", "currentAssets", "inventory",
           "totalLiabilities", "currentLiabilities", "equity", "longTermDebt",
           "shortTermDebt", "sharesOutstanding"}

ANNUAL_FORMS = ("10-K", "20-F", "40-F")
QUARTER_FORMS = ("10-Q", "10-K")


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _facts_for(companyfacts: dict, names: list[str]) -> tuple[str | None, list[dict]]:
    """후보 태그 중 **가장 최근까지 보고된** 것을 고른다.

    우선순위 목록의 첫 번째를 그냥 쓰면 안 된다 — 기업이 중간에 태그를 바꾸면
    옛 태그에 오래된 값만 남아 있어서, 손익계산서와 재무상태표의 회계연도가
    어긋난 채 비율이 계산된다 (NVDA에서 실제로 매출총이익률 570%가 나왔다).
    """
    us_gaap = ((companyfacts or {}).get("facts") or {}).get("us-gaap") or {}
    dei = ((companyfacts or {}).get("facts") or {}).get("dei") or {}
    best = (None, [], "", 0)  # tag, entries, latest_end, count
    for rank, name in enumerate(names):
        node = us_gaap.get(name) or dei.get(name)
        if not node:
            continue
        units = node.get("units") or {}
        entries = None
        for unit_key in ("USD", "USD/shares", "shares", "pure"):
            if units.get(unit_key):
                entries = units[unit_key]
                break
        if entries is None and units:
            entries = next(iter(units.values()))
        if not entries:
            continue
        latest = max((e.get("end") or "") for e in entries)
        # 최신 보고일이 1년 이상 앞서면 그 태그가 이긴다. 비슷하면 우선순위가 앞선 태그.
        if latest > best[2]:
            best = (name, entries, latest, len(entries))
    return best[0], best[1]


def _pick(entries: list[dict], instant: bool, period: str) -> list[dict]:
    """중복 정정 공시를 제거하고 (end 기준 최신 filed) 기간별로 고른다."""
    forms = ANNUAL_FORMS if period == "annual" else QUARTER_FORMS
    lo, hi = (350, 380) if period == "annual" else (80, 100)
    best: dict[str, dict] = {}
    for e in entries:
        if e.get("form") not in forms:
            continue
        end = e.get("end")
        val = e.get("val")
        if not end or val is None:
            continue
        if not instant:
            start = e.get("start")
            if not start:
                continue
            try:
                span = _days(start, end)
            except ValueError:
                continue
            if not (lo <= span <= hi):
                continue
        prev = best.get(end)
        if prev is None or (e.get("filed") or "") >= (prev.get("filed") or ""):
            best[end] = e
    rows = [{"end": k, "value": float(v["val"]), "form": v.get("form"),
             "fy": v.get("fy"), "fp": v.get("fp"), "filed": v.get("filed")}
            for k, v in best.items()]
    rows.sort(key=lambda r: r["end"])
    return rows


def extract_statements(companyfacts: dict, periods: int = 6) -> dict:
    """companyfacts → {annual: {...}, quarterly: {...}, tagsUsed: {...}}"""
    out = {"annual": {}, "quarterly": {}, "tagsUsed": {}, "missing": []}
    for field, names in TAGS.items():
        tag, entries = _facts_for(companyfacts, names)
        if not tag:
            out["missing"].append(field)
            continue
        out["tagsUsed"][field] = tag
        instant = field in INSTANT
        out["annual"][field] = _pick(entries, instant, "annual")[-periods:]
        out["quarterly"][field] = _pick(entries, instant, "quarterly")[-periods * 2:]

    for scope in ("annual", "quarterly"):
        ocf = {r["end"]: r["value"] for r in out[scope].get("operatingCashFlow", [])}
        capex = {r["end"]: r["value"] for r in out[scope].get("capex", [])}
        fcf = [{"end": k, "value": v - capex.get(k, 0.0)} for k, v in sorted(ocf.items())
               if k in capex or capex]
        out[scope]["freeCashFlow"] = fcf
    return out


def _last(series: list[dict]):
    return series[-1]["value"] if series else None


def _near(series: list[dict], end: str, tol_days: int = 45):
    """회계연도 종료일 근처(±tol)의 값을 고른다.

    재무상태표(시점)와 손익계산서(기간)의 종료일이 며칠 어긋나는 경우가 있어
    정확히 일치하는 키만 찾으면 값이 통째로 비게 된다.
    """
    if not series or not end:
        return None
    try:
        target = date.fromisoformat(end)
    except ValueError:
        return None
    best, best_gap = None, None
    for row in series:
        try:
            gap = abs((date.fromisoformat(row["end"]) - target).days)
        except (ValueError, KeyError):
            continue
        if gap <= tol_days and (best_gap is None or gap < best_gap):
            best, best_gap = row["value"], gap
    return best


def align_annual(statements: dict, periods: int = 6) -> list[dict]:
    """연도별로 모든 항목을 같은 회계연도에 맞춰 정렬한 표를 만든다.

    항목마다 독립적으로 마지막 값을 꺼내 쓰면 서로 다른 회계연도의 숫자를
    나누게 되므로, 반드시 이 표를 거쳐 계산한다.
    """
    a = statements.get("annual", {})
    anchor_field = "revenue" if a.get("revenue") else "netIncome"
    anchors = [r["end"] for r in a.get(anchor_field, [])][-periods:]
    rows = []
    for end in anchors:
        row = {"end": end}
        for field, series in a.items():
            row[field] = _near(series, end)
        rows.append(row)
    return rows


def _yoy_rows(rows: list[dict], field: str):
    vals = [r.get(field) for r in rows]
    if len(vals) < 2 or vals[-1] is None or not vals[-2]:
        return None
    return vals[-1] / vals[-2] - 1


def _cagr_rows(rows: list[dict], field: str, years: int):
    vals = [r.get(field) for r in rows]
    if len(vals) < years + 1:
        return None
    start, end = vals[-(years + 1)], vals[-1]
    if start is None or end is None or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def _div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def compute_metrics(statements: dict, price: float | None = None,
                    shares: float | None = None, tax_rate: float = 0.21) -> dict:
    """문서 §11 성장성·수익성·안정성·현금흐름 지표. 모두 같은 회계연도 기준."""
    rows = align_annual(statements)
    if not rows:
        return {"latest": {}, "growth": {}, "profitability": {}, "stability": {},
                "cashFlow": {}, "valuation": {}, "annualTable": [],
                "coverage": _coverage(statements)}
    cur = rows[-1]

    revenue = cur.get("revenue")
    gross = cur.get("grossProfit")
    op = cur.get("operatingIncome")
    net = cur.get("netIncome")
    eps = cur.get("eps")
    ocf = cur.get("operatingCashFlow")
    free = cur.get("freeCashFlow")
    equity = cur.get("equity")
    assets = cur.get("totalAssets")
    cash = (cur.get("cash") or 0) + (cur.get("shortTermInvestments") or 0)
    debt = (cur.get("longTermDebt") or 0) + (cur.get("shortTermDebt") or 0)
    cur_a, cur_l, inv = cur.get("currentAssets"), cur.get("currentLiabilities"), cur.get("inventory")
    interest = cur.get("interestExpense")
    shares = shares or cur.get("sharesOutstanding") or cur.get("dilutedShares")

    # 한국 기업(DART)은 지배주주 지표를 따로 준다. EPS·ROE는 지배주주 기준이 관행이며,
    # 지주회사·자회사 다수 보유 기업에서 연결 기준으로 계산하면 ROE가 부풀려진다.
    net_owners = cur.get("netIncomeOwners")
    equity_owners = cur.get("equityOwners")
    controlling = None
    if net_owners is not None or equity_owners is not None:
        controlling = {
            "netIncomeOwners": net_owners,
            "equityOwners": equity_owners,
            "roeControlling": _div(net_owners, equity_owners),
            "minorityShareOfIncome": (
                (net - net_owners) / net if (net and net_owners is not None) else None),
            "basis": "지배주주 기준 (EPS·ROE는 이 값을 쓴다)",
        }

    # 값이 0인 것과 아예 보고되지 않은 것을 구분한다.
    # (예: NVDA FY2026은 유동 유가증권 태그를 보고하지 않아 현금이 과소계상된다)
    gaps = [f for f in ("revenue", "grossProfit", "operatingIncome", "netIncome", "eps",
                        "operatingCashFlow", "capex", "cash", "shortTermInvestments",
                        "equity", "totalAssets", "currentAssets", "currentLiabilities",
                        "longTermDebt", "sharesOutstanding")
            if cur.get(f) is None]
    # 주식수는 별도 API로 받아 넘길 수 있다 (DART stockTotqySttus). 넘어왔으면 결측이 아니다.
    if shares is not None and "sharesOutstanding" in gaps:
        gaps.remove("sharesOutstanding")

    nopat = op * (1 - tax_rate) if op is not None else None
    invested = (equity or 0) + debt - cash if equity is not None else None
    ebitda_proxy = op  # 감가상각을 XBRL에서 일관되게 못 뽑는 경우가 많아 영업이익으로 근사한다

    growth = {
        "revenueYoY": _yoy_rows(rows, "revenue"),
        "epsYoY": _yoy_rows(rows, "eps"),
        "fcfYoY": _yoy_rows(rows, "freeCashFlow"),
        "revenueCagr3Y": _cagr_rows(rows, "revenue", 3),
        "revenueCagr5Y": _cagr_rows(rows, "revenue", 5),
        "epsCagr3Y": _cagr_rows(rows, "eps", 3),
        "epsCagr5Y": _cagr_rows(rows, "eps", 5),
    }
    profitability = {
        "grossMargin": _div(gross, revenue),
        "operatingMargin": _div(op, revenue),
        "netMargin": _div(net, revenue),
        "fcfMargin": _div(free, revenue),
        # 지배주주 값이 있으면 ROE는 그쪽을 쓴다 (한국 회계 관행)
        "roe": _div(net_owners, equity_owners) if controlling and net_owners is not None
               and equity_owners else _div(net, equity),
        "roeBasis": "controlling" if (controlling and net_owners is not None and equity_owners)
                    else "consolidated",
        "roa": _div(net, assets),
        "roic": _div(nopat, invested) if invested and invested > 0 else None,
    }
    stability = {
        "totalDebt": debt,
        "netDebt": debt - cash,
        "debtToEquity": _div(debt, equity),
        "netDebtToOperatingIncome": _div(debt - cash, ebitda_proxy) if ebitda_proxy and ebitda_proxy > 0 else None,
        "interestCoverage": _div(op, abs(interest)) if interest else None,
        "currentRatio": _div(cur_a, cur_l),
        "quickRatio": _div((cur_a - inv) if (cur_a is not None and inv is not None) else None, cur_l),
    }
    cashflow = {
        "operatingCashFlow": ocf,
        "freeCashFlow": free,
        "fcfMargin": _div(free, revenue),
        "fcfConversion": _div(free, net),
        "capex": cur.get("capex"),
        "stockBasedComp": cur.get("stockComp"),
        "sbcToRevenue": _div(cur.get("stockComp"), revenue),
    }
    valuation = {}
    if price and shares:
        mcap = price * shares
        ev = mcap + debt - cash
        valuation = {
            "price": price,
            "sharesOutstanding": shares,
            "marketCap": mcap,
            "enterpriseValue": ev,
            "trailingPE": _div(price, eps),
            "priceToSales": _div(mcap, revenue),
            "priceToBook": _div(mcap, equity),
            "evToRevenue": _div(ev, revenue),
            "evToFcf": _div(ev, free),
            "fcfYield": _div(free, mcap),
            "earningsYield": _div(net, mcap),
        }
        if "shortTermInvestments" in gaps or "cash" in gaps:
            valuation["evWarning"] = (
                "현금성자산 항목 일부가 해당 회계연도에 보고되지 않아 순현금이 과소, "
                "EV가 과대 계상되었을 수 있다. EV 기반 배수는 CONFLICTED 가능성을 안고 읽을 것."
            )
        peg_g = growth.get("epsCagr3Y")
        if valuation.get("trailingPE") and peg_g and peg_g > 0:
            valuation["peg"] = valuation["trailingPE"] / (peg_g * 100)

    return {
        "latest": {
            "periodEnd": cur.get("end"),
            "revenue": revenue, "grossProfit": gross, "operatingIncome": op,
            "netIncome": net, "eps": eps, "operatingCashFlow": ocf,
            "freeCashFlow": free, "cash": cash, "totalDebt": debt,
            "totalAssets": assets, "equity": equity, "sharesOutstanding": shares,
        },
        "annualTable": rows,
        "growth": growth,
        "profitability": profitability,
        "stability": stability,
        "cashFlow": cashflow,
        "valuation": valuation,
        "controllingInterest": controlling,
        "coverage": _coverage(statements),
        "dataGaps": gaps,
        "notes": [
            "모든 비율은 동일 회계연도 기준으로 정렬해 계산했다 (align_annual).",
            f"ROIC의 세율은 {tax_rate:.0%} 가정값이다 (ASSUMPTION).",
            "netDebtToOperatingIncome은 EBITDA가 아니라 영업이익 기준 근사치다.",
        ],
    }


def _coverage(statements: dict) -> dict:
    """데이터 커버리지 — 문서 §68 INSUFFICIENT DATA 판정의 입력."""
    core = ["revenue", "operatingIncome", "netIncome", "operatingCashFlow", "equity"]
    a = statements.get("annual", {})
    have = [f for f in core if a.get(f)]
    return {
        "coreFields": core,
        "present": have,
        "missing": [f for f in core if f not in have],
        "ratio": round(len(have) / len(core), 2),
        "annualPeriods": len(a.get("revenue", [])),
    }
