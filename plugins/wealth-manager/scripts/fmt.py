"""리포트 수치 포맷 — stock-analyst/scripts/fmt.py와 같은 역할.

에이전트가 각자 포맷하면 "1,200만원", "12,000,000원", "1.2천만원"이 한 리포트 안에
동시에 나온다. 비교가 안 되는 가장 큰 이유라 여기로 모았다.
"""
from __future__ import annotations

DASH = "—"

GATE_STATUS_TONE = {"OPEN": "pos", "BREACHED": "neg", "UNKNOWN": "unknown"}
VERDICT_TONE = {"ADMITTED": "pos", "PARTIAL": "warn", "DEFERRED": "unknown",
                "BLOCKED": "neg", "ADMITTED_WITH_OVERRIDE": "warn"}
SEVERITY_TONE = {"low": "pos", "medium": "warn", "high": "neg", "unknown": "unknown",
                 "NONE": "pos", "MODERATE": "warn", "CRITICAL": "neg"}
LABEL_TONE = {"FACT": "fact", "ESTIMATE": "estimate", "ASSUMPTION": "assumption", "OPINION": "opinion"}
CONFIDENCE_TONE = {"VERIFIED": "pos", "USER_PROVIDED": "pos-soft", "ESTIMATED": "warn", "UNKNOWN": "unknown"}


def _n(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def money(v) -> str:
    """원화 금액. 조/억 단위로 축약한다."""
    if not _n(v):
        return DASH
    neg = "-" if v < 0 else ""
    a = abs(float(v))
    if a >= 1e12:
        return f"{neg}{a / 1e12:,.2f}조원"
    if a >= 1e8:
        return f"{neg}{a / 1e8:,.1f}억원"
    if a >= 1e4:
        return f"{neg}{a / 1e4:,.0f}만원"
    return f"{neg}{a:,.0f}원"


def money_full(v) -> str:
    if not _n(v):
        return DASH
    return f"{'-' if v < 0 else ''}{abs(v):,.0f}원"


def pct(v, digits: int = 1, signed: bool = False) -> str:
    if not _n(v):
        return DASH
    p = float(v) * 100
    if signed:
        return f"{p:+.{digits}f}%"
    return f"{p:.{digits}f}%"


def num(v, digits: int = 1, suffix: str = "") -> str:
    if not _n(v):
        return DASH
    return f"{v:,.{digits}f}{suffix}"


def months(v) -> str:
    if not _n(v):
        return DASH
    return f"{v:,.1f}개월"
