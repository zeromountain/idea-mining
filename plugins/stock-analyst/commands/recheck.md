---
description: 저장된 투자 Thesis가 아직 유효한지 재검증한다 (전체 재분석 없이)
argument-hint: <종목명 또는 티커>
---

`stock-analyst` 스킬을 **recheck 모드**로 실행한다. 대상: **$ARGUMENTS**

`references/memory.md`의 recheck 절차를 따른다.

`thesis/<TICKER>.json`을 읽어 **무효화 조건과 감시 지표만** 다시 확인한다.
전체 재분석을 하지 않는다 — 그게 이 모드의 존재 이유다.

판정: `VALID` / `WEAKENING` / `BROKEN` / `IMPROVING`
결과를 `thesis/<TICKER>.json`의 `rechecks[]`에 **덧붙인다** (덮어쓰지 않는다).
`BROKEN`이면 전체 재분석을 제안한다.

Thesis 파일이 없으면 먼저 `/stock-analyst:deep`을 제안한다.
