---
description: 현재 주가가 적정한지만 분석한다 (3중 비교 + DCF)
argument-hint: <종목명 또는 티커>
---

`stock-analyst` 스킬을 **valuation 모드**로 실행한다. 대상: **$ARGUMENTS**

`references/valuation.md`를 읽고 따른다. `stock-valuation` 에이전트 1개만 쓴다.

반드시 3중 비교(현재 / 자사 과거 5년 / 동종기업)를 수행하고, 하나라도 못 구하면 `partial`로 표기한다.
DCF는 `dcf.py`로 계산하고 가정표와 민감도표를 함께 제시한다 — 적정주가만 인용하지 않는다.
