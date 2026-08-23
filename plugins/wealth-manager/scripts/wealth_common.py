"""wealth-manager 공용 유틸 — 경로, confidence 격자, 원/퍼센트 단위 가드, RE API 클라이언트.

파이썬 표준 라이브러리만 사용한다 (pip 설치 없음). stock-analyst/scripts/common.py의
관례(ROOT 환경변수, envelope, 실패도 정상 반환값)를 그대로 따른다.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("WEALTH_HOME", Path.home() / "wealth"))
RE_API_BASE = os.environ.get("RE_API_BASE", "http://localhost:3001")
RE_API_CACHE_TTL = 86400  # 24h — 결정론적 계산이므로 길게 캐시해도 안전하다

CONFIDENCE_ORDER = ["UNKNOWN", "ESTIMATED", "USER_PROVIDED", "VERIFIED"]
CONFIDENCE_RANK = {c: i for i, c in enumerate(CONFIDENCE_ORDER)}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# --------------------------------------------------------------- Computed<T>

def computed(value):
    """RE API의 packages/calculators/src/money.ts::Computed<T>와 와이어 동일.

    {"computable": true, "value": ...} — 필드명은 "computed"가 아니라 "computable"이다.
    """
    return {"computable": True, "value": value}


def not_computable(reason: str):
    return {"computable": False, "reason": reason}


# ------------------------------------------------------------ 단위 가드 (§2.3)

class UnitError(ValueError):
    pass


def assert_won(v, field: str = "amount") -> int:
    """금액은 원 단위 정수. float나 0<|v|<1000(만원 단위 실수 의심)은 거부한다."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise UnitError(f"{field}: 원 단위 정수가 아니다 (받은 값: {v!r})")
    if isinstance(v, float) and not v.is_integer():
        raise UnitError(f"{field}: 원 단위는 정수여야 한다 (받은 값: {v})")
    iv = int(v)
    if 0 < abs(iv) < 1000:
        raise UnitError(
            f"{field}: {iv}는 만원 단위 오류로 보인다 — 원 단위 정수를 쓴다 (예: 500만원 → 5000000)")
    return iv


def assert_ratio(v, field: str = "rate") -> float:
    """비율은 소수. 1.0을 넘으면 퍼센트 수를 잘못 넣은 것으로 본다."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise UnitError(f"{field}: 소수 비율이 아니다 (받은 값: {v!r})")
    fv = float(v)
    if fv > 1.0:
        raise UnitError(
            f"{field}: {fv}를 넘겼는가? 연 {fv}%는 {fv / 100}이다 — 비율은 항상 소수로 쓴다")
    return fv


# ----------------------------------------------------------- confidence 격자

def min_conf(*states: str) -> str:
    """계산값의 confidence = 입력들의 최솟값. 하나라도 UNKNOWN이면 UNKNOWN."""
    states = [s for s in states if s]
    if not states:
        return "UNKNOWN"
    return min(states, key=lambda s: CONFIDENCE_RANK.get(s, -1))


def conf_at_least(state: str, floor: str) -> bool:
    return CONFIDENCE_RANK.get(state, -1) >= CONFIDENCE_RANK.get(floor, 999)


# 순수 식별자/메모 필드 — 계산에 쓰이지 않으므로 confidence 집계에서 제외한다.
# 포함시키면 사용자가 명시적으로 VERIFIED를 준 금액 필드가, 자동 생성되어 아무도
# 등급을 매기지 않은 'id' 필드 하나 때문에 블록 전체가 USER_PROVIDED로 깎인다.
# liquidity·type·category 같은 분류 필드는 잘못되면 계산 자체가 틀리므로 제외하지 않는다.
_NON_SUBSTANTIVE_LEAF_KEYS = {"id", "label", "_note"}


def block_confidence(ctx: dict, effective_leaves: dict, prefix: str) -> str:
    """블록/리스트 전체의 실효 confidence = 그 접두어 아래 모든 (실질) 리프의 min.

    financial-context.resolved.json의 effectiveConfidence는 실제 리프 경로로만
    키가 채워져 있다 ('liabilities#jeonse-loan.balance'는 있어도 'liabilities'는
    없다) — 정확한 키로 조회하면 항상 실패해서 UNKNOWN처럼 보인다. 반드시 접두어
    매칭으로 집계해야 한다.

    해당 접두어 아래 리프가 하나도 없으면(블록이 진짜로 비어 있으면) declared
    default로 내려간다 — "값이 없다"와 "값이 UNKNOWN이다"는 다르다.
    """
    matches = [c for p, c in effective_leaves.items()
               if (p == prefix or p.startswith(prefix + ".") or p.startswith(prefix + "#"))
               and p.rsplit(".", 1)[-1].split("#")[-1] not in _NON_SUBSTANTIVE_LEAF_KEYS]
    if not matches:
        return resolve_confidence(ctx, prefix)
    return min_conf(*matches)


# --------------------------------------------------------------- 점경로 유틸

def resolve_path(obj, path: str):
    """financial-context 점경로 해석. '#id' 세그먼트로 리스트 원소를 찾는다.

    'liabilities#jeonse-loan.balance' → liabilities 리스트에서 id=='jeonse-loan'인
    원소의 balance. '[n]' 형태의 숫자 인덱스도 지원하지만 재정렬에 취약해 권장하지 않는다.
    """
    cur = obj
    for part in path.split("."):
        if "#" in part:
            key, ident = part.split("#", 1)
            cur = cur.get(key) if isinstance(cur, dict) else None
            if not isinstance(cur, list):
                return None
            match = next((x for x in cur if isinstance(x, dict) and str(x.get("id")) == ident), None)
            cur = match
        elif part.startswith("[") and part.endswith("]"):
            idx = part[1:-1]
            if not idx.lstrip("-").isdigit() or not isinstance(cur, list):
                return None
            try:
                cur = cur[int(idx)]
            except IndexError:
                return None
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


# ------------------------------------------------------- confidence 리졸버

def resolve_confidence(context: dict, path: str) -> str:
    """정확한 경로 → 가장 가까운 상위 접두어 → defaults → UNKNOWN."""
    table = context.get("confidence") or {}
    if path in table:
        return table[path]
    parts = path.split(".")
    for i in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in table:
            return table[prefix]
    return (context.get("defaults") or {}).get("confidence", "UNKNOWN")


def resolve_as_of(context: dict, path: str) -> str | None:
    table = context.get("asOf") or {}
    if path in table:
        return table[path]
    parts = path.split(".")
    for i in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in table:
            return table[prefix]
    return (context.get("defaults") or {}).get("asOf")


def resolve_staleness_days(context: dict, path: str) -> int | None:
    table = context.get("staleness") or {}
    if path in table:
        return table[path]
    parts = path.split(".")
    for i in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in table:
            return table[prefix]
    return None


def effective_confidence(context: dict, path: str, as_of_override: str | None = None) -> str:
    """선언 confidence에 staleness 감쇠를 적용한다.

    now - asOf > staleness  → VERIFIED→ESTIMATED, ESTIMATED→UNKNOWN
    now - asOf > 3*staleness → 추가 감쇠(ESTIMATED→UNKNOWN, USER_PROVIDED→ESTIMATED)
    """
    declared = resolve_confidence(context, path)
    as_of = as_of_override or resolve_as_of(context, path)
    staleness = resolve_staleness_days(context, path)
    if not as_of or not staleness:
        return declared
    try:
        age_days = (datetime.now() - datetime.strptime(as_of, "%Y-%m-%d")).days
    except ValueError:
        return declared
    rank = CONFIDENCE_RANK.get(declared, 0)
    if age_days > staleness:
        rank = max(0, rank - 1)
    if age_days > 3 * staleness:
        rank = max(0, rank - 1)
    return CONFIDENCE_ORDER[rank]


# ------------------------------------------------------------------- 응답 봉투

def envelope(script: str, data: dict, *, assumptions=None, not_computable_list=None,
             warnings=None, input_confidence: str = "VERIFIED",
             input_confidence_by_field: dict | None = None, context_hash: str | None = None) -> dict:
    return {
        "ok": True,
        "script": script,
        "generatedAt": now_iso(),
        "contextHash": context_hash,
        "inputConfidence": {"min": input_confidence, "byField": input_confidence_by_field or {}},
        "assumptions": assumptions or [],
        "notComputable": not_computable_list or [],
        "warnings": warnings or [],
        "data": data,
    }


def context_hash(context: dict) -> str:
    blob = json.dumps(context, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


# ------------------------------------------------------------------- 파일 IO

def load_json(path: Path | str) -> dict:
    return json.loads(Path(path).read_text())


def write_json(path: Path | str, obj: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    return path


# --------------------------------------------------------- RE API 클라이언트
#
# localhost:3001과 대화하는 유일한 지점. 이 파일 밖에서 소수↔퍼센트 변환을
# 하지 않는다 — 우리 컨텍스트는 요율을 소수(0.039)로, RE API는 퍼센트(3.9)로
# 받는다. 이 어댑터가 그 이음매를 한 곳에 가둔다.

def _re_api_cache_path(request_key: str) -> Path:
    digest = hashlib.sha1(request_key.encode("utf-8")).hexdigest()
    return ROOT / "cache" / "calc" / f"{digest}.json"


def _re_api_post(path: str, body: dict, *, use_cache: bool = True):
    key = f"{path}:{json.dumps(body, sort_keys=True)}"
    cache_path = _re_api_cache_path(key)
    if use_cache and cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age <= RE_API_CACHE_TTL:
            try:
                return json.loads(cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

    url = f"{RE_API_BASE}{path}"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError, OSError):
        return None

    if use_cache:
        write_json(cache_path, result)
    return result


def re_api_dsr(annual_income: float | None, debts: list[dict]):
    """POST /calculator/dsr. annualRate는 소수 → 퍼센트로 변환해서 보낸다."""
    body = {
        "annualIncome": annual_income,
        "debts": [
            {
                "annualInterestRatePercent": round(d["annualRatePercent"] * 100, 4)
                if "annualRatePercent" in d else round(d["annualRate"] * 100, 4),
                "balance": d.get("balance"),
                "monthlyPayment": d.get("monthlyPayment"),
                "remainingMonths": d.get("remainingMonths"),
                "isMortgage": d.get("isMortgage", False),
            }
            for d in debts
        ],
    }
    result = _re_api_post("/calculator/dsr", body)
    if result is None:
        return not_computable("계산 API(localhost:3001) 미응답 — DSR을 계산할 수 없다. "
                               "real-estate-advisor API가 실행 중인지 확인한다 (pnpm --filter @rea/api start).")
    return result


def re_api_repayment(deposit_or_balance: float, annual_rate: float, term_months: int,
                      repayment_type: str = "INTEREST_ONLY"):
    """상환 스케줄. /calculator/loan은 전세대출 모양(deposit + loanAmount)이라
    balance를 deposit이자 loanAmount로 동시에 넘기는 어댑터 shim을 쓴다."""
    body = {
        "deposit": deposit_or_balance,
        "loanAmount": deposit_or_balance,
        "annualInterestRatePercent": round(annual_rate * 100, 4),
        "termMonths": term_months,
        "repaymentType": repayment_type,
    }
    result = _re_api_post("/calculator/loan", body)
    if result is None:
        return not_computable("계산 API(localhost:3001) 미응답 — 상환 스케줄을 계산할 수 없다.")
    return result


def re_api_ltv(loan_amount: float, collateral_value: float):
    result = _re_api_post("/calculator/ltv", {"loanAmount": loan_amount, "collateralValue": collateral_value})
    if result is None:
        return not_computable("계산 API(localhost:3001) 미응답 — LTV를 계산할 수 없다.")
    return result


def re_api_analyze(query: str, context: dict | None = None, conversation_facts: list | None = None):
    """POST /analysis — 부동산 종합 분석. mergeContext()가 여기 context를 LLM 추출값보다
    우선하므로, 자연어→구조화는 여기서(오케스트레이터/liaison 에이전트가) 직접 하고
    :3001의 내장 MockLlmProvider 정규식 분류기에 의존하지 않는다."""
    body = {"query": query}
    if context:
        body["context"] = context
    if conversation_facts:
        body["conversationFacts"] = conversation_facts
    result = _re_api_post("/analysis", body, use_cache=False)
    if result is None:
        return not_computable("계산 API(localhost:3001) 미응답 — 부동산 분석을 수행할 수 없다. "
                               "real-estate-advisor API가 실행 중인지 확인한다 (pnpm --filter @rea/api start).")
    return result


def re_api_strategy(funding_candidates: list, user_profile: dict | None = None, property_: dict | None = None):
    """POST /analysis/strategy — LLM 없이 결정론적으로 자금조달안을 비교한다."""
    body = {"fundingCandidates": funding_candidates}
    if user_profile:
        body["userProfile"] = user_profile
    if property_:
        body["property"] = property_
    result = _re_api_post("/analysis/strategy", body, use_cache=False)
    if result is None:
        return not_computable("계산 API(localhost:3001) 미응답 — 자금조달 전략 비교를 수행할 수 없다.")
    return result


def re_api_health() -> dict | None:
    req = urllib.request.Request(f"{RE_API_BASE}/health")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError, OSError):
        return None
