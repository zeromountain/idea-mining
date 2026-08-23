# Report JSON 스키마 · 모드별 상한

리포트를 손으로 조립하지 않는다. 판단을 이 스키마에 담아 `$S/render.py`에 넘긴다.

```json
{
  "mode": "checkup",
  "asOf": "2026-08-23",
  "verdict": {"confidence": "MEDIUM", "headline": "비상자금 부족과 고금리 부채가 겹쳐 이번 달은 투자·조기상환 모두 보류한다"},
  "snapshot": {"netWorth": -80000000, "liquidAssets": 20000000},
  "decisionTable": { "...arbitrate.py 출력 그대로..." },
  "sections": [
    {"title": "현금흐름", "body": "문단. **굵게**, FACT 같은 라벨을 쓸 수 있다."}
  ],
  "actions": ["비상자금부터 채운다", "15% 대출 갚을 여유자금이 생기면 우선 상환한다"],
  "risks": [{"severity": "high", "name": "유동성", "note": "비상자금 2.1개월"}],
  "unknowns": ["부채 커버리지가 60%뿐이라 다른 고금리 부채가 있을 수 있다"],
  "dataBasis": ["financial-context.resolved.json", "cashflow.py", "arbitrate.py"]
}
```

`validate.py --agent report`가 이 스키마를 검증한다.

## 값 규칙

- 금액은 원 단위 정수 그대로(`"8,000만원"`이 아니라 `80000000`). 렌더러가 `fmt.money()`로
  표시를 통일한다.
- 비율은 소수(`0.039`). 렌더러가 퍼센트로 바꾼다.
- `sections[].body`만 자유 서술이다. 나머지는 구조화 필드다 — 여기가 형식이 흔들리지 않는
  이유다.

## 모드별 상한 (`render.py`의 `MODE_SPEC`)

| mode | sections | **actions** | risks | body | scenarios | showsAmounts |
|---|---:|---:|---:|---:|---|---|
| `checkup` | 4 | 3 | 3 | 420자 | — | ✓ |
| `deep` | 무제한 | 7 | 9 | 무제한 | ✓ | ✓ |
| `cashflow` | 3 | 3 | 3 | 500자 | — | ✓ |
| `spending` | 4 | 5 | 3 | 600자 | — | ✓ |
| `debt` | 4 | 4 | 5 | 600자 | ✓ | ✓ |
| `insurance` | 3 | 4 | 4 | 500자 | — | ✓ |
| `goal` | 3 | 4 | 4 | 500자 | ✓ | ✓ |
| `scenario` | 3 | 3 | 5 | 600자 | ✓ | ✓ |
| `networth` | 2 | 2 | 2 | 350자 | — | ✓ |
| `share` | 2 | 3 | 2 | 300자 | — | **✗ (--redact 강제)** |

**`actions` 상한이 stock-analyst에 없던 것이다.** 문서 §29 "사용자가 행동하기 어려울 정도로
많은 Action을 제공하지 않는다"를 강제한다 — 액션 14개짜리 리포트는 액션이 0개다. 넘치면
렌더러가 자르고 경고를 남긴다(조용히 버리지 않는다).

## 절대 자르지 않는 두 블록

- **`decisionTable`** — arbitrate.py의 게이트·판정 표. 판단 근거의 핵심이라 상한을 적용하지 않는다.
- **`unknowns`** — "이 판단이 모르고 있는 것". 여기를 자르면 그 자체가 침묵이 된다.

## `--redact` / `share` 모드

절대금액(`netWorth`, `liquidAssets` 등)을 스냅샷에서 제거하고 `_redacted: true`를 단다.
본문 자유서술(`sections[].body`)에 남아있을 금액은 정규식으로 지우지 않는다 — 오탐(전화번호
등)이 더 위험하다. 대신 `_redactionNote`로 게시 전 직접 확인하라고 경고한다.

## 브리핑

대화창에는 `render.py brief` 출력(≤12줄)과 파일 경로만 보여준다. 전문을 다시 붙여넣지 않는다.
