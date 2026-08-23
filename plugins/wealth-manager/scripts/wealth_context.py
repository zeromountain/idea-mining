#!/usr/bin/env python3
"""~/wealth/financial-context.json 읽기·쓰기·검증·해소.

이 스크립트가 financial-context.json에 쓰는 유일한 통로다. `set`은 confidence를
필수로 요구한다 — 그래야 평면 confidence 블록이 시간이 지나며 썩지 않는다.

CLI:
  wealth_context.py show [--block income] [--human]
  wealth_context.py get income.primary.monthlyNet
  wealth_context.py set assets.cash#main.amount 8000000 --confidence VERIFIED --as-of 2026-08-23
  wealth_context.py resolve [-o financial-context.resolved.json]
  wealth_context.py doctor [--strict]
  wealth_context.py coverage
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import wealth_common as wc

CONTEXT_PATH = wc.ROOT / "financial-context.json"
RESOLVED_PATH = wc.ROOT / "financial-context.resolved.json"

BLOCKS = ["profile", "income", "assets", "liabilities", "monthlyExpenses",
          "insurance", "goals", "riskProfile", "upcomingEvents"]

AMOUNT_HINTS = ("amount", "balance", "premium", "payment", "price", "deposit",
                "cost", "contribution", "value", "impact", "networth", "salary", "benefit")
RATE_HINTS = ("rate", "ratio", "tolerance", "drawdown", "fee", "volatility")

DEFAULT_CONTEXT = {
    "schemaVersion": 1,
    "updatedAt": None,
    "currency": "KRW",
    "profile": {},
    "income": {"primary": {}, "secondary": [], "irregular": []},
    "assets": {"cash": [], "savings": [], "deposits": [], "investments": [],
               "retirement": [], "realEstate": [], "other": []},
    "liabilities": [],
    "monthlyExpenses": {"fixed": [], "variable": [], "savingsAuto": [], "annualLumpy": []},
    "insurance": {"policies": [], "assumptions": {}},
    "goals": [],
    "riskProfile": {},
    "upcomingEvents": [],
    "defaults": {"confidence": "USER_PROVIDED", "asOf": None},
    "confidence": {},
    "asOf": {},
    "staleness": {"income": 180, "assets": 90, "liabilities": 90, "monthlyExpenses": 90,
                  "insurance": 180, "goals": 90, "riskProfile": 365},
}


def load_context() -> dict:
    if not CONTEXT_PATH.exists():
        return json.loads(json.dumps(DEFAULT_CONTEXT))
    return wc.load_json(CONTEXT_PATH)


def save_context(ctx: dict) -> None:
    ctx["updatedAt"] = wc.today()
    wc.write_json(CONTEXT_PATH, ctx)


# ------------------------------------------------------------------- set

def _parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def set_path(ctx: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = ctx
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        if "#" in part:
            key, ident = part.split("#", 1)
            lst = cur.setdefault(key, [])
            if not isinstance(lst, list):
                raise ValueError(f"{key}는 리스트가 아니다 — #id 경로를 쓸 수 없다")
            match = next((x for x in lst if isinstance(x, dict) and str(x.get("id")) == ident), None)
            if match is None:
                match = {"id": ident}
                lst.append(match)
            if is_last:
                if isinstance(value, dict):
                    match.update(value)
                else:
                    raise ValueError(
                        f"{path}는 리스트 원소 전체다 — 값은 JSON 객체여야 한다 (받은 값: {value!r})")
                return
            cur = match
        else:
            if is_last:
                cur[part] = value
                return
            nxt = cur.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[part] = nxt
            cur = nxt


def cmd_set(args) -> int:
    ctx = load_context()
    value = _parse_value(args.value)
    try:
        set_path(ctx, args.path, value)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    ctx.setdefault("confidence", {})[args.path] = args.confidence
    if args.as_of:
        ctx.setdefault("asOf", {})[args.path] = args.as_of
    else:
        ctx.setdefault("asOf", {})[args.path] = wc.today()
    if args.note:
        set_path(ctx, args.path.rsplit(".", 1)[0] + "._note" if "." in args.path else "_note", args.note)
    save_context(ctx)
    print(json.dumps({"ok": True, "path": args.path, "value": value,
                       "confidence": args.confidence, "asOf": ctx["asOf"].get(args.path)},
                      ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------- get/show

def cmd_get(args) -> int:
    ctx = load_context()
    value = wc.resolve_path(ctx, args.path)
    result = {
        "path": args.path,
        "value": value,
        "declaredConfidence": wc.resolve_confidence(ctx, args.path),
        "effectiveConfidence": wc.effective_confidence(ctx, args.path),
        "asOf": wc.resolve_as_of(ctx, args.path),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _human_money(v) -> str:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return str(v)
    a = abs(v)
    neg = "-" if v < 0 else ""
    if a >= 1e8:
        return f"{neg}{a / 1e8:,.1f}억원"
    if a >= 1e4:
        return f"{neg}{a / 1e4:,.0f}만원"
    return f"{neg}{a:,.0f}원"


def cmd_show(args) -> int:
    ctx = load_context()
    blocks = [args.block] if args.block else BLOCKS
    if not args.human:
        out = {b: ctx.get(b) for b in blocks} if args.block else ctx
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    for block in blocks:
        print(f"## {block}")
        for path, value in _walk_leaves(ctx.get(block), block):
            if isinstance(value, (int, float)) and not isinstance(value, bool) and \
                    any(h in path.lower() for h in AMOUNT_HINTS):
                shown = _human_money(value)
            else:
                shown = value
            conf = wc.effective_confidence(ctx, path)
            print(f"  {path} = {shown}  [{conf}]")
    return 0


# ------------------------------------------------------------------- resolve

def _sum(items, field) -> int:
    return sum(int(x.get(field) or 0) for x in items if isinstance(x, dict))


def compute_totals(ctx: dict) -> dict:
    income = ctx.get("income") or {}
    primary = (income.get("primary") or {}).get("monthlyNet") or 0
    secondary = _sum(income.get("secondary") or [], "monthlyNetAvg")
    irregular_annual = _sum(income.get("irregular") or [], "annualAmount")
    monthly_net_total = primary + secondary + round(irregular_annual / 12)

    assets = ctx.get("assets") or {}
    asset_totals, liquid_total = {}, 0
    for cat in ("cash", "savings", "deposits", "investments", "retirement", "realEstate", "other"):
        items = assets.get(cat) or []
        cat_total = _sum(items, "amount")
        asset_totals[cat] = cat_total
        liquid_total += sum(int(x.get("amount") or 0) for x in items
                             if isinstance(x, dict) and x.get("liquidity") in ("IMMEDIATE", "T_PLUS_2"))
    total_assets = sum(asset_totals.values())

    liabilities = ctx.get("liabilities") or []
    total_liabilities = _sum(liabilities, "balance")
    monthly_debt_service = _sum(liabilities, "monthlyPayment")

    exp = ctx.get("monthlyExpenses") or {}
    fixed_total = _sum(exp.get("fixed") or [], "amount")
    variable_total = _sum(exp.get("variable") or [], "monthlyAvg")
    savings_auto_total = _sum(exp.get("savingsAuto") or [], "amount")
    lumpy_annual = _sum(exp.get("annualLumpy") or [], "amount")
    lumpy_monthly_equiv = round(lumpy_annual / 12)

    insurance_total = _sum((ctx.get("insurance") or {}).get("policies") or [], "monthlyPremium")

    return {
        "income": {"monthlyNetTotal": monthly_net_total, "secondaryMonthly": secondary,
                   "irregularMonthlyEquivalent": round(irregular_annual / 12)},
        "assets": {"byCategory": asset_totals, "totalAssets": total_assets, "liquidAssets": liquid_total},
        "liabilities": {"totalBalance": total_liabilities, "monthlyDebtService": monthly_debt_service},
        "monthlyExpenses": {"fixedTotal": fixed_total, "variableTotal": variable_total,
                            "savingsAutoTotal": savings_auto_total,
                            "annualLumpyMonthlyEquivalent": lumpy_monthly_equiv},
        "insurance": {"monthlyPremiumTotal": insurance_total},
        "netWorth": total_assets - total_liabilities,
    }


def _walk_leaves(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            path = f"{prefix}.{k}" if prefix else k
            yield from _walk_leaves(v, path)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, dict) and "id" in item:
                path = f"{prefix}#{item['id']}"
            else:
                path = f"{prefix}[{i}]"
            yield from _walk_leaves(item, path)
    else:
        yield (prefix, obj)


def cmd_resolve(args) -> int:
    ctx = load_context()
    leaves = list(_walk_leaves({b: ctx.get(b) for b in BLOCKS}))
    effective = {path: wc.effective_confidence(ctx, path) for path, _ in leaves if path}

    resolved = json.loads(json.dumps(ctx))
    resolved["effectiveConfidence"] = effective
    resolved["_derived"] = {"totals": compute_totals(ctx), "generatedAt": wc.now_iso()}
    resolved["contextHash"] = wc.context_hash(ctx)

    out_path = Path(args.out) if args.out else RESOLVED_PATH
    wc.write_json(out_path, resolved)
    print(json.dumps({"ok": True, "out": str(out_path), "contextHash": resolved["contextHash"],
                       "netWorth": resolved["_derived"]["totals"]["netWorth"]},
                      ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------- doctor

def cmd_doctor(args) -> int:
    ctx = load_context()
    errors, warnings = [], []

    leaves = list(_walk_leaves({b: ctx.get(b) for b in BLOCKS}))
    leaf_paths = {p for p, _ in leaves if p}

    for path, value in leaves:
        if not path or isinstance(value, (bool, str, type(None), dict, list)):
            continue
        last = path.rsplit(".", 1)[-1].split("#")[-1].lower()
        try:
            if any(h in last for h in AMOUNT_HINTS):
                wc.assert_won(value, path)
            elif any(h in last for h in RATE_HINTS):
                wc.assert_ratio(value, path)
        except wc.UnitError as exc:
            errors.append(str(exc))

    # 파생값이 정본에 섞여 들어오지 않았는지 (문서 §2.3)
    forbidden_top = {"netWorth", "totalAssets", "monthlyNetTotal", "savingsRate"}
    for block in BLOCKS:
        b = ctx.get(block)
        if isinstance(b, dict):
            hit = forbidden_top & set(b.keys())
            if hit:
                errors.append(f"{block}에 파생값이 정본에 섞여 있다: {', '.join(sorted(hit))} "
                               f"— resolve 결과에만 있어야 한다")

    # confidence 고아 키 (병렬 트리 대신 평면 블록을 쓴 이유가 이 검사다)
    for key in ctx.get("confidence") or {}:
        if not any(p == key or p.startswith(key + ".") or p.startswith(key + "#") for p in leaf_paths):
            errors.append(f"고아 confidence 키: '{key}' — 해당하는 컨텍스트 노드가 없다")

    # null 리프가 confidence에 정확히 매칭되면 모순 (규칙 3)
    leaf_value = dict(leaves)
    for key in ctx.get("confidence") or {}:
        if key in leaf_value and leaf_value[key] is None:
            errors.append(f"'{key}'는 값이 null(UNKNOWN)인데 confidence가 선언돼 있다 — 모순")

    # id 유일성 · 참조 무결성
    for block_name, block in (("liabilities", ctx.get("liabilities")),
                               ("goals", ctx.get("goals"))):
        ids = [x.get("id") for x in (block or []) if isinstance(x, dict)]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            errors.append(f"{block_name}에 중복 id: {', '.join(sorted(str(d) for d in dup))}")

    goal_asset_refs = []
    for g in ctx.get("goals") or []:
        goal_asset_refs += g.get("fundedFrom") or []
    asset_ids = set()
    for cat in (ctx.get("assets") or {}).values():
        if isinstance(cat, list):
            asset_ids |= {x.get("id") for x in cat if isinstance(x, dict)}
    for ref in goal_asset_refs:
        ref_id = ref.split("#", 1)[-1] if "#" in ref else ref
        if ref_id not in asset_ids:
            warnings.append(f"goals[].fundedFrom 참조가 존재하지 않는 자산을 가리킨다: {ref}")

    ok = not errors and (not warnings or not args.strict)
    result = {"ok": ok, "errors": errors, "warnings": warnings}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ok else 1


# ------------------------------------------------------------------- coverage

def cmd_coverage(args) -> int:
    ctx = load_context()
    by_block = {}
    for block in BLOCKS:
        leaves = [(p, v) for p, v in _walk_leaves(ctx.get(block), block) if p]
        total = len(leaves) or 1
        present = sum(1 for _, v in leaves if v is not None)
        confs = [wc.effective_confidence(ctx, p) for p, v in leaves if v is not None]
        weakest = min(confs, key=lambda c: wc.CONFIDENCE_RANK.get(c, -1)) if confs else "UNKNOWN"
        by_block[block] = {"ratio": round(present / total, 3), "present": present,
                            "total": total, "weakest": weakest}
    overall = round(sum(b["ratio"] for b in by_block.values()) / len(by_block), 3) if by_block else 0.0
    print(json.dumps({"byBlock": by_block, "overall": overall}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="wealth financial-context 관리")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show")
    p_show.add_argument("--block", choices=BLOCKS)
    p_show.add_argument("--human", action="store_true")
    p_show.set_defaults(func=cmd_show)

    p_get = sub.add_parser("get")
    p_get.add_argument("path")
    p_get.set_defaults(func=cmd_get)

    p_set = sub.add_parser("set")
    p_set.add_argument("path")
    p_set.add_argument("value")
    p_set.add_argument("--confidence", required=True,
                        choices=["VERIFIED", "USER_PROVIDED", "ESTIMATED", "UNKNOWN"])
    p_set.add_argument("--as-of")
    p_set.add_argument("--note")
    p_set.set_defaults(func=cmd_set)

    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("-o", "--out")
    p_resolve.set_defaults(func=cmd_resolve)

    p_doctor = sub.add_parser("doctor")
    p_doctor.add_argument("--strict", action="store_true")
    p_doctor.set_defaults(func=cmd_doctor)

    p_cov = sub.add_parser("coverage")
    p_cov.set_defaults(func=cmd_coverage)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
