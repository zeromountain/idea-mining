---
description: 보유 포트폴리오의 집중도와 리스크를 분석한다
argument-hint: [티커와 비중], 예: VOO 40 QQQ 30 NVDA 15 PLTR 15 (생략하면 저장된 portfolio.json 사용)
---

`stock-analyst` 스킬을 **portfolio 모드**로 실행한다. 입력: **$ARGUMENTS**

`references/portfolio.md`를 읽고 따른다.

인자가 없으면 `~/stock-research/portfolio.json`을 읽고, 그것도 없으면 사용자에게 비중을 묻는다.
각 종목은 `fetch.py quote`만 쓴다 (전체 deep 분석을 돌리지 않는다).
ETF는 구성종목까지 펼쳐 **실질 중복**을 계산한다.

**`profile.json`(투자 성향)이 없으면 구체적 비중이나 금액을 제시하지 않는다.**
관찰과 리스크만 알리고, 판단에 필요한 정보가 무엇인지 밝힌다.
