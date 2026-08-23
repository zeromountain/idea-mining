---
description: 보험 포트폴리오를 검토한다 (보장공백·중복특약·보험료 부담률)
argument-hint: (인자 없음)
---

`wealth-manager` 스킬을 **insurance 모드**로 실행한다.

`insurance-manager`와 `cashflow-analyst`를 병렬로, 마지막에 `financial-risk-manager`로
검증한다. `insurance.assumptions`(유족필요생활비 등)가 없으면 보장공백을 기본값으로 채우지
않고 `AskUserQuestion`으로 물어본다.

중복 특약은 실손형/정액형을 구분해서 보고한다. **해지를 직접 권하지 않는다** — 최종 권고는
항상 `CONSULT_PROFESSIONAL`에서 멈춘다 (`agents/insurance-manager.md`).
