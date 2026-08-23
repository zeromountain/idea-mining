# 리포트 산출 — report JSON과 렌더러

**마크다운을 손으로 조립하지 않는다.** 판단을 `report.json`에 담고 `render.py`에 넘기면
HTML·마크다운·터미널 요약이 한 번에 나온다. 배치·길이·숫자 포맷은 전부 렌더러가 정한다.

```bash
python3 $S/render.py html  report.json -o ~/stock-research/reports/<T>/<날짜>-<모드>.html
python3 $S/render.py md    report.json -o ~/stock-research/reports/<T>/<날짜>-<모드>.md
python3 $S/render.py brief report.json     # 대화창에 그대로 붙인다
```

발행 전 반드시 검증한다:
```bash
python3 $S/validate.py --agent report report.json
```

## report JSON

```json
{
  "ticker": "005930.KS", "name": "삼성전자", "market": "KR", "currency": "KRW",
  "mode": "quick", "analysisDate": "2026-08-23",

  "verdict": {
    "rating": "HOLD",
    "proposedRating": "ACCUMULATE",
    "reason": "제안 등급과 다를 때만. 왜 바꿨는지 한두 문장.",
    "score": 7.11,
    "confidence": {"score": 48, "level": "MEDIUM"},
    "headline": "결론 한 문장. 페이지 최상단에 세리프로 크게 들어간다."
  },

  "snapshot": {"price": 281500, "changePct": 0.0387,
               "marketCap": 1641000000000000,
               "asOf": "2026-08-21", "week52": [67500, 374500]},

  "scores": [{"area": "Business", "value": 8.0, "weight": 0.20}],

  "sections": [{"id": "thesis", "title": "Investment Thesis", "open": true,
                "takeaway": "접힌 상태에서 보이는 한 줄 요약",
                "body": "문단. **굵게**, `FACT` 같은 라벨, - 목록을 쓸 수 있다."}],

  "scenarios": [{"name": "Bear", "fairValue": 150000, "upside": -0.467,
                 "probability": 0.25, "basis": "가정 요약"}],

  "risks": [{"name": "사이클 역전", "severity": "high", "note": "근거 한 줄"}],
  "criticalFlags": {"accounting": "low", "dataReliability": "high"},

  "changeMyMind": ["관측 가능한 조건 (최소 2개, deep은 3개 이상)"],
  "unavailable": [{"section": "DCF", "reason": "적자 기업이라 부적합"}],
  "sources": [{"tier": 1, "name": "DART 전자공시", "asOf": "2026-08-22", "url": "https://..."}]
}
```

**`sections[].body`만 자유 서술이다.** 나머지는 전부 구조화 필드이며, 여기가 형식이 흔들리지 않는 이유다.

## 값 규칙

| 필드 | 규칙 |
|---|---|
| `changePct`, `upside` | 비율 그대로 (3.9%는 `0.039`). 렌더러가 부호와 색을 붙인다. |
| `marketCap`, `fairValue` | 원 단위 숫자 그대로. 조/억, T/B 변환은 렌더러가 한다. |
| `score`, `scores[].value` | 0~10 |
| `confidence.score` | 0~100, `level`은 LOW/MEDIUM/HIGH |
| `severity`, `criticalFlags` | `low` / `medium` / `high` / `unknown` |
| `rating` | STRONG BUY · BUY · ACCUMULATE · HOLD · REDUCE · AVOID · INSUFFICIENT DATA |

**숫자를 문자열로 넣지 않는다.** `"1,641조원"`이 아니라 `1641000000000000`이다.
포맷을 직접 하면 그 순간 리포트 안에서 표기가 갈린다.

## 모드별 상한 (렌더러가 강제한다)

| 모드 | 섹션 | 본문 예산 | 리스크 | 출처 | 시나리오 |
|---|---:|---:|---:|---:|---|
| quick | 4 | 420자 | 3 | 5 | O |
| deep | 무제한 | 무제한 | 9 | 20 | O |
| valuation | 4 | 700자 | 3 | 8 | O |
| technical | 3 | 500자 | 3 | 4 | X |
| earnings | 4 | 600자 | 4 | 8 | X |
| news / market_movement | 3 | 600 / 450자 | 3 | 10 / 8 | X |
| compare | 4 | 600자 | 5 | 12 | X |
| portfolio | 4 | 600자 | 6 | 8 | X |
| recheck | 3 | 450자 | 4 | 8 | X |

상한을 넘기면 **잘라내고 경고를 리포트에 남긴다.** 조용히 버리지 않는다.
quick에서 더 담고 싶으면 늘리지 말고 deep을 권한다 — quick이 deep이 되면 두 모드를 나눈 의미가 없다.

## 서술 규칙

- **본문은 한국어, 지표명과 Rating은 영문 원어** (Forward P/E, ROIC, FCF Yield, BUY/HOLD).
- 수치에 라벨을 붙인다: `` `FACT` `` `` `ESTIMATE` `` `` `ASSUMPTION` `` `` `OPINION` ``.
  백틱으로 감싸면 렌더러가 색 배지로 만든다. `` `CONFLICTED` ``도 인식한다.
- `takeaway`는 **결론**을 쓴다. "밸류에이션을 살펴본다"가 아니라
  "저PER·고PBR 조합은 전형적인 사이클 고점의 지문이다".
- 데이터를 못 구한 영역은 섹션에서 지우지 말고 `unavailable`에 넣는다. 빈칸이 정보다.
- `changeMyMind`는 관측 가능해야 한다. "성장이 둔화되면"은 조건이 아니고,
  "3분기 영업이익이 90조원 미만이면"이 조건이다.

## 비교·포트폴리오

`compare`는 종목별 점수를 `scores`에 합치지 말고, 비교표를 `sections[].body`에 마크다운 표로 넣는다
(렌더러가 가로 스크롤 컨테이너로 감싼다). 마지막에 **Best Business / Best Growth /
Best Valuation / Lowest Risk / Best Overall**을 반드시 구분한다.

`portfolio`는 `verdict.rating`을 비우고(`INSUFFICIENT DATA`) 관찰만 낸다.
`profile.json`이 없으면 비중·금액을 제시하지 않는다.
