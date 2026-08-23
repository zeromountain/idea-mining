# 데이터 소스 계층

원칙: **수치는 API, 정성 정보는 WebSearch.** 모든 데이터에는 출처·기준일·신뢰도를 붙인다 (문서 §38).

## Provider 표 (2026-08-22 실측 확인)

| 데이터 | Primary | Fallback | Tier |
|---|---|---|---|
| 미국·한국·ETF 시세, 10년 OHLCV | Yahoo chart v8 | Toss candles (KR, 200봉 한계) | 3 |
| 미국 재무제표 | SEC EDGAR XBRL `companyfacts` | — | **1** |
| 미국 공시 (10-K/Q/8-K) | SEC `submissions` | — | **1** |
| 티커↔CIK↔회사명 | SEC `company_tickers.json` | Yahoo search, 내장 별칭표 | 1 |
| 거시지표 | FRED CSV (키 불필요) | — | **1** |
| 컨센서스·Forward P/E·실적발표일 | **WebSearch** | — | 2~3 |
| 한국 재무제표 | **DART OpenAPI** `fnlttSinglAcntAll` | WebSearch (키 없을 때) | **1** |
| 한국 공시 | **DART OpenAPI** `list` | WebSearch | **1** |
| 뉴스·촉매 | WebSearch / WebFetch | — | 1~3 |
| ETF 보유종목·보수율 | 운용사 페이지 WebFetch | WebSearch | 2 |

## 스크립트 사용법

`$S`는 SKILL.md의 "준비" 단계에서 확인한 스크립트 디렉터리 절대경로다. 실제 경로로 치환해 실행한다.

```bash
python3 $S/fetch.py resolve "엔비디아"        # 종목명·티커 해석
python3 $S/fetch.py bundle NVDA --peers AMD,AVGO   # deep 모드 일괄 수집
python3 $S/fetch.py quote NVDA                # 시세 + 기간별 수익률
python3 $S/fetch.py indicators NVDA           # 기술적 지표
python3 $S/fetch.py financials NVDA           # SEC XBRL → 정규화 재무제표 + 비율
python3 $S/fetch.py filings NVDA              # 최근 공시
python3 $S/fetch.py macro                     # FRED 10개 계열
python3 $S/fetch.py financials 005930.KS      # 한국: DART (연결 기준)
python3 $S/fetch.py peers NVDA --peers AMD,AVGO
```

캐시는 `~/stock-research/cache/<TICKER>/<type>.json`. TTL(문서 §39):
price 5분 · technical 15분 · news 1시간 · financials 7일 · macro 1일 · 티커맵 30일.
`--no-cache`로 무시한다.

## 실패했을 때 (문서 §67)

`fetch.py`는 예외를 던지지 않고 `{"ok": false, "error": {...}}`를 돌려준다.
**한 Provider 실패로 전체 분석을 중단하지 않는다.** 해당 섹션만 `분석 불가`로 표기하고 나머지를 진행하며,
리포트 Executive Summary에 어느 영역이 비었는지 명시한다.

`error.code`별 대응:
- `symbol-not-found` → WebSearch로 정확한 티커 확인 후 재시도
- `rate-limited` / `provider-timeout` → 60초 뒤 1회 재시도, 그래도 실패면 WebSearch 대체
- `provider-unavailable` → WebSearch 대체, `confidence: low` 표기
- `insufficient-history` → 기술적 분석 생략, 사유 명시

## 출처 우선순위 (문서 §25)

Tier 1 SEC · 기업 IR · 거래소 · 정부 · 중앙은행
Tier 2 Reuters · Bloomberg · FT · WSJ
Tier 3 Morningstar · Yahoo Finance · MarketWatch · CNBC · Seeking Alpha
Tier 4 Reddit · X · YouTube · 블로그

**Tier 4는 사실 검증에 쓰지 않는다.** 시장 심리 서술에만 인용하고 반드시 Tier 4임을 밝힌다.
소스 간 수치가 다르면 둘 다 적고 `CONFLICTED DATA`로 표기한 뒤 상위 Tier를 채택한다.

## 알려진 한계

- **한국 재무제표**: DART OpenAPI로 Tier 1 조회된다(`DART_API_KEY` 필요, 하루 20,000건).
  6자리 종목코드가 아니라 8자리 `corp_code`로 조회하며 변환은 자동이다. 키가 없으면
  WebSearch 폴백 안내가 나온다. `references/korea.md` 참고.
- **DART 계정 중복**: 같은 IFRS 계정 ID가 여러 재무제표에 나온다. 특히 SCE(자본변동표)는
  자본총계·당기순이익을 구성요소별로 다시 내보내므로 필터 없이 읽으면 값이 통째로 틀린다.
  `dart.py`의 `FIELD_DIV`가 필드별 출처를 고정한다 — 이 필터를 지우지 않는다.
- **Toss**: 자격증명(`TOSS_CLIENT_ID`/`TOSS_CLIENT_SECRET`)이 있을 때만 동작하며 IP 허용목록 등록이
  필요하다. 일봉 200개 상한이라 MA200을 계산할 수 없어 시세 폴백 용도로만 쓴다.
- **Yahoo 429**: (IP, User-Agent) 버킷 단위로 걸린다. 스크립트가 UA를 자동 로테이션하지만
  연속 실패하면 잠시 뒤 재시도한다.
- **SEC 태그 변경**: 기업이 XBRL 태그를 바꾸면 옛 태그에 오래된 값만 남는다. 추출기가 "가장 최신까지
  보고된 태그"를 고르지만, `dataGaps`에 항목이 올라오면 그 항목이 걸린 비율은 해석하지 않는다.
