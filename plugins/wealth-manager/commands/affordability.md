---
description: 이거 사도 되나를 판정한다 (아파트·자동차·큰 지출 등, 게이트 통과 여부까지 확인)
argument-hint: <구매 대상과 금액>, 예 — 6억원짜리 아파트 또는 5,000만원 자동차
---

`wealth-manager` 스킬을 **deep 모드**로 실행한다. 대상: **$ARGUMENTS**

`references/routing.md`의 라우팅을 따른다 — 부동산이면 cashflow·debt·goal·insurance 병렬 →
`real-estate-liaison`, 그 외 큰 지출이면 `scenario.py`로 조립한다. 반드시 `arbitrate.py`를
거쳐 게이트 통과 여부를 확정한 뒤 `financial-risk-manager`로 마무리한다.

`BLOCKED`가 나오면 `unblockCondition`("이 조건이면 됩니다")을 최우선으로 제시한다 — 단순
"안 됩니다"로 끝내지 않는다.
