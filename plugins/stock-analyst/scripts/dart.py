"""DART OpenAPI 어댑터 — 한국 상장사 재무제표 (Tier 1).

DART_API_KEY 환경변수가 있을 때만 동작한다. 없으면 조용히 비활성화되고
fetch.py가 WebSearch 폴백 안내를 돌려준다.

SEC 경로와 **같은 자료구조**로 정규화해서 metrics.compute_metrics를 그대로 재사용한다.
"""
from __future__ import annotations

import io
import os
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

from common import FetchError, http_get, read_cache, write_cache

BASE = "https://opendart.fss.or.kr/api"
REPRT_ANNUAL = "11011"  # 사업보고서

# DART는 IFRS 표준 계정 ID를 준다. account_id로 매핑하고, 없으면 계정명으로 폴백한다.
BY_ID = {
    "ifrs-full_Revenue": "revenue",
    "ifrs-full_GrossProfit": "grossProfit",
    "dart_OperatingIncomeLoss": "operatingIncome",
    "ifrs-full_ProfitLoss": "netIncome",
    "ifrs-full_ProfitLossAttributableToOwnersOfParent": "netIncomeOwners",
    "ifrs-full_BasicEarningsLossPerShare": "eps",
    "ifrs-full_DilutedEarningsLossPerShare": "epsDiluted",
    "ifrs-full_Assets": "totalAssets",
    "ifrs-full_CurrentAssets": "currentAssets",
    "ifrs-full_Inventories": "inventory",
    "ifrs-full_CashAndCashEquivalents": "cash",
    "ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents": "shortTermInvestments",
    "ifrs-full_Liabilities": "totalLiabilities",
    "ifrs-full_CurrentLiabilities": "currentLiabilities",
    "ifrs-full_Equity": "equity",
    "ifrs-full_EquityAttributableToOwnersOfParent": "equityOwners",
    "ifrs-full_CashFlowsFromUsedInOperatingActivities": "operatingCashFlow",
    "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": "capex",
}

# 같은 account_id가 여러 재무제표에 중복 등장한다. 특히 SCE(자본변동표)는 105행에 걸쳐
# ifrs-full_Equity / ifrs-full_ProfitLoss를 구성요소별로 다시 내보내서, 필터 없이 읽으면
# 자본총계가 4.4조, 당기순이익이 0.9조로 나온다 (삼성전자에서 실제로 발생했다).
# 필드별로 어느 재무제표에서 읽을지 고정하고, 앞에 있는 구분을 우선한다. SCE는 절대 쓰지 않는다.
FIELD_DIV = {
    "revenue": ("IS", "CIS"),
    "grossProfit": ("IS", "CIS"),
    "operatingIncome": ("IS", "CIS"),
    "netIncome": ("IS", "CIS"),
    "netIncomeOwners": ("IS", "CIS"),
    "eps": ("IS", "CIS"),
    "epsDiluted": ("IS", "CIS"),
    "interestExpense": ("IS", "CIS"),
    "totalAssets": ("BS",), "currentAssets": ("BS",), "inventory": ("BS",),
    "cash": ("BS",), "shortTermInvestments": ("BS",),
    "totalLiabilities": ("BS",), "currentLiabilities": ("BS",),
    "equity": ("BS",), "equityOwners": ("BS",),
    "shortTermDebt": ("BS",), "longTermDebt": ("BS",),
    "operatingCashFlow": ("CF",), "capex": ("CF",),
}

# 차입금은 IFRS 표준 ID로 안 내려오는 경우가 많아 계정명으로 잡는다.
DEBT_SHORT_NAMES = ("단기차입금", "유동성장기부채", "유동성사채", "유동차입금")
DEBT_LONG_NAMES = ("사채", "장기차입금", "비유동차입금")
INTEREST_NAMES = ("이자비용",)


def available() -> bool:
    return bool(os.environ.get("DART_API_KEY"))


def _key() -> str:
    k = os.environ.get("DART_API_KEY")
    if not k:
        raise FetchError("configuration-required", "DART_API_KEY 환경변수가 없다")
    return k


def _check(payload: dict, ctx: str) -> dict:
    status = str(payload.get("status", ""))
    if status == "000":
        return payload
    codes = {
        "010": "등록되지 않은 인증키", "011": "사용할 수 없는 인증키",
        "012": "접근할 수 없는 IP", "013": "조회된 데이터 없음",
        "020": "일일 요청 한도(20,000건) 초과", "021": "조회 가능 회사 개수 초과",
        "100": "필드 부적절", "800": "시스템 점검 중", "900": "정의되지 않은 오류",
    }
    code = "no-data" if status == "013" else "provider-error"
    raise FetchError(code, f"DART {ctx}: [{status}] {codes.get(status, payload.get('message', ''))}")


def corp_map() -> dict:
    """종목코드(6자리) → 고유번호(8자리). DART의 가장 흔한 함정이라 반드시 거친다."""
    cached = read_cache("tickermap", "_dart")
    if cached and cached.get("ok"):
        return cached["data"]

    url = f"{BASE}/corpCode.xml?crtfc_key={_key()}"
    data = http_get(url, as_json=False, as_bytes=True, timeout=90, retries=1)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        # 인증키 오류 시 DART는 ZIP 대신 XML 에러 문서를 준다.
        snippet = data[:300].decode("utf-8", errors="replace")
        raise FetchError("invalid-payload", f"DART corpCode 응답이 ZIP이 아니다: {snippet}")

    root = ET.fromstring(zf.read(zf.namelist()[0]))
    by_stock = {}
    for e in root.findall("list"):
        stock = (e.findtext("stock_code") or "").strip()
        if not stock:
            continue  # 비상장
        by_stock[stock] = {
            "corpCode": (e.findtext("corp_code") or "").strip(),
            "name": (e.findtext("corp_name") or "").strip(),
        }
    out = {"byStockCode": by_stock, "count": len(by_stock)}
    write_cache("tickermap", "_dart", {"ok": True, "data": out, "meta": {"source": "dart"}})
    return out


def resolve_corp_code(ticker: str) -> dict:
    """'005930.KS' 또는 '005930' → {corpCode, name}"""
    code = "".join(ch for ch in ticker.split(".")[0] if ch.isdigit())[:6]
    if len(code) != 6:
        raise FetchError("symbol-not-found", f"{ticker}: 한국 6자리 종목코드가 아니다")
    hit = corp_map()["byStockCode"].get(code)
    if not hit:
        raise FetchError("symbol-not-found", f"{code}: DART 상장사 목록에 없다 (상장폐지·비상장 가능)")
    return {**hit, "stockCode": code}


def _num(s):
    if s in (None, "", "-"):
        return None
    try:
        return float(str(s).replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def company_info(corp_code: str) -> dict:
    """기업개황. 결산월(acc_mt)을 얻는 유일한 경로다."""
    cached = read_cache("profile", f"_dart_{corp_code}")
    if cached and cached.get("ok"):
        return cached["data"]
    url = f"{BASE}/company.json?crtfc_key={_key()}&corp_code={corp_code}"
    payload = _check(http_get(url, timeout=30), "company")
    write_cache("profile", f"_dart_{corp_code}", {"ok": True, "data": payload,
                                                  "meta": {"source": "dart"}})
    return payload


_LAST_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
             7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _fiscal_end(year: int, acc_mt: int) -> str:
    """회계연도 종료일. DART 재무제표 응답에는 날짜 필드가 비어 있어(thstrm_dt=None)
    기업개황의 결산월로 직접 만든다. 3월 결산사는 2025 사업연도 → 2026-03-31이 아니라
    DART 기준으로 2025-03-31이다 (사업연도 표기를 그대로 따른다)."""
    day = _LAST_DAY[acc_mt]
    if acc_mt == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        day = 29
    return f"{year:04d}-{acc_mt:02d}-{day:02d}"


def fetch_year(corp_code: str, year: int, fs_div: str = "CFS") -> list[dict]:
    url = (f"{BASE}/fnlttSinglAcntAll.json?crtfc_key={_key()}&corp_code={corp_code}"
           f"&bsns_year={year}&reprt_code={REPRT_ANNUAL}&fs_div={fs_div}")
    payload = _check(http_get(url, timeout=45), f"fnlttSinglAcntAll {year}")
    return payload.get("list") or []


def shares_outstanding(corp_code: str, year: int) -> dict | None:
    """주식의 총수 현황. 보통주 발행주식총수에서 자기주식을 뺀 유통주식수를 쓴다."""
    url = (f"{BASE}/stockTotqySttus.json?crtfc_key={_key()}&corp_code={corp_code}"
           f"&bsns_year={year}&reprt_code={REPRT_ANNUAL}")
    try:
        payload = _check(http_get(url, timeout=30), "stockTotqySttus")
    except FetchError:
        return None
    common, preferred, treasury = None, None, 0.0
    for row in payload.get("list") or []:
        kind = (row.get("se") or "").strip()
        issued = _num(row.get("istc_totqy"))
        tesstk = _num(row.get("tesstk_co")) or 0.0
        if issued is None:
            continue
        if "보통주" in kind:
            common, treasury = issued, tesstk
        elif "우선주" in kind:
            preferred = issued
    if common is None:
        return None
    return {
        "commonIssued": common,
        "treasury": treasury,
        "commonOutstanding": common - treasury,
        "preferredIssued": preferred,
    }


def _assign(bucket: dict, field: str, end: str | None, value, prio: int):
    """같은 (필드, 회계연도)에 여러 후보가 오면 우선순위가 높은(숫자가 작은) 것만 남긴다."""
    if not end or value is None:
        return
    slot = bucket.setdefault(field, {})
    prev = slot.get(end)
    if prev is None or prio < prev[0]:
        slot[end] = (prio, value)


def ingest_rows(rows: list[dict], year: int, acc_mt: int,
                collected: dict, tags_used: dict) -> None:
    """DART 응답 행들을 필드별 시계열로 흡수한다 (순수 함수, 네트워크 없음).

    한 응답에 당기·전기·전전기 3개년이 들어 있고, 같은 account_id가 여러 재무제표에
    중복 등장하므로 FIELD_DIV로 출처를 고정한다.
    """
    for row in rows:
        div = (row.get("sj_div") or "").strip()
        if div == "SCE":
            continue
        aid = (row.get("account_id") or "").strip()
        nm = (row.get("account_nm") or "").strip()
        field = BY_ID.get(aid)
        if field is None:
            if nm in DEBT_SHORT_NAMES:
                field = "shortTermDebt"
            elif nm in DEBT_LONG_NAMES:
                field = "longTermDebt"
            elif nm in INTEREST_NAMES:
                field = "interestExpense"
            else:
                continue
        allowed = FIELD_DIV.get(field)
        if allowed and div not in allowed:
            continue
        prio = allowed.index(div) if allowed else 9
        tags_used.setdefault(field, aid or nm)
        for offset, which in enumerate(("thstrm", "frmtrm", "bfefrmtrm")):
            _assign(collected, field, _fiscal_end(year - offset, acc_mt),
                    _num(row.get(f"{which}_amount")), prio)


def annual_statements(corp_code: str, latest_year: int, fs_div: str = "CFS",
                      periods: int = 6) -> dict:
    """DART 연간 재무제표 → SEC 경로와 동일한 구조.

    한 번의 호출이 당기·전기·전전기 3개년을 주므로, 2회 호출로 6개년을 만든다.
    """
    try:
        acc_mt = int((company_info(corp_code).get("acc_mt") or "12").strip() or 12)
    except (ValueError, FetchError):
        acc_mt = 12

    collected: dict[str, dict[str, float]] = {}
    tags_used: dict[str, str] = {}
    fetched_years, errors = [], []

    for year in (latest_year, latest_year - 3):
        if year < 2015:
            break
        try:
            rows = fetch_year(corp_code, year, fs_div)
        except FetchError as exc:
            errors.append(f"{year}: {exc.message}")
            continue
        fetched_years.append(year)
        ingest_rows(rows, year, acc_mt, collected, tags_used)

    annual = {}
    for field, by_end in collected.items():
        annual[field] = [{"end": e, "value": v} for e, (_, v) in sorted(by_end.items())][-periods:]

    ocf = {r["end"]: r["value"] for r in annual.get("operatingCashFlow", [])}
    capex = {r["end"]: r["value"] for r in annual.get("capex", [])}
    if ocf:
        annual["freeCashFlow"] = [{"end": e, "value": v - capex.get(e, 0.0)}
                                  for e, v in sorted(ocf.items())][-periods:]

    if not annual.get("revenue"):
        raise FetchError("no-data",
                         f"DART에서 매출 계정을 찾지 못했다 ({', '.join(errors) or 'rows 비어 있음'})")

    return {
        "annual": annual,
        "quarterly": {},
        "tagsUsed": tags_used,
        "missing": [],
        "fetchedYears": fetched_years,
        "fiscalMonth": acc_mt,
        "fsDiv": fs_div,
        "errors": errors,
    }


def recent_filings(corp_code: str, months: int = 12, limit: int = 15) -> list[dict]:
    """최근 공시 목록. 미국 8-K에 해당하는 수시공시까지 포함한다."""
    from datetime import date, timedelta
    end = date.today()
    start = end - timedelta(days=30 * months)
    url = (f"{BASE}/list.json?crtfc_key={_key()}&corp_code={corp_code}"
           f"&bgn_de={start:%Y%m%d}&end_de={end:%Y%m%d}&page_count=100")
    try:
        payload = _check(http_get(url, timeout=30), "list")
    except FetchError as exc:
        if exc.code == "no-data":
            return []
        raise
    out = []
    for row in payload.get("list") or []:
        rcept = row.get("rcept_no")
        out.append({
            "date": row.get("rcept_dt"),
            "title": row.get("report_nm"),
            "submitter": row.get("flr_nm"),
            "remark": row.get("rm"),
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept}" if rcept else None,
        })
        if len(out) >= limit:
            break
    return out
