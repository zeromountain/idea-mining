#!/usr/bin/env python3
"""stock-analyst 데이터 수집 CLI (문서 §6~7, §38~43).

원칙: 이 스크립트는 **분석하지 않는다**. 원본에 가까운 데이터를 정규화해서
~/stock-research/cache/ 에 쓰고, 어디서 왔는지 메타데이터를 붙인다.
Provider가 실패하면 예외를 던지지 않고 ok:false 봉투를 돌려준다 (문서 §67).

  python3 fetch.py resolve "엔비디아"
  python3 fetch.py quote NVDA
  python3 fetch.py indicators NVDA
  python3 fetch.py financials NVDA
  python3 fetch.py filings NVDA
  python3 fetch.py macro
  python3 fetch.py peers NVDA --peers AMD,AVGO
  python3 fetch.py bundle NVDA          # deep 모드용 일괄 수집
"""
from __future__ import annotations

import argparse
import json
import re
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

import dart
import indicators as ind
import metrics as met
import providers as prov
from common import (ROOT, FetchError, emit, envelope, failure, read_cache,
                    write_cache)

# 한국어로 흔히 부르는 미국 종목 별칭. Yahoo 검색이 429일 때의 결정론적 1차 경로.
ALIASES = {
    "엔비디아": "NVDA", "애플": "AAPL", "테슬라": "TSLA", "마이크로소프트": "MSFT",
    "구글": "GOOGL", "알파벳": "GOOGL", "아마존": "AMZN", "메타": "META",
    "팔란티어": "PLTR", "브로드컴": "AVGO", "인텔": "INTC", "넷플릭스": "NFLX",
    "코카콜라": "KO", "버크셔": "BRK-B", "제이피모건": "JPM", "일라이릴리": "LLY",
    "마이크론": "MU", "퀄컴": "QCOM", "티에스엠씨": "TSM", "티에스엠": "TSM",
    "슈퍼마이크로": "SMCI", "코스트코": "COST", "비자": "V", "월마트": "WMT",
    "삼성전자": "005930.KS", "삼성전자우": "005935.KS", "에스케이하이닉스": "000660.KS",
    "sk하이닉스": "000660.KS", "네이버": "035420.KS", "카카오": "035720.KS",
    "현대차": "005380.KS", "기아": "000270.KS", "셀트리온": "068270.KS",
    "삼성바이오로직스": "207940.KS", "포스코홀딩스": "005490.KS", "엘지에너지솔루션": "373220.KS",
}

KR_SUFFIXES = (".KS", ".KQ")


# ------------------------------------------------------------------- resolve

def _market_of(ticker: str) -> str:
    if ticker.upper().endswith(KR_SUFFIXES):
        return "KR"
    return "US"


def _try_kr(code: str) -> dict | None:
    for suffix in KR_SUFFIXES:
        sym = f"{code}{suffix}"
        try:
            q = prov.yahoo_chart(sym, "5d")
        except FetchError:
            continue
        if q.get("price") is not None:
            return {"ticker": sym, "name": q.get("longName"), "market": "KR",
                    "currency": q.get("currency"), "exchange": q.get("exchange"),
                    "via": "yahoo-chart"}
    return None


def resolve(query: str) -> dict:
    q = (query or "").strip()
    if not q:
        return failure("resolve", q, "invalid-request", "빈 질의")

    tried = []
    alias = ALIASES.get(q.lower()) or ALIASES.get(q)
    if alias:
        q = alias
        tried.append("alias")

    # 1) 한국 6자리 코드
    if re.fullmatch(r"\d{6}", q):
        hit = _try_kr(q)
        tried.append("yahoo-chart(KR)")
        if hit:
            return envelope("resolve", hit["ticker"], "yahoo-chart",
                            "https://query1.finance.yahoo.com/v8/finance/chart/", hit, tier=3)

    upper = q.upper()

    # 2) 이미 KR 접미사가 붙은 티커
    if upper.endswith(KR_SUFFIXES):
        try:
            c = prov.yahoo_chart(upper, "5d")
            return envelope("resolve", upper, "yahoo-chart", c["sourceUrl"], {
                "ticker": upper, "name": c.get("longName"), "market": "KR",
                "currency": c.get("currency"), "exchange": c.get("exchange"), "via": "yahoo-chart",
            }, tier=3)
        except FetchError as exc:
            tried.append(f"yahoo-chart({exc.code})")

    # 3) 미국 티커 — SEC 매핑이 가장 신뢰도 높다 (Tier 1)
    if re.fullmatch(r"[A-Z][A-Z.\-]{0,5}", upper):
        try:
            m = prov.sec_ticker_map()
            entry = m["byTicker"].get(upper.replace("-", "-"))
            if entry:
                return envelope("resolve", upper, "sec-edgar",
                                "https://www.sec.gov/files/company_tickers.json", {
                                    "ticker": entry["ticker"], "name": entry["name"],
                                    "cik": entry["cik"], "market": "US", "via": "sec-ticker-map",
                                }, tier=1)
            tried.append("sec-ticker-map")
        except FetchError as exc:
            tried.append(f"sec-ticker-map({exc.code})")

    # 4) 영문 회사명 → SEC 회사명 매칭 (키 불필요, 오프라인 캐시로 동작)
    if re.search(r"[A-Za-z]", q):
        try:
            m = prov.sec_ticker_map()
            needle = re.sub(r"[^a-z0-9 ]", "", q.lower())
            cands = [e for e in m["all"] if needle and needle in e["name"].lower()]
            cands.sort(key=lambda e: len(e["name"]))
            if cands:
                best = cands[0]
                return envelope("resolve", best["ticker"], "sec-edgar",
                                "https://www.sec.gov/files/company_tickers.json", {
                                    "ticker": best["ticker"], "name": best["name"],
                                    "cik": best["cik"], "market": "US", "via": "sec-name-match",
                                    "otherCandidates": [c["ticker"] for c in cands[1:5]],
                                }, tier=1)
            tried.append("sec-name-match")
        except FetchError as exc:
            tried.append(f"sec-name-match({exc.code})")

    # 5) 한국 회사명 → Toss 종목 마스터 (자격증명 있을 때만)
    if prov.toss_available():
        try:
            rows = []
            for market in ("KOSPI", "KOSDAQ"):
                rows += prov.toss_universe(market)
            hits = [r for r in rows if r.get("name") and q in r["name"]]
            hits.sort(key=lambda r: len(r["name"]))
            if hits:
                code = hits[0]["ticker"]
                kr = _try_kr(re.sub(r"\D", "", code)[:6]) or {}
                return envelope("resolve", kr.get("ticker", code), "toss",
                                "https://openapi.tossinvest.com/api/v1/stocks/all", {
                                    "ticker": kr.get("ticker", code), "name": hits[0]["name"],
                                    "market": "KR", "krxCode": code, "via": "toss-universe",
                                    "otherCandidates": [h["ticker"] for h in hits[1:5]],
                                }, tier=3)
            tried.append("toss-universe")
        except FetchError as exc:
            tried.append(f"toss-universe({exc.code})")

    # 6) Yahoo 검색 (429가 잦아 마지막)
    try:
        hits = prov.yahoo_search(q)
        if hits:
            best = hits[0]
            return envelope("resolve", best["ticker"], "yahoo-search",
                            "https://query1.finance.yahoo.com/v1/finance/search", {
                                "ticker": best["ticker"], "name": best["name"],
                                "market": _market_of(best["ticker"]), "via": "yahoo-search",
                                "otherCandidates": [h["ticker"] for h in hits[1:5]],
                            }, confidence="medium", tier=3)
        tried.append("yahoo-search")
    except FetchError as exc:
        tried.append(f"yahoo-search({exc.code})")

    return failure("resolve", query, "symbol-not-found",
                   f"'{query}'를 티커로 해석하지 못했다. 웹 검색으로 티커를 확인한 뒤 다시 시도하라.", tried)


# --------------------------------------------------------------------- quote

def get_history(ticker: str, rng: str = "5y", use_cache: bool = True) -> dict:
    # 캐시 키에 기간을 포함한다. 넣지 않으면 1y 요청이 5y 캐시를 덮어써서
    # MA200과 1Y/3Y/5Y 수익률이 통째로 사라진다.
    key = f"{ticker}@{rng}"
    if use_cache:
        c = read_cache("history", key)
        if c:
            return c
    tried = []
    try:
        data = prov.yahoo_chart(ticker, rng)
        payload = envelope("history", ticker, "yahoo-chart", data["sourceUrl"], data,
                           tier=3, as_of=data["bars"][-1]["date"] if data["bars"] else None)
        write_cache("history", key, payload)
        return payload
    except FetchError as exc:
        tried.append(f"yahoo-chart({exc.code})")

    if _market_of(ticker) == "KR" and prov.toss_available():
        try:
            code = ticker.split(".")[0]
            data = prov.toss_candles(code)
            payload = envelope("history", ticker, "toss", data["sourceUrl"], data,
                               confidence="medium", tier=3)
            payload["meta"]["warning"] = "Toss는 최대 200봉만 준다 — MA200은 계산할 수 없다."
            write_cache("history", key, payload)
            return payload
        except FetchError as exc:
            tried.append(f"toss-candles({exc.code})")

    return failure("history", ticker, "provider-unavailable",
                   "시세 Provider를 모두 시도했으나 실패했다.", tried)


def get_quote(ticker: str, use_cache: bool = True) -> dict:
    c = read_cache("quote", ticker) if use_cache else None
    if c:
        return c
    hist = get_history(ticker, "10y", use_cache)
    if not hist.get("ok"):
        return failure("quote", ticker, hist["error"]["code"], hist["error"]["message"],
                       hist["error"].get("providersTried"))
    d = hist["data"]
    bars = d["bars"]
    rets = ind.returns(bars) if len(bars) > 2 else {}
    vols = [b["volume"] or 0 for b in bars]
    data = {
        "ticker": d.get("symbol") or ticker,
        "name": d.get("longName"),
        "currency": d.get("currency"),
        "exchange": d.get("exchange"),
        "instrumentType": d.get("instrumentType"),
        "price": d.get("price"),
        "previousClose": d.get("previousClose"),
        "changePct": (d["price"] / d["previousClose"] - 1) if d.get("price") and d.get("previousClose") else None,
        "week52High": d.get("fiftyTwoWeekHigh") or max((b["high"] for b in bars[-252:]), default=None),
        "week52Low": d.get("fiftyTwoWeekLow") or min((b["low"] for b in bars[-252:]), default=None),
        "volume": vols[-1] if vols else None,
        "avgVolume50": (sum(vols[-50:]) / min(50, len(vols))) if vols else None,
        "returns": rets,
        "lastBar": bars[-1]["date"] if bars else None,
    }
    payload = envelope("quote", ticker, hist["meta"]["source"], hist["meta"]["sourceUrl"], data,
                       tier=hist["meta"].get("tier", 3))
    write_cache("quote", ticker, payload)
    return payload


def get_indicators(ticker: str, use_cache: bool = True) -> dict:
    c = read_cache("indicators", ticker) if use_cache else None
    if c:
        return c
    hist = get_history(ticker, "10y", use_cache)
    if not hist.get("ok"):
        return failure("indicators", ticker, hist["error"]["code"], hist["error"]["message"])
    analysis = ind.analyze(hist["data"]["bars"])
    if not analysis.get("ok"):
        return failure("indicators", ticker, analysis["error"], analysis["message"])
    payload = envelope("indicators", ticker, hist["meta"]["source"],
                       hist["meta"]["sourceUrl"], analysis, tier=hist["meta"].get("tier", 3))
    write_cache("indicators", ticker, payload)
    return payload


# ---------------------------------------------------------------- financials

def _kr_financials(ticker: str, use_cache: bool = True) -> dict:
    """한국 종목: DART OpenAPI (Tier 1). 키가 없으면 WebSearch 폴백을 안내한다."""
    if not dart.available():
        return failure(
            "financials", ticker, "configuration-required",
            "DART_API_KEY가 없어 한국 재무제표를 조회할 수 없다. "
            "WebSearch로 매출·영업이익·순이익·FCF·부채를 수집하되 출처 2곳 이상을 교차확인하고 "
            "confidence를 low로 표기하라. 키는 https://opendart.fss.or.kr 에서 무료 발급된다.",
            ["dart(no-key)"])

    tried = []
    try:
        corp = dart.resolve_corp_code(ticker)
    except FetchError as exc:
        return failure("financials", ticker, exc.code, exc.message, ["dart-corpcode"])

    from datetime import date
    statements, used_year = None, None
    for year in (date.today().year - 1, date.today().year - 2):
        try:
            statements = dart.annual_statements(corp["corpCode"], year)
            used_year = year
            break
        except FetchError as exc:
            tried.append(f"dart({year}):{exc.code}")
    if statements is None:
        return failure("financials", ticker, "no-data",
                       "DART에서 최근 2개 사업연도 재무제표를 찾지 못했다", tried)

    shares = dart.shares_outstanding(corp["corpCode"], used_year) or {}
    quote = get_quote(ticker, use_cache)
    price = (quote.get("data") or {}).get("price")
    # 한국 법인세 실효세율 근사 (ASSUMPTION). ROIC 계산에만 쓰인다.
    m = met.compute_metrics(statements, price=price,
                            shares=shares.get("commonOutstanding"), tax_rate=0.22)

    data = {
        "ticker": ticker,
        "corpCode": corp["corpCode"],
        "entityName": corp["name"],
        "currency": (quote.get("data") or {}).get("currency", "KRW"),
        "fiscalYear": used_year,
        "fiscalMonth": statements.get("fiscalMonth"),
        "fsDiv": statements.get("fsDiv"),
        "shares": shares,
        "tagsUsed": statements["tagsUsed"],
        "annual": statements["annual"],
        "quarterly": {},
        **m,
    }
    data["notes"] = list(data.get("notes", [])) + [
        "K-IFRS 연결(CFS) 기준이다. 별도재무제표와 섞어 비교하지 않는다.",
        "시가총액은 보통주 유통주식수(발행 - 자기주식) 기준이며 우선주를 포함하지 않는다.",
        f"우선주 발행주식수: {shares.get('preferredIssued')} (시총 계산에서 제외됨)",
        "ROIC의 세율 22%는 한국 실효세율 근사값이다 (ASSUMPTION).",
    ]
    payload = envelope("financials", ticker, "dart-opendart",
                       "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                       data, tier=1, as_of=m["latest"].get("periodEnd"))
    write_cache("financials", ticker, payload)
    return payload


def get_financials(ticker: str, use_cache: bool = True) -> dict:
    c = read_cache("financials", ticker) if use_cache else None
    if c:
        return c
    if _market_of(ticker) == "KR":
        return _kr_financials(ticker, use_cache)

    r = resolve(ticker)
    cik = (r.get("data") or {}).get("cik")
    if not cik:
        return failure("financials", ticker, "symbol-not-found", "CIK를 찾지 못했다 (미국 상장사가 아닐 수 있다)")
    try:
        cf = prov.sec_companyfacts(cik)
    except FetchError as exc:
        return failure("financials", ticker, exc.code, exc.message, ["sec-companyfacts"])

    statements = met.extract_statements(cf)
    quote = get_quote(ticker, use_cache)
    price = (quote.get("data") or {}).get("price")
    m = met.compute_metrics(statements, price=price)
    data = {
        "ticker": ticker, "cik": cik,
        "entityName": cf.get("entityName"),
        "tagsUsed": statements["tagsUsed"],
        "annual": statements["annual"],
        "quarterly": statements["quarterly"],
        **m,
    }
    payload = envelope("financials", ticker, "sec-edgar-xbrl",
                       f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                       data, tier=1, as_of=m["latest"].get("periodEnd"))
    write_cache("financials", ticker, payload)
    return payload


def get_filings(ticker: str, use_cache: bool = True) -> dict:
    c = read_cache("filings", ticker) if use_cache else None
    if c:
        return c
    if _market_of(ticker) == "KR":
        if not dart.available():
            return failure("filings", ticker, "configuration-required",
                           "DART_API_KEY가 없다. 공시는 WebSearch로 대체하라.", ["dart(no-key)"])
        try:
            corp = dart.resolve_corp_code(ticker)
            rows = dart.recent_filings(corp["corpCode"])
        except FetchError as exc:
            return failure("filings", ticker, exc.code, exc.message, ["dart-list"])
        payload = envelope("filings", ticker, "dart-opendart",
                           "https://opendart.fss.or.kr/api/list.json",
                           {"filings": rows, "corpCode": corp["corpCode"]}, tier=1)
        write_cache("filings", ticker, payload)
        return payload
    r = resolve(ticker)
    cik = (r.get("data") or {}).get("cik")
    if not cik:
        return failure("filings", ticker, "symbol-not-found", "CIK를 찾지 못했다")
    try:
        rows = prov.sec_recent_filings(cik)
    except FetchError as exc:
        return failure("filings", ticker, exc.code, exc.message, ["sec-submissions"])
    payload = envelope("filings", ticker, "sec-edgar",
                       f"https://data.sec.gov/submissions/CIK{cik}.json", {"filings": rows}, tier=1)
    write_cache("filings", ticker, payload)
    return payload


# --------------------------------------------------------------------- macro

def get_macro(use_cache: bool = True) -> dict:
    c = read_cache("macro", "_global") if use_cache else None
    if c:
        return c
    out, failed = {}, []
    for sid in prov.FRED_SERIES:
        try:
            out[sid] = prov.fred_series(sid)
        except FetchError as exc:
            failed.append({"series": sid, "error": exc.code})
    if not out:
        return failure("macro", "_global", "provider-unavailable", "FRED 전 계열 실패", ["fred"])
    payload = envelope("macro", "_global", "fred",
                       "https://fred.stlouisfed.org/graph/fredgraph.csv", 
                       {"series": out, "failed": failed}, tier=1)
    write_cache("macro", "_global", payload)
    return payload


# --------------------------------------------------------------------- peers

def get_peers(ticker: str, peers: list[str], use_cache: bool = True) -> dict:
    rows = []
    for t in [ticker] + peers:
        q = get_quote(t, use_cache)
        f = get_financials(t, use_cache)
        fd = f.get("data") or {}
        rows.append({
            "ticker": t,
            "name": (q.get("data") or {}).get("name"),
            "price": (q.get("data") or {}).get("price"),
            "financialsAvailable": f.get("ok", False),
            "growth": fd.get("growth"),
            "profitability": fd.get("profitability"),
            "valuation": fd.get("valuation"),
            "note": None if f.get("ok") else (f.get("error") or {}).get("message"),
        })
    payload = envelope("peers", ticker, "composite", "-",
                       {"base": ticker, "peers": peers, "rows": rows,
                        "comparedFields": ["revenueYoY", "epsYoY", "grossMargin", "operatingMargin",
                                           "roic", "trailingPE", "evToRevenue", "fcfYield"]},
                       tier=1)
    write_cache("peers", ticker, payload)
    return payload


# -------------------------------------------------------------------- bundle

def bundle(ticker: str, peers: list[str], use_cache: bool = True) -> dict:
    r = resolve(ticker)
    resolved = (r.get("data") or {}).get("ticker", ticker) if r.get("ok") else ticker
    parts = {
        "resolve": r,
        "quote": get_quote(resolved, use_cache),
        "indicators": get_indicators(resolved, use_cache),
        "financials": get_financials(resolved, use_cache),
        "filings": get_filings(resolved, use_cache),
        "macro": get_macro(use_cache),
    }
    if peers:
        parts["peers"] = get_peers(resolved, peers, use_cache)

    summary = {}
    for name, p in parts.items():
        summary[name] = {
            "ok": p.get("ok", False),
            "cachePath": str(ROOT / "cache" / resolved.upper() / f"{name}.json")
            if name not in ("resolve", "macro") else None,
            "source": (p.get("meta") or {}).get("source"),
            "error": (p.get("error") or {}).get("message"),
        }
    summary["macro"]["cachePath"] = str(ROOT / "cache" / "_GLOBAL" / "macro.json")
    summary["indicators"]["cachePath"] = str(ROOT / "cache" / resolved.upper() / "indicators.json")

    return {
        "ok": True,
        "ticker": resolved,
        "sections": summary,
        "unavailable": [k for k, v in summary.items() if not v["ok"]],
        "note": ("에이전트에게는 이 요약과 cachePath만 넘긴다. 원본 JSON을 프롬프트에 "
                 "붙여넣지 않는다 (문서 §49)."),
    }


# ----------------------------------------------------------------------- CLI

def main() -> int:
    ap = argparse.ArgumentParser(description="stock-analyst 데이터 수집기")
    ap.add_argument("command", choices=["resolve", "quote", "history", "indicators",
                                        "financials", "filings", "macro", "peers", "bundle"])
    ap.add_argument("target", nargs="?", default="")
    ap.add_argument("--range", default="5y")
    ap.add_argument("--peers", default="", help="쉼표로 구분한 비교 대상 티커")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    (ROOT / "cache").mkdir(parents=True, exist_ok=True)
    use_cache = not args.no_cache
    peers = [p.strip().upper() for p in args.peers.split(",") if p.strip()]
    cmd, target = args.command, args.target

    if cmd == "macro":
        emit(get_macro(use_cache))
        return 0
    if not target:
        print(f"'{cmd}' 명령에는 종목이 필요하다", file=sys.stderr)
        return 2

    if cmd == "resolve":
        emit(resolve(target))
        return 0

    r = resolve(target)
    ticker = (r.get("data") or {}).get("ticker", target.upper()) if r.get("ok") else target.upper()

    if cmd == "quote":
        emit(get_quote(ticker, use_cache))
    elif cmd == "history":
        emit(get_history(ticker, args.range, use_cache))
    elif cmd == "indicators":
        emit(get_indicators(ticker, use_cache))
    elif cmd == "financials":
        emit(get_financials(ticker, use_cache))
    elif cmd == "filings":
        emit(get_filings(ticker, use_cache))
    elif cmd == "peers":
        emit(get_peers(ticker, peers, use_cache))
    elif cmd == "bundle":
        emit(bundle(ticker, peers, use_cache))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
