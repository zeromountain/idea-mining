"""데이터 Provider 어댑터 (문서 §40~43).

각 함수는 원본 응답을 최소한으로 정규화해서 돌려주고, 실패하면 common.FetchError를 던진다.
어느 Provider를 쓸지 고르는 폴백 로직은 fetch.py가 담당한다.
"""
from __future__ import annotations

import json
import os
import urllib.parse
from datetime import datetime, timezone

from common import BROWSER_UA, FetchError, http_get, read_cache, write_cache

# ---------------------------------------------------------------- Yahoo Finance

YAHOO_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]


def yahoo_chart(symbol: str, rng: str = "5y", interval: str = "1d") -> dict:
    """일봉 OHLCV + 시세 메타. 키 불필요. 미국·한국(.KS/.KQ)·ETF 모두 지원."""
    last = None
    for host in YAHOO_HOSTS:
        url = (f"https://{host}/v8/finance/chart/{urllib.parse.quote(symbol)}"
               f"?range={rng}&interval={interval}&includeAdjustedClose=true")
        try:
            payload = http_get(url, headers={"User-Agent": BROWSER_UA})
        except FetchError as exc:
            last = exc
            continue
        chart = (payload or {}).get("chart") or {}
        if chart.get("error"):
            raise FetchError("symbol-not-found", f"{symbol}: {chart['error'].get('description')}")
        results = chart.get("result") or []
        if not results:
            raise FetchError("symbol-not-found", f"{symbol}: 결과 없음")
        return _parse_chart(results[0], url)
    raise last or FetchError("provider-unavailable", "yahoo-chart")


def _parse_chart(result: dict, url: str) -> dict:
    meta = result.get("meta") or {}
    stamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    adj = ((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []

    bars = []
    for i, ts in enumerate(stamps):
        close = _at(quote.get("close"), i)
        if close is None:
            continue
        bars.append({
            "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
            "open": _at(quote.get("open"), i),
            "high": _at(quote.get("high"), i),
            "low": _at(quote.get("low"), i),
            "close": close,
            "adjClose": _at(adj, i) if adj else close,
            "volume": _at(quote.get("volume"), i),
        })
    return {
        "symbol": meta.get("symbol"),
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "instrumentType": meta.get("instrumentType"),
        "longName": meta.get("longName") or meta.get("shortName"),
        "price": meta.get("regularMarketPrice"),
        "previousClose": meta.get("chartPreviousClose") or meta.get("previousClose"),
        "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow"),
        "regularMarketTime": meta.get("regularMarketTime"),
        "timezone": meta.get("exchangeTimezoneName"),
        "bars": bars,
        "sourceUrl": url,
    }


def _at(seq, i):
    if not seq or i >= len(seq):
        return None
    v = seq[i]
    return v if isinstance(v, (int, float)) else None


def yahoo_search(query: str, count: int = 6) -> list[dict]:
    """회사명 → 티커 후보. 429가 잦아 폴백 용도로만 쓴다."""
    last = None
    for host in YAHOO_HOSTS:
        url = (f"https://{host}/v1/finance/search?q={urllib.parse.quote(query)}"
               f"&quotesCount={count}&newsCount=0&enableFuzzyQuery=true")
        try:
            payload = http_get(url, headers={"User-Agent": BROWSER_UA}, retries=0)
        except FetchError as exc:
            last = exc
            continue
        out = []
        for q in (payload or {}).get("quotes") or []:
            if not q.get("symbol"):
                continue
            out.append({
                "ticker": q.get("symbol"),
                "name": q.get("longname") or q.get("shortname"),
                "exchange": q.get("exchDisp") or q.get("exchange"),
                "type": q.get("quoteType"),
                "source": "yahoo-search",
            })
        return out
    raise last or FetchError("provider-unavailable", "yahoo-search")


# ------------------------------------------------------------------- SEC EDGAR

def sec_ticker_map() -> dict:
    """티커 ↔ CIK ↔ 회사명 매핑 (Tier 1, 30일 캐시)."""
    cached = read_cache("tickermap", "_sec")
    if cached and cached.get("ok"):
        return cached["data"]
    url = "https://www.sec.gov/files/company_tickers.json"
    raw = http_get(url)
    by_ticker, by_name = {}, []
    for row in (raw or {}).values():
        t = str(row.get("ticker", "")).upper()
        if not t:
            continue
        entry = {"ticker": t, "cik": f"{int(row['cik_str']):010d}", "name": row.get("title", "")}
        by_ticker[t] = entry
        by_name.append(entry)
    data = {"byTicker": by_ticker, "all": by_name, "sourceUrl": url}
    write_cache("tickermap", "_sec", {"ok": True, "data": data, "meta": {"source": "sec"}})
    return data


def sec_companyfacts(cik: str) -> dict:
    """XBRL 전체 팩트. 수 MB이므로 절대 LLM에 그대로 넘기지 않는다 (문서 §49)."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    return http_get(url, timeout=45)


def sec_submissions(cik: str) -> dict:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    return http_get(url, timeout=30)


def sec_recent_filings(cik: str, forms=("10-K", "10-Q", "8-K"), limit: int = 12) -> list[dict]:
    payload = sec_submissions(cik)
    recent = ((payload or {}).get("filings") or {}).get("recent") or {}
    forms_list = recent.get("form") or []
    out = []
    for i, form in enumerate(forms_list):
        if form not in forms:
            continue
        acc = (recent.get("accessionNumber") or [None] * (i + 1))[i]
        doc = (recent.get("primaryDocument") or [None] * (i + 1))[i]
        acc_plain = (acc or "").replace("-", "")
        out.append({
            "form": form,
            "filingDate": (recent.get("filingDate") or [None] * (i + 1))[i],
            "reportDate": (recent.get("reportDate") or [None] * (i + 1))[i],
            "primaryDocDescription": (recent.get("primaryDocDescription") or [None] * (i + 1))[i],
            "url": (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_plain}/{doc}"
                    if acc_plain and doc else None),
        })
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------------ FRED

FRED_SERIES = {
    "DGS10": "10년 국채금리",
    "DGS2": "2년 국채금리",
    "T10Y2Y": "10년-2년 스프레드",
    "FEDFUNDS": "연방기금금리",
    "CPIAUCSL": "CPI",
    "UNRATE": "실업률",
    "GDPC1": "실질 GDP",
    "DTWEXBGS": "달러인덱스(광의)",
    "DCOILWTICO": "WTI 유가",
    "BAMLH0A0HYM2": "하이일드 스프레드",
}


def fred_series(series_id: str, tail: int = 8, years: int = 3) -> dict:
    """키 불필요 CSV 엔드포인트. Tier 1 (세인트루이스 연준).

    cosd(시작일)를 반드시 붙인다 — 없으면 1960년대부터 전 구간을 내려받아 타임아웃 난다.
    """
    from datetime import date, timedelta
    start = (date.today() - timedelta(days=365 * years)).isoformat()
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    text = http_get(url, as_json=False, timeout=30)
    rows = []
    for line in text.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        date, val = parts[0].strip(), parts[1].strip()
        if val in ("", "."):
            continue
        try:
            rows.append({"date": date, "value": float(val)})
        except ValueError:
            continue
    if not rows:
        raise FetchError("invalid-payload", f"FRED {series_id}: 값 없음")
    return {
        "seriesId": series_id,
        "label": FRED_SERIES.get(series_id, series_id),
        "latest": rows[-1],
        "history": rows[-tail:],
        "sourceUrl": url,
    }


# ------------------------------------------------- Toss 증권 (선택 — 자격증명 있을 때만)

TOSS_BASE = os.environ.get("TOSS_API_BASE_URL", "https://openapi.tossinvest.com")
_toss_token: dict = {}


def toss_available() -> bool:
    return bool(os.environ.get("TOSS_CLIENT_ID") or os.environ.get("TOSSINVEST_CLIENT_ID"))


def _toss_token_get() -> str:
    import time
    if _toss_token.get("value") and _toss_token.get("expires", 0) > time.time() + 60:
        return _toss_token["value"]
    cid = os.environ.get("TOSS_CLIENT_ID") or os.environ.get("TOSSINVEST_CLIENT_ID")
    secret = os.environ.get("TOSS_CLIENT_SECRET") or os.environ.get("TOSSINVEST_CLIENT_SECRET")
    if not cid or not secret:
        raise FetchError("configuration-required", "TOSS_CLIENT_ID/SECRET 환경변수 없음")
    import urllib.request
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": cid, "client_secret": secret,
    }).encode()
    req = urllib.request.Request(
        f"{TOSS_BASE}/oauth2/token", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 폴백으로 넘긴다
        raise FetchError("authentication-failed", f"Toss 토큰 발급 실패: {exc}")
    _toss_token["value"] = payload.get("access_token")
    _toss_token["expires"] = time.time() + int(payload.get("expires_in", 600))
    if not _toss_token["value"]:
        raise FetchError("authentication-failed", "Toss 토큰 응답에 access_token 없음")
    return _toss_token["value"]


def toss_universe(market: str) -> list[dict]:
    """종목 마스터. 한국 회사명 → 티커 해석의 검증된 경로 (삼성전자 → 005930)."""
    cached = read_cache("tickermap", f"_toss_{market}")
    if cached and cached.get("ok"):
        return cached["data"]
    token = _toss_token_get()
    url = f"{TOSS_BASE}/api/v1/stocks/all?market={market}&status=ACTIVE"
    payload = http_get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    rows = []
    for item in (payload or {}).get("stocks") or (payload or {}).get("data") or []:
        sym = item.get("symbol") or item.get("code")
        if not sym:
            continue
        rows.append({"ticker": sym, "name": item.get("name") or item.get("korName"),
                     "market": market, "source": "toss"})
    write_cache("tickermap", f"_toss_{market}", {"ok": True, "data": rows, "meta": {"source": "toss"}})
    return rows


def toss_candles(symbol: str, count: int = 200) -> dict:
    """일봉 (수정주가). 최대 200봉 — MA200에는 부족하므로 Yahoo 폴백 전용."""
    token = _toss_token_get()
    url = (f"{TOSS_BASE}/api/v1/candles?symbol={urllib.parse.quote(symbol)}"
           f"&interval=1d&count={count}&adjusted=true")
    payload = http_get(url, headers={"Authorization": f"Bearer {token}"}, timeout=20)
    bars = []
    for c in (payload or {}).get("candles") or (payload or {}).get("data") or []:
        close = c.get("close")
        if close is None:
            continue
        bars.append({
            "date": (c.get("date") or c.get("tradingDate") or "")[:10],
            "open": c.get("open"), "high": c.get("high"), "low": c.get("low"),
            "close": close, "adjClose": close, "volume": c.get("volume"),
        })
    bars.sort(key=lambda b: b["date"])
    if not bars:
        raise FetchError("insufficient-history", f"Toss {symbol}: 봉 데이터 없음")
    return {"symbol": symbol, "bars": bars, "price": bars[-1]["close"], "sourceUrl": url}
