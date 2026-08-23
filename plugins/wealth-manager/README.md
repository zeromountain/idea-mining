# wealth-manager

사용자의 전체 재무 상태를 관리하는 **Personal CFO** Claude Code 플러그인.
현금흐름 → 저축 → 소비 → 부채 → 보험 → 목표 → (필요하면) 주식·부동산 → 리스크 검증 순으로
진행하고, 최종 판단은 게이트 기반 산술 중재로 재현 가능하게 내린다.

## 왜 이렇게 만들었나

`stock-analyst`(주식)와 `real-estate-advisor`(부동산)는 이미 있었지만 둘을 잇는 것이 없었다.
주식 시스템은 투자성향 파일이 없으면 스스로 비중 제시를 차단하고, 부동산 시스템은 "이 집을
사면 다른 목표가 어떻게 되나"에 답하지 못한다. 소비·저축·부채·보험·목표 계층은 아예 없었다.

이 플러그인은 그 빠진 계층이다. 기존 두 시스템은 **한 줄도 재작성하지 않는다** —
주식은 `~/stock-research/profile.json`을 써주는 것으로, 부동산은 `localhost:3001` HTTP 호출로
편입한다.

- **투자수익보다 재무 안정성.** 게이트(비상자금·유동성·고금리부채·임박목표·보장공백)가 하나라도
  깨지면 그보다 낮은 우선순위의 투자 제안은 예산이 남아도 차단된다.
- **순서는 코드, 설명은 LLM.** 같은 대차대조표가 화요일과 목요일에 다른 결론을 내면 안 된다.
  우선순위 캐스케이드와 게이트 판정은 `arbitrate.py`가 결정론적으로 계산하고, 에이전트는 그
  결과를 한국어 문장으로 옮길 뿐 뒤집지 않는다.
- **모르는 것을 침묵하지 않는다.** 모든 컨텍스트 값에 VERIFIED/USER_PROVIDED/ESTIMATED/UNKNOWN
  신뢰도가 붙고, 모든 에이전트 출력은 `unknownImpact`(어떤 UNKNOWN이 어떤 결론을 약화시켰는가)를
  필수로 낸다.
- **조기상환 vs 투자를 같은 종류의 숫자로 비교하지 않는다.** 확정 이자 절감(`certain`)과
  기대 투자수익(`uncertain`)은 서로 다른 `kind`로 나란히 내고, 스칼라 `netBenefit`은 만들지 않는다.

## 설치

```
/plugin marketplace add zeromountain/idea-mining
/plugin install wealth-manager@my-plugins
```

로컬 테스트:
```bash
cc --plugin-dir ~/claude-plugins/plugins/wealth-manager
```

## 사용법

스킬은 자연어로 트리거된다 — "이번달 너무 많이 썼나", "이 보험 해지해도 돼?",
"6억 아파트 사도 될까", "순자산 얼마야" 같은 말이면 된다. 명시적으로 부르려면 슬래시 커맨드를 쓴다.

| 커맨드 | 하는 일 |
|---|---|
| `/wealth-manager:wealth-review` | 월간 종합 리뷰 — 순자산·저축률·목표 진행률 + Top 3 이슈/액션 |
| `/wealth-manager:spending-review [YYYY-MM]` | 소비 패턴 분석 |
| `/wealth-manager:insurance-review` | 보장공백·중복특약·보험료 부담 |
| `/wealth-manager:financial-plan` | 목표 기반 저축 전략 |
| `/wealth-manager:scenario <설명>` | "이 선택을 하면 어떻게 되나" 시뮬레이션 |
| `/wealth-manager:affordability <설명>` | "이거 사도 되나" 판정 |
| `/wealth-manager:profile-sync` | `~/stock-research/profile.json` 재계산·기록 |

## 기존 시스템과의 관계

| | 방식 |
|---|---|
| `stock-analyst` | 파일 seam. `~/stock-research/profile.json`(6개 항목: 투자기간·위험감내도·최대낙폭·월투자금액·현재자산·현금필요시점)을 계산해 쓰고, `thesis/`·`reports/`를 읽는다. 게이트가 깨지면 `profile.blocked.json`을 쓰고 사유를 남긴다 |
| `real-estate-advisor` | HTTP seam. `localhost:3001`의 `/analysis`, `/analysis/strategy`, `/calculator/{loan,dsr,ltv}`를 호출한다. 서버가 꺼져 있으면 `not_computable`로 degrade하고 로컬로 재구현하지 않는다. `real-estate-advisor`의 검색 백엔드가 Mock이라 정책·규제 관련 항목이 구조적으로 항상 `PARTIAL`인데, `real-estate-researcher` 에이전트(WebSearch/WebFetch)가 그 공백을 공식 출처에서 채운다 — 계산은 여전히 API 전담 |

두 시스템 모두 **단 한 줄도 수정하지 않는다** (`stock-analyst/skills/stock-analyst/references/portfolio.md`에
`profile.blocked.json` 처리 1줄을 추가하는 것이 유일한 예외).

## 데이터

```
~/wealth/
├── financial-context.json              정본 — 사용자가 주장한 사실만
├── financial-context.resolved.json     파생 — confidence 상속·감쇠 적용, 합계
├── categories.json                     거래 분류 규칙
├── transactions/raw/                   카드·은행 원본 (사용자 소유)
├── transactions/<YYYY-MM>.normalized.json
├── insurance/policies.json
├── snapshots/<YYYY-MM>.json            순자산 스냅샷 (append-only)
├── scenarios/<slug>.json + results/
├── cache/calc/                         :3001 응답 캐시
├── reports/<날짜>-<모드>.{json,md,html}
└── runs/<날짜>-<모드>.jsonl            실행·중재·override 로그
```

**리포트는 아티팩트로 자동 게시하지 않는다.** stock-analyst와 다른 점이다 — 순자산 리포트가
공개 URL에 놓이는 건 주식 리포트와 범주가 다른 실수다. 게시하려면 매번 명시적 확인과
`--redact`(비율·방향만, 절대금액·기관명 제거)가 필요하다.

## 개발

```bash
python3 -m unittest discover -s scripts/tests -t .        # 24개, 네트워크 없음
python3 -m json.tool .claude-plugin/plugin.json
WEALTH_HOME=/tmp/wealth-test python3 scripts/wealth_context.py doctor
```

`scripts/tests/test_core.py`의 회귀 테스트 중 특히 두 개를 지우지 마세요.
- `TestConfidenceLattice.test_block_confidence_ignores_id_and_label` — **`id` 필드 하나가
  블록 전체 confidence를 깎던 실제 버그**의 재발 방지 테스트. 구현 중 발견하고 고쳤다.
- `TestArbitrate.test_low_emergency_fund_blocks_everything_above_stability` — 게이트 차단이
  자기 레벨보다 낮은 레벨 전체에 전이되는지 확인한다. 이게 깨지면 "안정성이 최우선"이라는
  이 시스템의 핵심 주장이 깨진다.

계산은 전부 표준 라이브러리 파이썬이다 — `pip install` 없이 동작해야 한다.
`re_api`(`wealth_common.py`)가 `localhost:3001`과 대화하는 유일한 지점이고, 소수(0.039)↔퍼센트(3.9)
변환이 일어나는 유일한 지점이다. 이 이음매를 다른 곳에 복제하지 않는다.
