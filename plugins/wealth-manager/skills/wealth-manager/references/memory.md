# 저장 구조 — `~/wealth/`

`WEALTH_HOME` 환경변수로 위치를 바꿀 수 있다(기본 `~/wealth/`). `chmod 700`을 권장하고
git으로 추적하지 않는다.

```
~/wealth/
├── INDEX.md                                리뷰 이력 한 줄 요약        [오케스트레이터 append]
├── financial-context.json                  정본 — 사용자가 주장한 사실만 [wealth_context.py 전용]
├── financial-context.resolved.json         파생 — confidence 해소·합계   [resolve 명령 소유]
├── categories.json                         거래 분류 규칙               [사용자 편집]
├── transactions/
│   ├── raw/<YYYY-MM>-<source>.csv          카드·은행 원본               [사용자 소유, 읽기 전용]
│   └── <YYYY-MM>.normalized.json           정규화 거래                 [spending.py ingest 소유]
├── insurance/policies.json                 특약 상세 (길면 분리)
├── snapshots/<YYYY-MM>.json                순자산 스냅샷 — append-only [snapshot.py take 소유]
├── scenarios/<slug>.json                   시나리오 정의               [사용자/에이전트 작성]
├── scenarios/results/<slug>-<날짜>.json    시나리오 실행 결과          [scenario.py 소유]
├── cache/calc/<sha1>.json                  :3001 응답 캐시 (TTL 24h)   [wealth_common.re_api 소유]
├── reports/<YYYY-MM-DD>-<모드>.{json,md,html}  리포트 3종
└── runs/<YYYY-MM-DD>-<모드>.jsonl          실행·중재·override 로그     [오케스트레이터 append]
```

## `financial-context.resolved.json`을 왜 따로 두는가

정본에는 사용자가 실제로 진술한 것만 남긴다. confidence 상속·감쇠·합계는 전부 파생 파일에만
있다 — "내가 말한 것"과 "시스템이 결론낸 것"을 항상 diff할 수 있어야 confidence가 감사
가능해진다. 계산 스크립트는 전부 `.resolved.json`을 읽는다, 정본을 직접 읽지 않는다.

## 스냅샷은 append-only다

정정은 **새 레코드**에 `corrects: "2026-07"`을 다는 것이지 기존 파일을 고치는 게 아니다.
`snapshot.py take --corrects 2026-08`은 `2026-08-correction-<오늘날짜>.json`을 새로 만든다.
소급 수정되는 시계열은 "언제 판단이 바뀌었나"에 답할 수 없다.

## `transactions/raw/`는 사용자 소유다

스크립트가 이 안의 파일을 쓰지 않는다. CSV가 잘못됐으면 고치는 게 아니라 새로 내보내게 한다.

## 리포트를 아티팩트로 자동 게시하지 않는다

stock-analyst와 가장 크게 다른 점이다. 순자산 리포트가 공개 URL에 놓이는 것은 주식 리포트와
범주가 다른 실수다. 게시가 필요하면 매번 `AskUserQuestion`으로 확인받고, `--redact`가 붙은
`share` 모드로 다시 렌더한 결과만 올린다.

## `runs/*.jsonl` — 실행 로그

한 줄에 하나: 어떤 에이전트가 실행됐는지, 스키마 검증 결과, `arbitrate.py`의 게이트 상태,
override가 있었는지. 사후 검증(이 결정이 옳았는가)은 v1 범위 밖이지만, 이 로그가 있어야
나중에라도 그 검증이 가능해진다.
