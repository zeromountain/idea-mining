---
description: 여러 종목을 동일 기준으로 비교한다
argument-hint: <티커 2개 이상>, 예: NVDA AMD AVGO
---

`stock-analyst` 스킬을 **compare 모드**로 실행한다. 대상: **$ARGUMENTS**

각 종목에 quick 파이프라인을 **병렬로** 돌린 뒤 비교 에이전트 1개로 종합한다.
`fetch.py peers <첫 종목> --peers <나머지>`로 동일 지표를 한 번에 확보한다.

`references/templates.md`의 비교표를 쓰고, 반드시 다섯을 구분해 제시한다:
Best Business / Best Growth / Best Valuation / Lowest Risk / Best Overall.
다섯이 한 종목으로 몰리면 왜 그런지 설명하거나 분석을 다시 본다.
