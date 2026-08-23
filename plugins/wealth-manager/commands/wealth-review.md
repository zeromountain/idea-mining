---
description: 월간 종합 재무 리뷰를 실행한다 (순자산·저축률·목표진행률 + Top 3 이슈/액션)
argument-hint: (인자 없음)
---

`wealth-manager` 스킬을 **checkup 모드**로 실행한다.

cashflow·spending·debt·insurance·goal을 전체 병렬로 돌린 뒤 `arbitrate.py` →
`financial-risk-manager` 순으로 진행한다. `snapshot.py take`로 이번 달 스냅샷을 남기고
직전 달과 `delta`를 비교한다.

리포트는 **Top 3 Financial Issues**와 **Top 3 Actions**만 우선 표시한다(문서 §29) —
`render.py`의 `checkup` 모드 상한(actions 3개)이 이를 강제한다.
