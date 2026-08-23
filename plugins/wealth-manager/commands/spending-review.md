---
description: 최근 소비 패턴을 분석한다 (구독증가·생활비인플레이션·소비급증·편의성소비)
argument-hint: [YYYY-MM], 예: 2026-08 (생략하면 최근 월)
---

`wealth-manager` 스킬을 **spending 모드**로 실행한다. 대상 월: **$ARGUMENTS**

`spending-analyst` 하나만 부른다(필요하면 저축여력 확인을 위해 `cashflow-analyst`도 병렬로).
`~/wealth/transactions/`에 12개월 미만 이력만 있으면 lifestyleInflation은 `notComputable`이라고
정직하게 보고한다 — 판단하지 않는다.

`impulse`(충동구매)를 단정하지 않는다. `references/routing.md`를 참고한다.
