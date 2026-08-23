---
description: 종목을 전체 파이프라인으로 심층 분석한다 (Bull/Bear 논쟁 + Investment Committee + 리포트 저장)
argument-hint: <종목명 또는 티커> [--peers A,B], 예: NVDA --peers AMD,AVGO
---

`stock-analyst` 스킬을 **deep 모드**로 실행한다. 대상: **$ARGUMENTS**

전체 DAG를 돈다:
1. `fetch.py bundle`로 데이터 확보
2. 1단 병렬 — Fundamental / Financial / Technical / News / Macro
3. `validate.py`로 스키마 검증 + 숫자 교차검증
4. 2단 병렬 — Valuation / Bull / **Bear(격리)** / **Risk(격리)**
5. `score.py` → Investment Committee가 최종 등급 확정
6. 리포트를 `~/stock-research/reports/`에 저장하고, Thesis와 무효화 조건을 `thesis/`에 남긴다

Bear와 Risk에는 1단의 긍정적 서술을 넘기지 않는다. 단계마다 진행 상황을 한 줄로 알린다.
