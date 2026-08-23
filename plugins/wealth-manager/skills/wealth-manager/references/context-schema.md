# Shared Financial Context

`~/wealth/financial-context.json`이 정본이다. **사용자가 실제로 진술한 값만** 여기 들어간다.
파생값(순자산, 저축률, 월소득 합계 등)은 여기 살 수 없다 — `wealth_context.py resolve`가 만드는
`financial-context.resolved.json`의 `_derived.totals`에만 있다. `wealth_context.py doctor`가
이 규칙 위반을 에러로 잡는다.

## 블록

```
profile            나이·가구원수·고용형태·주거상태
income             primary(주소득) · secondary[](부소득) · irregular[](비정기, 상여 등)
assets             cash · savings · deposits · investments · retirement · realEstate · other
liabilities        [] (대출 목록)
monthlyExpenses    fixed[] · variable[] · savingsAuto[](자동이체 저축) · annualLumpy[](연 1회성)
insurance          policies[] · assumptions(보장공백 계산용 가정)
goals              []
riskProfile        자기신고 위험감내도·최대낙폭·비상자금 목표개월
upcomingEvents     []
```

전체 필드는 `$S/wealth_context.py show`(전체) 또는 `--block <이름>`으로 확인한다. 새 필드가
필요하면 `wealth_context.py set <점경로> <값> --confidence <상태>`로 추가한다 — JSON을 직접
편집하지 않는다(confidence·asOf가 같이 기록되지 않는다).

## 단위 규칙 — 이 문서에서 가장 중요한 부분

- **금액은 항상 원 단위 정수.** `500만원`이 아니라 `5000000`. `wealth_context.py doctor`가
  `0 < |v| < 1000`을 만원 단위 오류로 거부한다.
- **비율은 항상 소수.** 연 3.9%는 `0.039`. `doctor`가 `v > 1.0`을 퍼센트 오기입으로 거부한다.
  `real-estate-advisor` API는 반대로 퍼센트 수를 받는다(`3.9`) — 이 변환은
  `wealth_common.py`의 `re_api_*` 함수 안에서만 일어난다. 다른 곳에서 직접 변환하지 않는다.

## Confidence — VERIFIED / USER_PROVIDED / ESTIMATED / UNKNOWN

값마다 객체로 감싸지 않는다. `confidence` 블록에 **점경로 → 상태**를 평면으로 적는다:

```json
"defaults":  {"confidence": "USER_PROVIDED", "asOf": "2026-08-23"},
"confidence": {"income.primary.monthlyNet": "VERIFIED", "assets.investments": "ESTIMATED"},
"asOf":      {"assets.investments": "2026-08-20"},
"staleness": {"income": 180, "assets": 90, "liabilities": 90}
```

해석 순서: **정확한 경로 → 가장 가까운 상위 접두어 → defaults → UNKNOWN.** 블록당 한 줄만
쓰고 예외만 개별 덮어쓰면 된다 — `assets: "USER_PROVIDED"` 하나로 `assets.*` 전체를 덮고,
`assets.investments`만 다르면 그 줄만 추가한다.

`wealth_context.py resolve`가 `staleness`를 넘긴 값을 자동 감쇠시킨다(VERIFIED→ESTIMATED→
UNKNOWN). **계산은 항상 `effectiveConfidence`(감쇠 적용 후)를 쓴다**, 선언된 confidence를
그대로 쓰지 않는다.

`null`은 UNKNOWN, 키 자체가 없으면 NOT_APPLICABLE — 다르다. `set`으로 값을 쓸 때
`--confidence`는 필수다.

## 라벨 매핑 — 에이전트 서술에 쓰는 FACT/ESTIMATE/ASSUMPTION/OPINION

| context confidence | 에이전트 라벨 |
|---|---|
| VERIFIED | `FACT` |
| USER_PROVIDED | `FACT (출처: 사용자 진술)` |
| ESTIMATED | `ESTIMATE` |
| UNKNOWN | 주장 불가 — `unknownImpact`에만 적는다 |

## 참조 무결성

`liabilities[]`·`goals[]`의 `id`는 유일해야 한다. `goals[].fundedFrom`은
`assets.<카테고리>#<id>` 형태로 실재하는 자산을 가리켜야 한다. `wealth_context.py doctor`가
이 둘을 검증한다 — 리포트를 만들기 전에 항상 한 번 돌린다.
