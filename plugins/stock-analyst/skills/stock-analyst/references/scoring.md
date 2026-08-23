# 점수·등급·신뢰도

## 7영역 가중치 (문서 §26)

| 영역 | 가중치 | 산출 에이전트 |
|---|---:|---|
| business | 0.20 | Fundamental |
| growth | 0.15 | Fundamental / Financial |
| financial | 0.15 | Financial |
| valuation | 0.20 | Valuation |
| technical | 0.10 | Technical |
| catalyst | 0.10 | News |
| risk | 0.10 | Risk (**10 = 리스크 최저**) |

실행되지 않은 영역은 빼고 남은 가중치를 정규화한다. `score.py`가 자동으로 처리하며,
어느 영역이 빠졌는지 `skippedSections`로 돌려준다 — 리포트에 반드시 명시한다.

## Rating 밴드 (문서 §27)

```
9.0 ~ 10   STRONG BUY
8.0 ~ 8.9  BUY
7.0 ~ 7.9  ACCUMULATE
5.5 ~ 6.9  HOLD
4.0 ~ 5.4  REDUCE
0   ~ 3.9  AVOID
```

**점수만으로 자동 결정하지 않는다.** `score.py`는 `proposedRating`만 낸다.
Committee가 확정하거나 하향하고, 어느 쪽이든 이유를 문장으로 남긴다.

## 하향 트리거

Risk Analyst가 아래 7개 중 하나라도 `high`로 판정하면 `downgradeReviewRequired: true`가 되고,
Committee는 하향 여부를 **반드시 문장으로 판단해야 한다.** 종합 점수가 높다는 이유로 무시하지 않는다.

`accounting` · `goingConcern` · `fraud` · `leverage` · `regulation` · `dataReliability` · `extremeValuation`

## INSUFFICIENT DATA (문서 §68)

다음 중 하나면 등급 대신 `INSUFFICIENT DATA`를 낸다:
- 핵심 재무 커버리지 `coverage.ratio < 0.6`
- 7영역 중 4개 이상이 비어 있음

억지로 등급을 만드는 것보다 데이터가 없다고 말하는 편이 정확하다.

## Confidence (문서 §28)

| 입력 | 가중치 | 방향 |
|---|---:|---|
| dataQuality | 0.30 | 높을수록 ↑ |
| dataFreshness | 0.20 | 높을수록 ↑ |
| analystAgreement | 0.20 | 높을수록 ↑ |
| valuationUncertainty | 0.15 | 높을수록 ↓ |
| eventRisk | 0.15 | 높을수록 ↓ |

각 0~1로 입력하면 0~100 점수와 LOW(<45) / MEDIUM(<70) / HIGH 등급이 나온다.

## 실행

```bash
echo '{"ticker":"NVDA",
 "scores":{"business":9.2,"growth":9.0,"financial":9.1,"valuation":6.0,"technical":7.0,"catalyst":8.0,"risk":5.5},
 "riskFlags":{"accounting":"low","goingConcern":"low","fraud":"low","leverage":"low","regulation":"high","dataReliability":"medium","extremeValuation":"medium"},
 "confidenceInputs":{"dataQuality":0.9,"dataFreshness":0.95,"analystAgreement":0.6,"valuationUncertainty":0.5,"eventRisk":0.4},
 "coverage":{"ratio":1.0,"missingSections":[]}}' | python3 $S/score.py -
```

## 채점 감각

- 밸류에이션 점수는 사업 품질과 **절대 섞지 않는다.** 훌륭한 회사가 비싸면 valuation은 낮은 점수다.
  이것이 STRONG BUY 남발을 막는 유일한 장치다.
- 저성장 우량주(KO 같은)는 growth 5~6, business 8~9가 정상이다. 종합 7점대면 ACCUMULATE가 맞다.
- 적자 고성장주는 financial 점수를 후하게 주지 않는다. 성장은 growth에서 이미 반영된다.
