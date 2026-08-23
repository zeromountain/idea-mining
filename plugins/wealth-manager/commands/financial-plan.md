---
description: 재무 목표 기반 저축 전략을 세운다 (목표 충돌 탐지 + 우선순위 제안)
argument-hint: (인자 없음, 목표는 financial-context.json의 goals[]에서 읽는다)
---

`wealth-manager` 스킬을 **goal 모드**로 실행한다.

`goal-manager`와 `savings-strategist`를 순차로 실행한다(savings-strategist가 goal-manager의
월 그리드·충돌 결과를 입력으로 쓴다). `goals.py`의 `contention.competingSets`가 비어 있지
않으면 선택지(DELAY/REDUCE_TARGET/REPRIORITIZE)를 사용자에게 제시하고 대신 결정하지 않는다.

목표가 `financial-context.json`에 없으면 `AskUserQuestion`으로 받아
`wealth_context.py set goals#<id>...`로 저장한다.
