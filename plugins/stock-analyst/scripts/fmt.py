"""리포트 수치 포맷 — 통화·부호·자릿수를 한 곳에서 통일한다.

에이전트가 각자 포맷하면 같은 리포트 안에서 "1,641조원", "1641조", "1.64천조"가
동시에 나온다. 비교가 안 되는 가장 큰 이유라 여기로 모았다.
"""
from __future__ import annotations

DASH = "—"          # 값 없음
RATINGS = ["STRONG BUY", "BUY", "ACCUMULATE", "HOLD", "REDUCE", "AVOID", "INSUFFICIENT DATA"]

# 등급 → 의미 색 계열 (구조색인 인디고와 겹치지 않게 분리한다)
RATING_TONE = {
    "STRONG BUY": "pos", "BUY": "pos", "ACCUMULATE": "pos-soft",
    "HOLD": "neutral", "REDUCE": "neg-soft", "AVOID": "neg",
    "INSUFFICIENT DATA": "unknown",
}
SEVERITY_TONE = {"low": "pos", "medium": "warn", "high": "neg", "unknown": "unknown"}
SEVERITY_FILL = {"low": 1, "medium": 2, "high": 3, "unknown": 0}
LABEL_TONE = {"FACT": "fact", "ESTIMATE": "estimate",
              "ASSUMPTION": "assumption", "OPINION": "opinion"}


def _n(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def money(v, currency: str = "USD") -> str:
    """큰 금액. 원화는 조/억, 달러는 T/B/M."""
    if not _n(v):
        return DASH
    neg = "-" if v < 0 else ""
    a = abs(float(v))
    if currency == "KRW":
        if a >= 1e14:
            return f"{neg}{a / 1e12:,.0f}조원"
        if a >= 1e12:
            return f"{neg}{a / 1e12:,.1f}조원"
        if a >= 1e8:
            return f"{neg}{a / 1e8:,.0f}억원"
        return f"{neg}{a:,.0f}원"
    unit = "$"
    if a >= 1e12:
        return f"{neg}{unit}{a / 1e12:,.2f}T"
    if a >= 1e9:
        return f"{neg}{unit}{a / 1e9:,.1f}B"
    if a >= 1e6:
        return f"{neg}{unit}{a / 1e6:,.1f}M"
    return f"{neg}{unit}{a:,.0f}"


def price(v, currency: str = "USD") -> str:
    """주가는 축약하지 않는다 — 281,500원 / $214.72"""
    if not _n(v):
        return DASH
    if currency == "KRW":
        return f"{v:,.0f}원"
    return f"${v:,.2f}"


def pct(v, digits: int = 1, signed: bool = True) -> str:
    """0.039 → +3.9% / -0.47 → -47.0% / 0 → 0.0%"""
    if not _n(v):
        return DASH
    p = float(v) * 100
    if signed and abs(p) >= 10 ** (-digits) / 2:
        return f"{p:+.{digits}f}%"
    return f"{p:.{digits}f}%"


def num(v, digits: int = 1, suffix: str = "") -> str:
    if not _n(v):
        return DASH
    return f"{v:,.{digits}f}{suffix}"


def multiple(v) -> str:
    """배수는 항상 소수 1자리 + x — P/E 43.8x"""
    if not _n(v):
        return DASH
    return f"{v:,.1f}x"


def bar_pct(value, lo: float = 0.0, hi: float = 10.0) -> float:
    """점수 → 막대 폭(0~100). 범위 밖 값은 잘라낸다."""
    if not _n(value) or hi == lo:
        return 0.0
    ratio = (float(value) - lo) / (hi - lo)
    return round(max(0.0, min(1.0, ratio)) * 100, 2)


def week52_position(price_v, low, high) -> float | None:
    """52주 범위 안에서 현재가의 위치(0~100). 없으면 None."""
    if not (_n(price_v) and _n(low) and _n(high)) or high <= low:
        return None
    return round(max(0.0, min(1.0, (price_v - low) / (high - low))) * 100, 1)


def ascii_bar(value, width: int = 10, lo: float = 0.0, hi: float = 10.0,
              full: str = "#", empty: str = ".") -> str:
    """터미널·마크다운용 텍스트 막대."""
    filled = int(round(bar_pct(value, lo, hi) / 100 * width))
    return full * filled + empty * (width - filled)
