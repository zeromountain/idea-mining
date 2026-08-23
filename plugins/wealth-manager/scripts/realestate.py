#!/usr/bin/env python3
"""real-estate-advisor(localhost:3001) 호출 CLI — real-estate-liaison 에이전트 전용.

이 파일 밖에서 :3001에 직접 요청하지 않는다. LTV/DSR/원리금 순수 계산기는
wealth_common.re_api_ltv/dsr/repayment로 이미 debt.py·cashflow.py가 쓰고 있으니,
여기서는 종합 분석(/analysis)과 자금조달 전략 비교(/analysis/strategy)만 다룬다.

CLI:
  python3 realestate.py health
  python3 realestate.py analyze --in analyze.json     # {"query": "...", "context": {...}}
  python3 realestate.py strategy --in strategy.json   # {"fundingCandidates": [...], ...}
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wealth_common as wc


def cmd_health(args) -> int:
    result = wc.re_api_health()
    if result is None:
        wc.emit({"ok": False, "reachable": False,
                "note": "localhost:3001 미응답 — real-estate-advisor API가 꺼져 있다"})
        return 1
    wc.emit({"ok": True, "reachable": True, "health": result})
    return 0


def cmd_analyze(args) -> int:
    inp = wc.load_json(args.in_file)
    result = wc.re_api_analyze(inp["query"], inp.get("context"), inp.get("conversationFacts"))
    wc.emit(wc.envelope("realestate.py analyze", {"result": result}))
    return 0


def cmd_strategy(args) -> int:
    inp = wc.load_json(args.in_file)
    result = wc.re_api_strategy(inp.get("fundingCandidates", []), inp.get("userProfile"), inp.get("property"))
    wc.emit(wc.envelope("realestate.py strategy", {"result": result}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("health")
    p1.set_defaults(func=cmd_health)

    p2 = sub.add_parser("analyze")
    p2.add_argument("--in", dest="in_file", required=True)
    p2.set_defaults(func=cmd_analyze)

    p3 = sub.add_parser("strategy")
    p3.add_argument("--in", dest="in_file", required=True)
    p3.set_defaults(func=cmd_strategy)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
