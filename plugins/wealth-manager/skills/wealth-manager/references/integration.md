# 기존 시스템 연동 — stock-analyst · real-estate-advisor

이 스킬은 주식·부동산 전문성을 새로 만들지 않는다. **기존 파일을 수정하지 않고** 두 가지
seam으로만 연결한다.

## stock-analyst — 파일 seam

`~/stock-research/`가 연결점이다. stock-analyst 자체는 수정하지 않는다.

### 읽기

- `thesis/<TICKER>.json` — 저장된 투자논리·무효화조건
- `reports/<TICKER>/<날짜>-<모드>.json` — 과거 분석
- `INDEX.md` — 분석 이력

### 쓰기 — `~/stock-research/profile.json`

stock-analyst는 이 파일이 없으면 **스스로 투자 비중 제시를 차단한다**
(`positionSizingWithheld: true`). 이 스킬이 그 파일을 계산해서 쓴다.

```json
{
  "schemaVersion": 1, "updatedAt": "2026-08-23", "expiresAt": "2026-11-21",
  "source": "wealth-manager",
  "horizonYears": 12, "cashNeededWithinMonths": 6, "cashNeededAmount": 50000000,
  "riskTolerance": "MODERATE", "maxDrawdownTolerance": 0.25,
  "monthlyInvestable": 500000, "investableAssets": 42000000,
  "excludedFromInvestable": [{"label": "비상자금 6개월", "amount": 18000000}],
  "constraints": ["연 6.9% 대출 잔액 상환 완료 전까지 신규 투자 비중 확대 금지"],
  "confidence": {"overall": "USER_PROVIDED"}
}
```

각 필드의 산출 근거:

| 필드 | 산출 |
|---|---|
| `horizonYears` | `goals.py` — `investmentFunded: true`인 목표 중 최장 기한, 없으면 `riskProfile`+은퇴목표연령 |
| `cashNeededWithinMonths/Amount` | `goals.py`의 `contention` — 가장 빠른 `liquidityRequired` 목표/이벤트 |
| `monthlyInvestable` | **`arbitrate.py`의 `allocation.byLevel.INVESTMENT_OPPORTUNITY`.** `cashflow.py`의 `surplus`가 **아니다** — 잉여는 남는 돈이고 이건 우선순위 캐스케이드를 통과한 돈이다 |
| `investableAssets` | 최신 스냅샷의 `liquidAssets` − 비상금 하한 − 단기목표 적립분 |
| `riskTolerance` | `min(자기신고, financial-risk-manager가 매긴 재무여력 등급)` — 여력이 의향의 상한 |
| `maxDrawdownTolerance` | `min(자기신고, scenario.py에 ASSET_MARKDOWN을 이분탐색해 bindingConstraint가 NONE을 유지하는 최대 낙폭)` |

### 쓰기 거부 규칙 — 하나라도 참이면 쓰지 않는다

| 규칙 | 조건 |
|---|---|
| R1 | 연 7% 이상 부채 잔존 (G3 BREACHED) |
| R2 | `emergencyFundMonths < 3` (G1 BREACHED) |
| R3 | 12개월 이내 유동성필요 목표가 ON_TRACK이 아님 (G4 BREACHED) |
| R4 | 캐스케이드 후 `monthlyInvestable ≤ 0` |
| R5 | `income` 또는 `liabilities`의 실효 confidence가 UNKNOWN |
| R6 | 최신 스냅샷이 90일 초과 (갱신 거부, 기존 profile을 `stale: true`로만 표시) |

거부되면 `profile.json`을 절대 부분적으로 쓰지 않는다 — 대신 `~/stock-research/profile.blocked.json`에
사유와 `unblockCondition`을 쓴다:

```json
{"blocked": true, "generatedBy": "wealth-manager", "at": "2026-08-23",
 "reasons": [{"rule": "R1", "observed": 0.15, "threshold": 0.07,
             "unblockCondition": "연 15% 잔액 8,000,000원 상환 완료 시 해제"}]}
```

**이 파일을 쓰기 전에 매번 `AskUserQuestion`으로 명시적 확인을 받는다** — 크로스 플러그인
쓰기를 리뷰의 조용한 부수효과로 만들지 않는다. `expiresAt`은 90일이다.

## real-estate-advisor — HTTP seam

`localhost:3001`. 코드는 절대 재구현하지 않는다 — `real-estate-liaison` 에이전트가 유일한
호출 지점이고, `$S/realestate.py`가 유일한 CLI다.

| 엔드포인트 | 용도 | 특성 |
|---|---|---|
| `GET /health` | 데이터 프로바이더 상태(MOCK/실제) 확인 | 항상 먼저 호출 |
| `POST /analysis` | 종합 판단(매수 검토, 전세 안전성) | 검색 백엔드가 Mock이라 대부분 `PARTIAL` |
| `POST /analysis/strategy` | 자금조달안 비교 | LLM 없이 결정론적, 재현 가능 |
| `POST /calculator/{loan,dsr,ltv}` | 순수 계산 | `debt.py`/`cashflow.py`가 이미 씀 |

API가 꺼져 있으면(`pnpm --filter @rea/api start`로 시작) `not_computable`을 받는다 — 로컬로
재구현하지 않고 그대로 사용자에게 알린다. 서울 25개 자치구 밖 주소, `dataProvider: "MOCK"`,
`approvalNote`는 반드시 원문 그대로 전달한다 (`real-estate-liaison.md` 참고).

### 연구 공백 — `real-estate-researcher`가 메우는 부분

`real-estate-advisor`의 `ResearchProvider`는 `MockResearchProvider`로 하드코딩돼 있다
(`apps/api/src/app.module.ts`) — 실제 웹 검색 백엔드는 그 프로젝트 자신의
`docs/implementation-plan.md`가 "Phase 5의 가장 큰 미완성"이라고 명시할 만큼 코드에 없다.
이게 막는 범위는 균일하지 않다:

| 분석 | 막힘 정도 | 실제 원인 |
|---|---|---|
| `policyAnalysis` (규제지역·토지거래허가·LTV/DSR 규정·전매제한) | **완전 차단**, 항상 `PARTIAL` | `policy.agent.ts`가 `ctx.research`를 직접 호출하는데 Mock이라 항상 빈 배열 |
| `loanAnalysis` | 부분 — 데이터는 있지만 얼어 있음 | `SEED` 프로바이더, 버팀목·청년전용 버팀목 2종만, 기준일 고정 |
| `safetyAnalysis` | 영향 적음 | 원래 계획엔 있었으나 코드에 연구 호출 자체가 없음 |
| 시중은행 주택담보대출 금리 | **원천이 아예 없음** | 문서: "시중은행 주택담보대출 금리를 조회할 수단이 없다" — 그래서 `fundingCandidates`를 사용자가 직접 입력해야 한다 |
| `publicHousingAnalysis` | 부분 | LH만, 공고 PDF 원문 파싱 미구현 → `eligibility: UNKNOWN`이 흔함 |

`real-estate-researcher` 에이전트(`agents/real-estate-researcher.md`)가 WebSearch/WebFetch로
이 공백, 특히 `policyAnalysis`를 채운다. **모든 부동산 질문에 부르지 않는다** — `real-estate-liaison`이
받은 `/analysis` 응답의 `degradations`/`missingInformation`에 정책·상품·금리 관련 항목이
실제로 있을 때만 오케스트레이터가 이어서 호출한다. 출처 우선순위·도메인 화이트리스트·신선도는
`references/real-estate-sources.md` — `real-estate-advisor/docs/data-sources.md`와
`.claude/agents/real-estate-researcher.md`에서 그대로 옮겨온 표다(재발명하지 않는다).

**Provenance 분리가 핵심 제약이다.** `real-estate-advisor`의 Verifier는 서버가 낸
`knownFacts`끼리만 `Evidence.subject` 기준으로 충돌을 검사한다. `real-estate-researcher`가
검색으로 찾은 사실은 그 파이프라인 밖에 있으므로 `policyFacts[]`에 `verifiedBy:
"agent-websearch"`로 표시하고 API 사실과 같은 신뢰 수준으로 섞지 않는다 —
`validate.py`가 이 태그와 `sourceUrl` 존재를 스키마 에러로 강제한다.

**`missingInformation[].askIfNeeded`를 활용한다.** API 스키마에 이미 있는(그러나 지금까지
아무도 안 쓰던) 필드다 — 부족한 정보가 결과를 어떻게 바꾸는지까지 담은 완성된 질문 문구다.
`real-estate-advisor/docs/agents.md` §14 질문 전략(부분 답변 먼저, 질문은 그 다음)을 그대로
따라 이 문구를 다음 행동 자리에 쓴다.

**재계산 피드백 루프(선택).** 확인된 규제값이 `AnalysisContext` 필드로 표현되면(예: 규제지역
LTV 상한 → `loanToValuePercent`), 그 값을 다음 `/analysis` 호출의 `context`에 넣어 다시 부를
수 있다 — `mergeContext()`가 호출자 제공 context를 우선하므로 계산 자체가 더 정확해진다.
기본 경로는 아니고, 재계산이 필요할 때만 쓴다.

## 순서 원칙

투자·부동산 도메인 에이전트는 재무 core(cashflow·debt·goal) **다음에** 부른다. 게이트 상태
없이 종목·매물 판단부터 내면, 나중에 arbitrate.py가 그 판단을 뒤늦게 차단하는 나쁜 사용자
경험이 된다.
