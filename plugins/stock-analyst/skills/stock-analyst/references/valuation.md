# 밸류에이션 절차

## 1. 3중 비교 — 하나라도 빠지면 `partial`

| 비교 축 | 데이터 | 없을 때 |
|---|---|---|
| 현재 멀티플 | `financials.json`의 `valuation` | — |
| vs 자사 과거 5년 | WebSearch (Morningstar / Macrotrends 등) | `available: false`로 표기 |
| vs 동종기업 | `peers.json`의 `rows` | 피어를 명시적으로 지정받아 재실행 |

동종기업 비교는 **같은 지표로만** 한다. A는 Forward P/E, B는 Trailing P/E로 비교하는 것은 비교가 아니다.

## 2. 배수 읽는 법

- `evWarning`이 붙어 있으면 EV 기반 배수(evToRevenue, evToFcf)에 그 경고를 함께 인용한다.
- PEG는 과거 EPS CAGR 기준이라 기저효과에 취약하다. 값이 극단적이면(0.3 미만, 3 초과)
  숫자만 쓰지 말고 왜 그런지 적는다.
- **현재 배수가 요구하는 성장률을 역산**해 실제 컨센서스와 비교한다. 이것이
  "이미 반영된 기대"(`impliedExpectations`)의 실체이며, Bear와 Committee가 그대로 인용한다.

## 3. DCF

### 하지 않아야 할 때
적자가 지속되는 기업, 은행·보험 등 금융주, ETF. 생략하고 사유를 적는다.
억지로 돌린 DCF는 정보가 아니라 소음이다.

### 절차
가정만 JSON으로 제출하고 계산은 `dcf.py`에 맡긴다.

```bash
echo '{...}' | python3 $S/dcf.py -
```

필수 입력: `baseRevenue` · `sharesOutstanding`. 권장: `netDebt` · `currentPrice` · `taxRate`.
시나리오마다 `revenueGrowth`(연도별 배열) · `operatingMargin` · `fcfConversion` · `wacc` ·
`terminalGrowth` · `probability`.

### 시나리오 설계 (문서 §14)
Bear / Base / Bull 셋을 만들고 확률 합을 1.0으로 맞춘다.
- **Bear는 파산 시나리오가 아니다.** 가장 그럴듯한 실망 경로다.
- Bull은 낙관의 상한이 아니라 **실현 가능한 최선**이다.
- 세 시나리오의 차이가 성장률 한 줄뿐이면 시나리오를 나눈 의미가 없다. 마진과 WACC도 함께 움직인다.

### 결과 다루기 (문서 §15, §70)
- `warnings`를 **그대로 리포트에 옮긴다.** 특히 잔존가치 비중 75% 초과 경고는 생략 금지.
- 적정주가만 인용하고 가정표·민감도표를 빼는 것은 금지다.
- 모든 DCF 수치에 `ASSUMPTION` 라벨을 붙인다.
- 민감도표(WACC × 영구성장률 5×5)를 리포트에 넣는다. DCF가 가정의 함수임을 보여주는 장치다.

## 4. 판정

`cheap` / `fair` / `expensive` / `extreme` 중 하나. 근거는 3중 비교에서 나와야 한다.
"성장주라서 프리미엄이 정당하다"는 순환논법이다 — 프리미엄의 크기를 숫자로 정당화하지 못하면 쓰지 않는다.
