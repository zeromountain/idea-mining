---
name: stock-analyst
description: 주식 종목을 분석하고 투자 판단을 돕는다. 사용자가 특정 종목이나 티커를 언급하며 "분석해줘", "지금 사도 될까", "적정가치", "왜 떨어졌어", "비교해줘", "내 포트폴리오 봐줘", "실적 어땠어", "밸류에이션", "목표주가" 같은 말을 하면 사용할 것 — 종목명(엔비디아, 삼성전자)이나 티커(NVDA, 005930, VOO)가 등장하고 그것에 대한 판단을 원하는 맥락이면 트리거한다. 미국·한국 주식과 ETF를 지원하며, 시장 데이터 수집 → 기업/재무 분석 → 밸류에이션 → Bull/Bear 논쟁 → Risk → Investment Committee 순서로 진행하고 리포트를 ~/stock-research/에 저장한다. 과거 분석을 다시 보거나("전에 NVDA 뭐라고 했지"), 저장된 투자 Thesis가 아직 유효한지 재검증하는 요청("그때 논리 아직 맞아?")에도 사용한다. 단순 시세 조회나 이미 정해진 매매의 실행 방법 질문에는 쓰지 않는다.
---

# 주식 분석·투자 리서치 (stock-analyst)

이 스킬의 목적은 "사라/팔아라"를 말하는 것이 아니라 **판단 절차를 강제하는 것**이다. 좋은 회사와
좋은 가격은 다른 문제이고, 반론을 거치지 않은 결론은 결론이 아니다. 그래서 매번 같은 순서를 밟고,
결과를 `~/stock-research/`에 남겨 다음 분기에 다시 검증한다.

## 절대 규칙

1. **숫자를 지어내지 않는다.** 현재 주가·시가총액·PER·실적·가이던스·컨센서스·뉴스·금리는
   모델 기억에서 꺼내지 않는다. 반드시 `fetch.py` 또는 WebSearch로 조회한다.
2. **계산은 스크립트가 한다.** 비율·DCF·점수를 대화 중에 암산하지 않는다.
   `fetch.py` / `dcf.py` / `score.py`가 이미 계산해 둔 값을 읽어 쓴다.
3. **Bear Case를 생략하지 않는다.** deep 분석에서 Bull만 내놓는 것은 실패다.
4. **BUY는 기본값이 아니다.** 데이터가 부족하면 `INSUFFICIENT DATA`가 정당한 답이다.
5. **모든 질의에 모든 에이전트를 돌리지 않는다.** 모드에 맞는 최소 경로만 실행한다.

## 모드

| 모드 | 트리거 | 실행 |
|---|---|---|
| `quick` | "간단히", "어때?", 기본값 | 데이터 수집 → 통합 분석 1콜 |
| `deep` | "분석해줘", "지금 투자해도 될까", "제대로/깊게" | 전체 DAG (아래) |
| `valuation` | "비싼가", "적정가치", "목표주가" | Valuation 단독 |
| `technical` | "차트", "지금 들어가도 되나", "지지선" | Technical 단독 |
| `earnings` | "실적 어땠어", "가이던스" | News + Financial |
| `news` | "무슨 일 있었어" | News 단독 |
| `market_movement` | "왜 떨어졌어/올랐어" | 데이터 + News + Macro |
| `compare` | "A랑 B 중 뭐가 나아" | 종목별 quick 병렬 → 비교 |
| `portfolio` | 보유 비중 제시 | 종목별 quick 병렬 → 포트폴리오 |
| `recheck` | "그때 논리 아직 맞아?" | 저장된 Thesis의 무효화 조건만 재확인 |

모호하면 `quick`으로 시작하고, 결과를 보여준 뒤 deep 분석을 제안한다. 처음부터 8개 에이전트를
돌리는 것보다 실제 사용 패턴에 맞는다.

---

## 워크플로

### 준비: 스크립트 경로 확인 (세션당 한 번)

이 스킬의 계산 스크립트는 플러그인 안에 있다. 설치 위치가 개발 저장소일 수도, 마켓플레이스
캐시일 수도 있으므로 **처음 한 번 경로를 확인하고 그 절대경로를 이후 모든 명령에 쓴다.**

```bash
find ~/claude-plugins/plugins ~/.claude/plugins/cache -maxdepth 5 -type d -path '*stock-analyst*/scripts' 2>/dev/null | head -1
```

(쉘이 zsh일 수 있으므로 glob 대신 `find`를 쓴다 — 매칭 실패 시 zsh는 명령 전체를 중단시킨다.)

이 값을 `$S`로 부른다. 아래 명령의 `$S`는 **실제 절대경로로 치환해서** 실행한다
(쉘 변수는 Bash 호출 사이에 유지되지 않는다). 서브에이전트를 띄울 때도 이 절대경로를 프롬프트에 함께 넘긴다.

경로가 안 나오면 스크립트 없이 진행할 수 없다 — 사용자에게 플러그인 설치 상태를 확인하도록 알린다.

### 0단계: 티커 해석

```bash
python3 $S/fetch.py resolve "엔비디아"
```

`otherCandidates`가 있고 사용자 의도가 모호하면 `AskUserQuestion`으로 확인한다.
해석 실패 시 WebSearch로 티커를 찾아 다시 시도한다.

### 1단계: 데이터 수집 (LLM 없이)

```bash
python3 $S/fetch.py bundle <TICKER> [--peers AMD,AVGO]
```

반환된 `sections`의 `cachePath`가 이후 모든 에이전트의 입력이다.
`unavailable`에 오른 영역은 `stock-data-research` 에이전트로 보완한다.
Provider가 실패해도 전체를 중단하지 않는다 — 그 영역만 `분석 불가`로 표기하고 진행한다.

자세한 Provider 계층·실패 대응·한국 종목 한계는 `references/data-sources.md`를 읽는다.

### 2단계: deep 모드 DAG

**1단 (병렬)** — 한 메시지에서 5개 서브에이전트를 동시에 띄운다:
`stock-fundamental` · `stock-financial` · `stock-technical` · `stock-news` · `stock-macro`

**검증** — 각 출력의 마지막 ```json 블록을 파일로 저장한 뒤:

```bash
python3 $S/validate.py --agent financial out.json \
  --ref ~/stock-research/cache/<TICKER>/financials.json
```

스키마 위반이면 `repairInstruction`을 그대로 **같은 에이전트에 1회만** 되돌려 재시도한다.
두 번째도 실패하면 그 섹션을 `unavailable`로 두고 진행한다.
`CONFLICTED DATA`가 뜨면 리포트에 그대로 표기하고, 신뢰도 높은 Tier를 우선 채택한다.

**2단 (병렬)** — `stock-valuation` · `stock-bull` · `stock-bear` · `stock-risk`

> **Bear와 Risk에는 1단의 긍정적 서술을 넘기지 않는다.** 원본 캐시 경로와 Bull의 주장만 준다.
> 설득당한 반론은 반론이 아니다. 이 격리가 이 스킬에서 가장 중요한 장치다.

**3단** — `stock-committee`. 여기서만 모든 출력을 본다.

각 단계가 끝날 때마다 사용자에게 진행 상황을 한 줄로 알린다 (`✓ 재무 분석 완료 / ● 밸류에이션 진행 중`).

### 3단계: 점수와 등급

Committee가 `score.py`를 실행한다. 산출된 `proposedRating`은 **제안일 뿐이며**,
Committee가 확인하거나 하향하고 그 이유를 문장으로 남긴다.
가중치·밴드·하향 트리거·Confidence 산식은 `references/scoring.md`.

### 4단계: 리포트 — 손으로 조립하지 않는다

마크다운을 직접 쓰지 않는다. 판단을 **report JSON** 하나에 담고 렌더러에 넘긴다.
배치·길이·숫자 포맷은 렌더러가 정하므로 매번 같은 모양이 나오고, quick이 deep 크기로 부풀지 않는다.
스키마와 모드별 상한은 `references/templates.md`.

```bash
R=~/stock-research/reports/<TICKER>/<YYYY-MM-DD>-<mode>
python3 $S/validate.py --agent report report.json   # 먼저 검증
python3 $S/render.py md    report.json -o $R.md
python3 $S/render.py html  report.json -o $R.html
python3 $S/render.py brief report.json              # 대화창 출력용
```

`report.json`도 같은 경로에 함께 남긴다 (나중에 다시 렌더할 수 있어야 한다).

**그다음 HTML을 아티팩트로 발행한다.** `Artifact` 도구에 `$R.html` 경로와
favicon `📊`를 넘기고, 한 문장 `description`을 붙인다. 페이지 디자인은 렌더러에 이미 고정되어
있으므로 HTML을 손으로 고치거나 다시 디자인하지 않는다.

같은 종목·날짜·모드를 다시 돌리면 같은 파일 경로를 쓰므로 같은 아티팩트 URL로 재발행된다.

마지막으로 사용자에게는 **`render.py brief` 출력(12줄 이내) + 아티팩트 링크 + 파일 경로**만 보여준다.
리포트 전문을 대화창에 다시 붙여넣지 않는다 — 그게 지금까지 결과물이 안 읽히던 이유다.

### 5단계: 기억

deep 분석은 `~/stock-research/thesis/<TICKER>.json`에 투자 논리와 **무효화 조건**을 저장하고
`INDEX.md`에 한 줄 추가한다. 절차는 `references/memory.md`.

---

## 참조 파일

필요할 때만 읽는다 (항상 읽지 않는다):

- `references/data-sources.md` — Provider 계층, 실패 대응, 한국 종목 데이터 한계
- `references/scoring.md` — 7영역 가중치, Rating 밴드, 하향 트리거, Confidence
- `references/valuation.md` — 3중 비교, DCF 절차, 시나리오 설계
- `references/korea.md` — 한국 종목 전용 규칙 (지배주주순이익, 우선주, 지주사, 공시 시차)
- `references/portfolio.md` — ETF·포트폴리오 분석, 투자성향 없을 때의 금지선
- `references/memory.md` — 저장 구조, Thesis 스키마, recheck 절차
- `references/templates.md` — report JSON 스키마, 모드별 상한, FACT/ESTIMATE 표기

## 하지 않을 것 (문서 §70)

- 현재 가격을 모델 기억에서 가져오기
- 출처 없는 재무 숫자 생성
- Bull Case만 생성
- BUY를 기본 등급으로 사용
- DCF 결과를 정답처럼 제시
- 기술적 분석만으로 장기투자 판단
- 뉴스 제목만 보고 Thesis 결정
- 사용자 투자 성향 없이 구체적 투자 비중 제시

## 면책

모든 리포트 말미에 고정한다: 이 분석은 투자 판단 참고자료이며 투자 권유가 아니다.
분석 시점의 주가와 데이터 기준일을 함께 명시한다.
