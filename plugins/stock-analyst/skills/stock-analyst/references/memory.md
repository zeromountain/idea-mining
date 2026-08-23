# 저장 구조와 재검증

## 디렉터리

```
~/stock-research/
├── INDEX.md                                  분석 이력 한 줄 요약
├── profile.json                              투자 성향 (없으면 비중 추천 금지)
├── watchlist.json
├── portfolio.json
├── cache/<TICKER>/<type>.json                TTL 기반 원본 (직접 편집하지 않는다)
├── reports/<TICKER>/<YYYY-MM-DD>-<mode>.{json,md,html}   리포트 3종
├── thesis/<TICKER>.json
└── runs/<YYYY-MM-DD>-<TICKER>-<mode>.jsonl   에이전트 실행 로그
```

첫 사용 시 `mkdir -p`로 만든다.

## INDEX.md 한 줄 형식

```markdown
| 날짜 | 티커 | 모드 | Rating | 점수 | 당시 주가 | 리포트 |
|---|---|---|---|---:|---:|---|
| 2026-08-22 | NVDA | deep | ACCUMULATE | 7.8 | $214.72 | [아티팩트](https://claude.ai/...) · [md](reports/NVDA/2026-08-22-deep.md) |
```

## thesis/<TICKER>.json (문서 §35)

```json
{
  "ticker": "NVDA",
  "createdAt": "2026-08-22",
  "priceAtAnalysis": 214.72,
  "rating": "ACCUMULATE",
  "score": 7.8,
  "confidence": "MEDIUM",
  "thesis": ["..."],
  "catalysts": ["..."],
  "risks": ["..."],
  "invalidationConditions": ["데이터센터 매출 YoY가 2분기 연속 15% 미만"],
  "metricsToMonitor": ["데이터센터 매출 YoY", "매출총이익률", "CUDA 대비 ASIC 채택률"],
  "reportPath": "reports/NVDA/2026-08-22-deep.md",
  "artifactUrl": "https://claude.ai/...",
  "rechecks": []
}
```

`invalidationConditions`는 리포트의 "What Would Change My Mind?"와 **같은 내용**이다.
따로 쓰지 않는다 — 리포트와 메모리가 같은 필드를 공유하는 것이 이 설계의 요점이다.

무효화 조건은 **관측 가능해야 한다.** "성장이 둔화되면"은 조건이 아니다.
숫자·기간·출처가 들어가야 조건이다.

## recheck 절차 (문서 §36)

`/stock-analyst:recheck NVDA` 또는 "그때 논리 아직 맞아?"에서:

1. `thesis/<TICKER>.json`을 읽는다. 없으면 deep 분석을 먼저 제안한다.
2. **전체 재분석을 하지 않는다.** `invalidationConditions`와 `metricsToMonitor`만 확인한다.
   - `fetch.py quote` + `financials`로 지표 갱신
   - 그 사이 실적발표·주요 공시가 있었는지 `filings` + WebSearch
3. 조건별로 판정한다: 충족(무효화 발생) / 근접 / 미충족.
4. 종합 판정: `VALID` / `WEAKENING` / `BROKEN` / `IMPROVING`
5. 결과를 `thesis/<TICKER>.json`에 `rechecks[]` 배열로 덧붙인다 (덮어쓰지 않는다 —
   판단이 언제 어떻게 바뀌었는지가 나중에 가장 중요한 정보다).
6. `BROKEN`이면 전체 재분석을 제안한다.

## runs 로그 (문서 §57, §65)

에이전트 실행마다 한 줄 JSON을 남긴다: 에이전트명 · 시작·종료 시각 · 성공 여부 ·
스키마 검증 결과 · 사용한 데이터 소스. 나중에 어느 에이전트가 자주 실패하는지 보기 위한 것이다.
