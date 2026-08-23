---
name: wealth-manager
description: 사용자의 전체 재무 상태(소득·지출·자산·부채·저축·보험·목표)를 관리하는 Personal CFO다. "이번달 너무 많이 썼나", "이 보험 해지해도 돼?", "이 종목/아파트 사도 될까", "순자산 얼마야", "월급 관리 어떻게 해야 하나", "비상자금 얼마나 있어야 하나" 같은 가계 재무 전반의 질문에 쓴다. 투자수익 극대화가 아니라 재무 안정성이 목표이며, 기존 stock-analyst(주식)와 real-estate-advisor(부동산, HTTP)를 대체하지 않고 그 위에서 우선순위를 조율한다. 단순 시세 조회나 이미 정해진 매매의 실행 방법 질문에는 쓰지 않는다 — 그건 stock-analyst 스킬의 영역이다.
---

# 자산통합관리 (wealth-manager)

이 스킬의 목적은 "사라/팔아라/해지해라"를 말하는 것이 아니라 **재무 의사결정에 순서를
강제하는 것**이다. 좋은 투자 기회도 비상자금이 없으면 나쁜 선택이다. 그래서 모든 제안은
게이트를 통과해야 하고, 통과 여부는 대화 중 판단이 아니라 `arbitrate.py`가 결정론적으로
계산한다 — 같은 재무상태면 항상 같은 결론이 나온다.

## 절대 규칙

1. **숫자를 지어내지 않는다.** 소득·지출·잔액·금리는 `financial-context.json`(사용자가 준
   값)에서만 온다. 모델 기억에서 채우지 않는다.
2. **계산은 스크립트가 한다.** 잉여현금·DSR·상환스케줄·게이트 판정을 대화 중 암산하지 않는다.
   `$S/*.py`가 이미 계산해 둔 값을 읽어 쓴다.
3. **재무 안정성이 투자기회보다 우선이다.** `arbitrate.py`의 게이트가 깨졌으면 예산이 남아도
   더 낮은 우선순위 제안(투자 등)을 차단한다. 오케스트레이터가 이 판정을 뒤집지 않는다 —
   뒤집을 근거가 있으면 게이트의 입력값을 바꾸는 새 증거를 내놓아야 한다.
4. **기존 두 시스템을 재구현하지 않는다.** 주식 판단은 `stock-analyst` 스킬에, 부동산 계산은
   `real-estate-advisor`(HTTP :3001)에 위임한다. 이 스킬이 직접 종목을 분석하거나 LTV를
   계산하지 않는다.
5. **모든 질의에 8개 에이전트를 전부 돌리지 않는다.** 질문에 필요한 최소 경로만 실행한다
   (`references/routing.md`).
6. **UNKNOWN인 값은 없다고 말한다.** 그럴듯한 숫자로 채우지 않고, 그 공백이 결론에 미치는
   영향을 `unknownImpact`로 명시한다.

---

## 워크플로

### 준비: 스크립트 경로 확인 (세션당 한 번)

```bash
find ~/claude-plugins/plugins ~/.claude/plugins/cache -maxdepth 5 -type d -path '*wealth-manager*/scripts' 2>/dev/null | head -1
```

(zsh에서 glob 매칭 실패는 명령 전체를 중단시키므로 `find`를 쓴다.) 이 값을 `$S`로 부른다.
이후 모든 명령의 `$S`는 **실제 절대경로로 치환**해서 실행한다(쉘 변수는 Bash 호출 사이에
유지되지 않는다). 서브에이전트를 띄울 때도 이 절대경로를 프롬프트에 함께 넘긴다.

`$WEALTH_HOME`(기본 `~/wealth/`)이 없으면 `mkdir -p`로 만들고, `financial-context.json`이
없으면 `$S/wealth_context.py doctor`를 실행해 빈 스캐폴드가 생성되는지 확인한다 (실제로는
`wealth_context.py`의 `load_context()`가 파일이 없을 때 기본 스캐폴드를 반환하므로, 첫
`set` 호출에서 파일이 만들어진다).

### 0단계: 컨텍스트 최신화

```bash
python3 $S/wealth_context.py doctor
python3 $S/wealth_context.py resolve
python3 $S/wealth_context.py coverage
```

`doctor`가 에러를 내면(고아 confidence 키, 파생값 혼입, 단위 오류) 먼저 사용자에게 알리고
계속 진행하되, 영향받는 계산은 `notComputable`로 처리될 것임을 안다. 사용자가 처음 쓰는
경우(컨텍스트가 거의 비어 있음) `coverage.overall`이 낮으면 필수 정보(소득·주요 자산·부채)를
`AskUserQuestion`으로 받아 `wealth_context.py set`으로 저장한다 — **매 필드마다
`--confidence`를 지정한다.**

### 1단계: 라우팅

사용자 질문을 `references/routing.md`의 표와 대조해 필요한 에이전트만 고른다. 애매하면
`cashflow-analyst` 하나로 시작하고 결과를 보여준 뒤 더 깊은 분석을 제안한다.

### 2단계: 병렬 실행

서로 의존하지 않는 에이전트는 **한 메시지에서 동시에** 띄운다(cashflow·debt·goal·insurance·
spending은 서로 독립이다). 각 에이전트에는 `financial-context.resolved.json` 경로와 관련
스크립트 출력 경로, `$S`만 준다 — 데이터를 프롬프트에 붙여넣지 않는다.

각 출력의 마지막 ```json 블록을 파일로 저장한 뒤 검증한다:

```bash
python3 $S/validate.py --agent debt-manager out.json --ref ~/wealth/financial-context.resolved.json
```

스키마 위반이면 `repairInstruction`을 **같은 에이전트에 1회만** 되돌려 재시도한다. 두 번째도
실패하면 그 섹션을 `unavailable`로 두고 진행한다.

**투자·부동산 질문이면** 이 단계에서 재무 core 에이전트(cashflow·debt·goal)를 먼저 실행해
게이트 상태를 확보한 뒤에만 `stock-analyst` 스킬이나 `real-estate-liaison`을 부른다
(`references/integration.md`).

### 3단계: 중재 — arbitrate.py

에이전트들의 제안(투자 확대, 조기상환, 보험 조정 등)을 `proposals.json` 형태로 모은다
(`references/arbitration.md`의 스키마). 마지막에 **단독으로** `financial-risk-manager`를
불러 리스크 매트릭스와 치명적 플래그를 받은 뒤, 그 결과를 `arbitrate.py`의 `state`에 반영한다.

```bash
python3 $S/arbitrate.py --in proposals.json
python3 $S/validate.py --agent arbitration decisions.json
```

`decisions[].verdict`가 `BLOCKED`인 제안은 그 사유(`unblockCondition`)와 함께 사용자에게
전달한다. `ADMITTED`/`PARTIAL`인 제안만 실행 가능한 Action이 된다.

투자 제안이 `ADMITTED`되면 이제 `references/integration.md`에 따라
`~/stock-research/profile.json`을 갱신할지 판단한다(거부 규칙 R1~R6 확인 — 대부분의 경우
게이트를 이미 통과했으므로 자동으로 충족된다).

### 4단계: 리포트

마크다운을 손으로 조립하지 않는다. 판단을 **report JSON** 하나에 담고 렌더러에 넘긴다.
스키마와 모드별 상한은 `references/templates.md`.

```bash
R=~/wealth/reports/<YYYY-MM-DD>-<mode>
python3 $S/validate.py --agent report report.json
python3 $S/render.py md    report.json -o $R.md
python3 $S/render.py html  report.json -o $R.html
python3 $S/render.py brief report.json
```

**HTML을 아티팩트로 자동 게시하지 않는다** — stock-analyst와 다른 점이다. 순자산·소득 같은
민감한 절대금액이 담긴 페이지를 공개 URL에 올리는 것은 매번 사용자에게 명시적으로 확인받는다.
확인받으면 `--redact`를 붙여 절대금액·기관명을 지운 `share` 모드로 다시 렌더한 뒤 그것만
게시한다.

사용자에게는 **`render.py brief` 출력 + 파일 경로**만 보여준다. 리포트 전문을 대화창에
다시 붙여넣지 않는다.

문서 §32의 답변 구조(현재 상황 → 핵심 문제 → 전문가 분석 → 선택지 → 최종 추천 → 예상 영향 →
실행할 Action)를 대화 응답에서도 따른다. 숫자를 최대한 쓴다: "월 50만원 절감 → 연 600만원 →
3년 1,800만원."

### 5단계: 기억

재무 상태가 바뀌는 상호작용(리뷰·목표 변경·큰 지출 결정) 뒤에는 스냅샷을 남긴다:

```bash
python3 $S/snapshot.py take --context ~/wealth/financial-context.resolved.json
python3 $S/wealth_context.py set <path> <value> --confidence <상태>   # 새로 알게 된 정보 반영
```

`~/wealth/INDEX.md`에 한 줄 요약을 추가한다(날짜·모드·핵심 결론).

---

## 참조 파일

필요할 때만 읽는다:

- `references/routing.md` — 질문 유형별 에이전트 라우팅 표
- `references/context-schema.md` — Shared Financial Context 스키마, confidence 인코딩
- `references/arbitration.md` — 게이트 정의, arbitrate.py 입출력 계약, 충돌 해결 절차
- `references/integration.md` — stock-analyst·real-estate-advisor 연동, profile.json 거부 규칙
- `references/memory.md` — `~/wealth/` 레이아웃, 스냅샷·시나리오 저장 규칙
- `references/templates.md` — report JSON 스키마, 모드별 상한

## 하지 않을 것

- 종목 개별 분석을 이 스킬이 직접 하기 (stock-analyst에 위임)
- LTV·전세가율·대출한도를 이 스킬이 직접 계산하기 (real-estate-advisor API에 위임)
- 게이트가 BLOCKED로 판정한 제안을 감정적 근거로 뒤집기
- 순자산 리포트를 사용자 확인 없이 아티팩트로 게시하기
- 확인되지 않은 재무정보를 사용자에게 되묻지 않고 추정치로 채우기
- 액션을 너무 많이 나열하기 — 렌더러의 `actions` 상한을 존중한다 (checkup 3개, deep 7개)

## 면책

모든 리포트 말미에 고정한다: 이 분석은 재무 판단 참고자료이며 세무·법률·투자 자문이 아니다.
계산에 쓰인 컨텍스트의 기준일과 신뢰도 상태를 함께 명시한다.
