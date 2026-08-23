---
description: 이 선택을 하면 미래에 어떻게 되는가를 시뮬레이션한다 (차량구매·주택구매·이직·조기상환·대출·보험가입 등)
argument-hint: <자연어로 상황 설명>, 예 — 3년 뒤 이직하면서 6개월 소득 공백이 생기면
---

`wealth-manager` 스킬을 **scenario 모드**로 실행한다. 상황: **$ARGUMENTS**

사용자 설명을 `$S/scenario.py`의 닫힌 이벤트 어휘 11종(INCOME_CHANGE·EXPENSE_RECURRING_ADD/
REMOVE·EXPENSE_ONEOFF·ASSET_ACQUIRE/DISPOSE/MARKDOWN·NEW_LOAN·LOAN_PREPAY·LOAN_REFINANCE·
TRANSFER)으로 조립해 `~/wealth/scenarios/<slug>.json`에 저장한 뒤 실행한다. 케이스별로 새
계산 로직을 만들지 않는다 — 이벤트 조합으로 표현한다.

`breakPoints.bindingConstraint`("왜 안 되는가")를 결과의 핵심으로 제시하고, `vsBaseline`으로
"이 선택을 안 했을 때"와 비교한다. `assumptions[]`(자산가치 변동률 등)는 반드시 명시한다 —
이 시스템은 가격을 예측하지 않는다.
