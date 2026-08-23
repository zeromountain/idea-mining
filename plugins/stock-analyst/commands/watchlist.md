---
description: 관심 종목을 등록·조회·삭제한다
argument-hint: [add|list|remove] [티커], 예: add NVDA / list / remove PLTR
---

`stock-analyst` 스킬의 watchlist를 다룬다. 입력: **$ARGUMENTS**

`~/stock-research/watchlist.json`을 읽고 쓴다. 스키마는 `references/memory.md` 참고.

- `add <티커>` — 현재 시세를 조회해 등록한다. 저장된 Thesis가 있으면 연결한다.
- `list` — 등록 종목의 현재가, 등록 시점 대비 변동, 저장된 Rating을 표로 보여준다.
- `remove <티커>` — 삭제한다. Thesis 파일은 지우지 않는다 (기록은 남긴다).

인자가 없으면 `list`로 동작한다.
