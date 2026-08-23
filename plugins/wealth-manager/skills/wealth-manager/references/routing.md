# 질문 유형별 라우팅

`→`는 순차, `·`는 병렬(한 메시지에서 동시에 띄운다)을 뜻한다. `financial-risk-manager`는
항상 마지막에 단독으로 실행한다 — 다른 에이전트와 병렬로 두지 않는다(다른 에이전트의 낙관적
결론에 설득되지 않도록 컨텍스트를 격리해야 한다).

| 질문 예시 | 라우팅 |
|---|---|
| "이번달 너무 많이 쓴 것 같아" | spending-analyst · cashflow-analyst → Wealth Manager |
| "이 보험 해지해도 돼?" | insurance-manager · cashflow-analyst → financial-risk-manager → Wealth Manager |
| "S&P500에 월 100만원씩 투자해도 될까" | cashflow-analyst · debt-manager · goal-manager → arbitrate.py → (ADMITTED면) stock-analyst 스킬 호출 → financial-risk-manager → Wealth Manager |
| "이 종목 사도 될까" (종목 지정) | 위와 동일 + stock-analyst의 quick/deep 모드로 종목 자체 분석 |
| "6억원짜리 아파트를 사도 될까" | cashflow-analyst · debt-manager · goal-manager · insurance-manager → real-estate-liaison → (정책/상품/금리 공백 있으면 real-estate-researcher) → arbitrate.py → financial-risk-manager → Wealth Manager |
| "이 동네 토지거래허가구역이야?" / "버팀목 소득기준 얼마야" | real-estate-liaison → real-estate-researcher(정책·상품 검색) → Wealth Manager |
| "차 5,000만원 사면 어떻게 돼?" | scenario.py(시나리오 조립) → goal-manager · cashflow-analyst → financial-risk-manager → Wealth Manager |
| "순자산 얼마야" / "이번달 변화" | `snapshot.py series`/`delta` 읽기만. **에이전트 0개** |
| "이 대출 갈아탈까?" | debt-manager (refinance 서브커맨드) → financial-risk-manager → Wealth Manager |
| "조기상환 vs 투자 뭐가 나아?" | debt-manager (prepay-vs-invest) → financial-risk-manager → Wealth Manager |
| "저축 계획 짜줘" / "목표 달성하려면 얼마씩" | goal-manager · savings-strategist → Wealth Manager |
| 월간 리뷰 요청 | cashflow · spending · debt · insurance · goal (전체 병렬) → arbitrate.py → financial-risk-manager → Wealth Manager |

## 판단 기준

- **정보 요청뿐인가, 의사결정이 걸려 있는가.** "순자산 얼마야"는 스냅샷을 읽으면 끝난다.
  "6억 아파트 사도 될까"는 여러 도메인이 얽힌 의사결정이라 병렬 core + arbitrate가 필요하다.
- **투자/부동산 도메인 에이전트(stock-analyst, real-estate-liaison)는 재무 core 다음에
  부른다.** 순서를 바꾸면 게이트 상태 없이 종목/매물 판단부터 나와서 최종 조율이 뒤늦게
  결론을 뒤집는 나쁜 사용자 경험이 된다.
- **모호하면 cashflow-analyst 하나로 시작**하고 결과를 보여준 뒤 더 깊은 분석을 제안한다.
  처음부터 8개 에이전트를 돌리는 것보다 실제 사용 패턴에 맞는다.
