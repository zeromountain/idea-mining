# stock-analyst

주식 종목을 **판단 절차를 강제하는 순서**로 분석하는 Claude Code 플러그인.
시장 데이터 → 기업/재무 분석 → 밸류에이션 → Bull/Bear 논쟁 → Risk → Investment Committee →
리포트 순으로 진행하고, 결과를 `~/stock-research/`에 축적한다.

## 왜 이렇게 만들었나

LLM에게 "엔비디아 지금 사도 될까?"라고 물으면 세 가지가 문제가 된다.

1. **주가와 재무를 기억에서 지어낸다.** 그럴듯한 숫자라서 검증 없이는 구분이 안 된다.
2. **Bull Case만 만든다.** 반론을 요청하지 않으면 반론이 나오지 않고, 요청해도 이미 낙관적
   서술을 읽은 뒤라 형식적인 반론이 나온다.
3. **좋은 회사를 좋은 투자와 혼동한다.** 훌륭한 기업이면 가격과 무관하게 BUY가 나온다.

이 플러그인의 설계는 그 셋을 구조로 막는다.

- **숫자는 스크립트, 판단은 에이전트.** 비율·DCF·점수는 파이썬이 계산하고 LLM은 해석만 한다.
  에이전트가 인용한 수치는 `validate.py`가 원본과 대조해 어긋나면 `CONFLICTED DATA`로 표시한다.
- **Bear 격리.** Bear/Risk 에이전트에는 원본 데이터와 Bull의 주장만 주고 긍정적 서술은 주지 않는다.
  설득당한 반론은 반론이 아니다.
- **밸류에이션 점수를 사업 품질과 분리.** Executive Summary에 두 점수를 나란히 놓는다.
  Business Quality 9.2 / Valuation 6.0 이면 종합은 ACCUMULATE지 STRONG BUY가 아니다.

## 설치

```
/plugin marketplace add zeromountain/idea-mining
/plugin install stock-analyst@my-plugins
```

설치 식별자(`@` 뒤)는 저장소 이름이 아니라 `marketplace.json`의 `name`인 **`my-plugins`**다.

로컬 테스트:
```bash
cc --plugin-dir ~/claude-plugins/plugins/stock-analyst
```

## 사용법

스킬은 자동으로 트리거된다 — "엔비디아 지금 투자해도 될까?", "삼성전자 적정가치 봐줘",
"테슬라 오늘 왜 떨어졌어?" 같은 말이면 된다. 명시적으로 부르려면 슬래시 커맨드를 쓴다.

| 커맨드 | 하는 일 | 서브에이전트 |
|---|---|---:|
| `/stock-analyst:quick NVDA` | 6블록 요약 | 1 |
| `/stock-analyst:deep NVDA --peers AMD,AVGO` | 전체 파이프라인 + 리포트 저장 | 8~9 |
| `/stock-analyst:valuation NVDA` | 3중 비교 + DCF | 1 |
| `/stock-analyst:technical NVDA` | 추세·지지·저항 | 1 |
| `/stock-analyst:earnings NVDA` | 실적의 질 + 가이던스 | 2 |
| `/stock-analyst:compare NVDA AMD AVGO` | 동일 기준 비교표 | N+1 |
| `/stock-analyst:portfolio VOO 40 QQQ 30 NVDA 15 PLTR 15` | 집중도·실질 중복 | N+1 |
| `/stock-analyst:watchlist add NVDA` | 관심 종목 관리 | 0 |
| `/stock-analyst:recheck NVDA` | 저장된 Thesis 재검증 | 1 |

## 데이터

API 키 없이 동작한다.

| 데이터 | 소스 | Tier |
|---|---|---|
| 시세·OHLCV (미국·한국·ETF, 10년) | Yahoo chart v8 | 3 |
| 미국 재무제표·공시 | SEC EDGAR XBRL | **1** |
| 한국 재무제표·공시 | DART OpenAPI | **1** |
| 거시지표 | FRED | **1** |
| 컨센서스·뉴스·촉매 | WebSearch / WebFetch | 1~3 |
| 한국 시세 폴백·회사명 해석 | Toss Open API (선택) | 3 |

환경변수: **`DART_API_KEY`** (한국 재무제표·공시 — [opendart.fss.or.kr](https://opendart.fss.or.kr)에서
개인은 즉시 무료 발급, 하루 20,000건). 없으면 한국 재무는 WebSearch 폴백으로 내려간다.
선택: `TOSS_CLIENT_ID`/`TOSS_CLIENT_SECRET` (한국 회사명 해석 보강),
`SEC_USER_AGENT` (SEC가 연락처 포함 UA를 요구한다), `STOCK_RESEARCH_HOME` (저장 위치 변경).

한국 종목은 **ROE를 지배주주 기준**으로, **시가총액을 보통주 유통주식수 기준**으로 계산한다.
연결/별도(CFS/OFS)와 결산월도 자동 처리한다 — 자세한 내용은 `references/korea.md`.

## 산출물

리포트는 **HTML 아티팩트로 발행**되어 링크로 열린다. 판정·점수 막대·시나리오 축이 한 화면에 들어오고,
본문은 접었다 펼 수 있으며 라이트/다크 모두 대응한다. 대화창에는 12줄 요약만 나온다.

```
~/stock-research/
├── INDEX.md                                       분석 이력 (아티팩트 링크 포함)
├── reports/<TICKER>/<날짜>-<모드>.json             렌더러 입력 (다시 렌더할 수 있다)
├── reports/<TICKER>/<날짜>-<모드>.md               마크다운 보관본
├── reports/<TICKER>/<날짜>-<모드>.html             아티팩트로 발행되는 페이지
├── thesis/<TICKER>.json                           투자 논리 + 무효화 조건 + artifactUrl
├── watchlist.json  portfolio.json  profile.json
└── cache/<TICKER>/*.json                          원본 데이터 + 출처 메타데이터
```

**리포트를 에이전트가 조립하지 않는다.** 판단만 `report.json`에 담고 `scripts/render.py`가
HTML·마크다운·터미널 요약을 만든다. 그래서 매번 같은 모양이 나오고, 통화·부호·자릿수가 한 곳에서
통일되며, quick 모드가 deep 크기로 부푸는 일이 없다 (모드별 섹션·본문·리스크·출처 상한을 렌더러가 강제).

가장 중요한 산출물은 리포트가 아니라 **`thesis/<TICKER>.json`의 `invalidationConditions`**다.
"무엇이 사실이면 내 판단이 틀린 것인가"를 미리 적어두면, 다음 분기에
`/stock-analyst:recheck`로 전체 재분석 없이 그 조건만 확인할 수 있다.

## 개발

```bash
python3 -m unittest discover -s scripts/tests -t .        # 62개, 네트워크 없음
python3 scripts/render.py html scripts/tests/fixtures/005930-quick.json -o /tmp/r.html
python3 -m json.tool .claude-plugin/plugin.json
python3 scripts/fetch.py bundle NVDA                      # 실데이터 스모크
```

계산 로직을 바꿀 때는 `scripts/tests/test_core.py`의 회귀 테스트를 먼저 본다.
특히 두 회귀 테스트를 지우지 마세요.
- `TestMetrics` — **회계연도가 어긋난 값끼리 나누는 버그**. 기업이 XBRL 태그를 바꾸면 옛 태그에
  오래된 값만 남아, 매출총이익률이 570%로 나온 적이 있다.
- `TestDart` — **자본변동표(SCE) 오염**. DART는 같은 IFRS 계정 ID를 여러 재무제표에 중복 출력해서,
  필터 없이 읽으면 삼성전자 자본총계가 436조가 아니라 4.4조로 나온다.
- `TestRender.test_no_color_defined_only_inside_a_theme_block` — 다크 블록에만 정의된 색이 있으면
  뷰어의 시스템 기본 테마에서 글자색이 통째로 빈다. 아티팩트에서 가장 흔한 버그다.
