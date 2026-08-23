---
description: ~/stock-research/profile.json을 재계산해 기록한다 (stock-analyst의 투자 비중 제시를 여는 열쇠)
argument-hint: (인자 없음)
---

`wealth-manager` 스킬을 실행하되 리포트를 만들지 않고 `references/integration.md`의
`profile.json` 산출 절차만 수행한다.

cashflow · debt · goal → `arbitrate.py`로 `monthlyInvestable`을 확정한 뒤, 거부 규칙
R1~R6을 확인한다. 하나라도 걸리면 `profile.json`을 쓰지 않고 대신
`~/stock-research/profile.blocked.json`에 사유와 `unblockCondition`을 남긴다.

**쓰기 전에 반드시 `AskUserQuestion`으로 확인을 받는다** — 다른 플러그인의 파일을 조용히
바꾸지 않는다.
