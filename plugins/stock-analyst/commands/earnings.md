---
description: 최근 실적과 가이던스를 분석한다 (Beat/Miss가 아니라 실적의 질)
argument-hint: <종목명 또는 티커>
---

`stock-analyst` 스킬을 **earnings 모드**로 실행한다. 대상: **$ARGUMENTS**

`fetch.py filings`로 최근 공시를 확보하고 `stock-news` + `stock-financial`을 병렬로 띄운다.

단순 Beat/Miss로 끝내지 않는다. 매출 성장의 질, 마진 변화, FCF 변화, 주식보상, CapEx,
그리고 **가이던스가 상향/유지/하향 중 무엇인지**를 반드시 다룬다.
Actual / Estimate / Surprise를 표로 제시하되, 컨센서스는 WebSearch로 확인하고 `ESTIMATE`로 라벨링한다.
