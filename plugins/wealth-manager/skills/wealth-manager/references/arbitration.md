# 게이트와 중재 — arbitrate.py

우선순위는 문장이 아니라 숫자다. 같은 재무상태에서 화요일과 목요일에 다른 결론이 나오면 안
된다 — 그래서 이 절차는 전부 `$S/arbitrate.py`가 결정론적으로 계산하고, 오케스트레이터는
결과를 한국어 문장으로 옮기기만 한다. **판정을 뒤집지 않는다.** 다른 결론을 주장하려면
게이트의 입력값을 바꾸는 새 증거를 내놓아야 한다.

## 우선순위 6단계

```
1 STABILITY              생활 안정성
2 LIQUIDITY               유동성
3 DEBT_RISK                고금리 부채
4 NEAR_TERM_GOAL             임박한 재무목표
5 INSURANCE                    보험 보장
6 INVESTMENT_OPPORTUNITY          투자 기회
```

## 게이트 5개

| 게이트 | 레벨 | OPEN 조건 | UNKNOWN 처리 |
|---|---|---|---|
| G1 소득중단 대비 | 1 | `emergencyFundMonths ≥ 3` | BREACHED로 취급 |
| G2 유동성 | 2 | `surplus > 0` AND `cashBalance ≥ monthlyFixed` | BREACHED로 취급 |
| G3 고위험부채 | 3 | 연 7%(0.07) 이상 부채 없음, 부채 커버리지 100% | BREACHED로 취급 |
| G4 임박목표 | 4 | 12개월 이내 유동성필요 목표 중 OFF_TRACK/INFEASIBLE 없음 | OPEN-경고로 취급 |
| G5 보장공백 | 5 | CRITICAL 보장공백 없음 | OPEN-경고로 취급 |

게이트 1~3에서 UNKNOWN이 BREACHED로 취급되는 이유: 모르는 유동성·부채는 그 자체가 위험이다.
4~5에서 OPEN으로 취급되는 이유: 모르는 투자 상방은 비상사태가 아니다. 이 비대칭이 이
시스템에서 confidence 상태가 실제로 값을 하는 지점이다.

G3의 0.07 임계값은 15.4% 금융소득세 차감 후 어떤 방어 가능한 장기 기대수익도 넘어서는
확정·무위험 수익률(세전 환산 약 8.3%)에서 근거했다 — `arbitrate.py`의
`HIGH_INTEREST_RATE_THRESHOLD` 상수로 버전 관리된다.

## proposals.json 입력 계약

```json
{
  "state": {
    "emergencyFundMonths": 2.1, "monthlySurplus": 900000, "cashBalance": 3000000,
    "monthlyFixed": 2100000, "maxDebtRate": 0.15, "highInterestBalance": 8000000,
    "nearTermGoals": [{"id": "house-deposit", "dueMonths": 6, "feasibility": "OFF_TRACK"}],
    "insuranceGapCritical": true,
    "coverage": {"income": 1.0, "liabilities": 0.6}
  },
  "proposals": [
    {"id": "p1", "source": "stock-analyst", "category": "INVESTMENT_OPPORTUNITY",
     "action": "월 50만원 추가 매수", "monthlyAmount": 500000,
     "evidence": "OPINION", "certainty": "EXPECTED", "dueMonths": null}
  ],
  "userOverride": null
}
```

`state`는 cashflow-analyst·debt-manager·goal-manager·insurance-manager·financial-risk-manager
의 출력에서 오케스트레이터가 조립한다. 각 에이전트의 스크립트 출력 JSON에서 그대로 뽑아 쓴다 —
암산하지 않는다.

`category`는 `STABILITY|LIQUIDITY|DEBT_RISK|NEAR_TERM_GOAL|INSURANCE|INVESTMENT_OPPORTUNITY`
중 하나. `certainty`는 `CERTAIN|EXPECTED|SPECULATIVE`.

## 출력

`decisions[].verdict`는 `ADMITTED`(전액) · `PARTIAL`(부분) · `DEFERRED`(예산 소진, 게이트는
안 깨짐) · `BLOCKED`(게이트 위반) · `ADMITTED_WITH_OVERRIDE`. `BLOCKED`는 항상
`unblockCondition`을 동반한다 — 없으면 `validate.py --agent arbitration`이 에러를 낸다.

## Override 채널

유일한 합법적 우회는 `userOverride: {"proposalId": "...", "acknowledgedRisk": true, "at":
"ISO시각"}`이고, **사용자가 명시적으로 요청했을 때만** 채운다. LLM이 스스로 override를 만들지
않는다. override가 적용돼도 예산이 남아 있어야 실제로 자금이 배정된다 — 게이트 통과가 곧
전액 승인은 아니다.

## 절차 요약

1. `arbitrate.py`가 게이트 5개를 평가한다.
2. 레벨 순으로 잉여를 캐스케이드 배분한다.
3. 자기 레벨보다 낮은 레벨의 게이트가 BREACHED면 예산과 무관하게 BLOCKED.
4. 동일 레벨 타이브레이크: 임박도 → 확실성(CERTAIN 우선) → 금액 작은 순 → id.
5. override가 있으면 해당 제안만 차단을 풀고 다시 캐스케이드에 태운다.

## Wealth Manager가 하는 일

`arbitrate.py`는 산문을 쓰지 않는다. 오케스트레이터가 `decisions[]`를 사용자 언어로 옮기고,
`unblockCondition`을 "이 조건이면 됩니다" 형태의 다음 행동으로 바꾼다. 판정에 동의하지 않으면
`arbitrationDissent`로 리포트에 남기되(문서 §28), state를 조작해 원하는 결론을 끌어내지 않는다.
