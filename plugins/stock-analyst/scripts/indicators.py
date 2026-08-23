#!/usr/bin/env python3
"""기술적 지표 (문서 §16) — 순수 계산, 네트워크 없음.

CLI: python3 indicators.py <bars.json>   (bars = [{date, open, high, low, close, volume}, ...])
"""
from __future__ import annotations

import json
import sys
from datetime import date


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0:
        return out
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        if i >= period - 1:
            out[i] = total / period
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period or period <= 0:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    """Wilder 평활 RSI."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g, avg_l = gains / period, losses / period
    out[period] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    ef, es = ema(values, fast), ema(values, slow)
    line = [(a - b) if (a is not None and b is not None) else None for a, b in zip(ef, es)]
    valid = [v for v in line if v is not None]
    sig_valid = ema(valid, signal)
    sig: list[float | None] = [None] * (len(line) - len(valid)) + sig_valid
    hist = [(l - s) if (l is not None and s is not None) else None for l, s in zip(line, sig)]
    return {"macd": line, "signal": sig, "histogram": hist}


def atr(bars: list[dict], period: int = 14) -> list[float | None]:
    trs: list[float] = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b["high"] - b["low"])
            continue
        pc = bars[i - 1]["close"]
        trs.append(max(b["high"] - b["low"], abs(b["high"] - pc), abs(b["low"] - pc)))
    return sma(trs, period)


def bollinger(values: list[float], period: int = 20, mult: float = 2.0) -> dict:
    mid = sma(values, period)
    upper: list[float | None] = [None] * len(values)
    lower: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1: i + 1]
        m = mid[i]
        var = sum((x - m) ** 2 for x in window) / period
        sd = var ** 0.5
        upper[i], lower[i] = m + mult * sd, m - mult * sd
    return {"middle": mid, "upper": upper, "lower": lower}


def classify_trend(close: float, ma20, ma50, ma200) -> str:
    """문서 §16 Market Structure 5단계."""
    have = [m for m in (ma20, ma50, ma200) if m is not None]
    if len(have) < 2 or ma200 is None:
        return "unknown"
    above = close > ma200
    stacked_up = ma20 is not None and ma50 is not None and ma20 > ma50 > ma200
    stacked_down = ma20 is not None and ma50 is not None and ma20 < ma50 < ma200
    if above and stacked_up and close > ma20:
        return "strong_uptrend"
    if above and (stacked_up or close > ma50):
        return "uptrend"
    if not above and stacked_down and close < ma20:
        return "strong_downtrend"
    if not above and (stacked_down or close < ma50):
        return "downtrend"
    return "sideways"


def swing_levels(bars: list[dict], lookback: int = 120, window: int = 5, top: int = 4) -> dict:
    """최근 구간의 스윙 고·저점을 지지/저항 후보로 뽑는다."""
    seg = bars[-lookback:]
    highs, lows = [], []
    for i in range(window, len(seg) - window):
        h = seg[i]["high"]
        l = seg[i]["low"]
        if h == max(b["high"] for b in seg[i - window:i + window + 1]):
            highs.append({"date": seg[i]["date"], "price": h})
        if l == min(b["low"] for b in seg[i - window:i + window + 1]):
            lows.append({"date": seg[i]["date"], "price": l})
    close = seg[-1]["close"]
    resistance = sorted([h for h in highs if h["price"] > close], key=lambda x: x["price"])[:top]
    support = sorted([l for l in lows if l["price"] < close], key=lambda x: -x["price"])[:top]
    return {"support": support, "resistance": resistance}


_PERIODS = {"1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252, "3Y": 756, "5Y": 1260}


def returns(bars: list[dict]) -> dict:
    closes = [b["close"] for b in bars]
    last = closes[-1]
    out = {}
    if len(closes) >= 2:
        out["1D"] = last / closes[-2] - 1
    for label, n in _PERIODS.items():
        if len(closes) > n:
            out[label] = last / closes[-1 - n] - 1
    ytd_base = None
    year = bars[-1]["date"][:4]
    for b in bars:
        if b["date"][:4] == year:
            ytd_base = b["close"]
            break
    if ytd_base:
        out["YTD"] = last / ytd_base - 1
    return out


def analyze(bars: list[dict]) -> dict:
    """봉 시계열 → 기술적 분석 스냅샷."""
    if len(bars) < 30:
        return {"ok": False, "error": "insufficient-history",
                "message": f"봉 {len(bars)}개 — 기술적 분석에는 최소 30개 필요"}
    closes = [b["close"] for b in bars]
    i = len(closes) - 1
    mas = {p: sma(closes, p)[i] for p in (20, 50, 100, 200)}
    r = rsi(closes)
    md = macd(closes)
    bb = bollinger(closes)
    a = atr(bars)
    vols = [b["volume"] or 0 for b in bars]
    close = closes[-1]

    trend = classify_trend(close, mas[20], mas[50], mas[200])
    signals = []
    if r[i] is not None:
        if r[i] >= 70:
            signals.append({"tone": "caution", "text": f"RSI {r[i]:.0f} — 과매수 구간"})
        elif r[i] <= 30:
            signals.append({"tone": "watch", "text": f"RSI {r[i]:.0f} — 과매도 구간"})
    if md["histogram"][i] is not None and md["histogram"][i - 1] is not None:
        if md["histogram"][i] > 0 >= md["histogram"][i - 1]:
            signals.append({"tone": "positive", "text": "MACD 골든크로스 발생"})
        elif md["histogram"][i] < 0 <= md["histogram"][i - 1]:
            signals.append({"tone": "negative", "text": "MACD 데드크로스 발생"})
    if mas[200] and close < mas[200]:
        signals.append({"tone": "negative", "text": "200일선 아래 — 장기 추세 훼손"})
    if bb["upper"][i] and close > bb["upper"][i]:
        signals.append({"tone": "caution", "text": "볼린저 상단 이탈 — 단기 과열"})

    highs = [b["high"] for b in bars[-252:]]
    lows = [b["low"] for b in bars[-252:]]
    return {
        "ok": True,
        "asOfBar": bars[-1]["date"],
        "close": close,
        "movingAverages": {f"ma{p}": mas[p] for p in mas},
        "distanceFromMa": {f"ma{p}": (close / mas[p] - 1) if mas[p] else None for p in mas},
        "rsi14": r[i],
        "macd": {"macd": md["macd"][i], "signal": md["signal"][i], "histogram": md["histogram"][i]},
        "atr14": a[i],
        "atrPct": (a[i] / close) if a[i] else None,
        "bollinger": {"upper": bb["upper"][i], "middle": bb["middle"][i], "lower": bb["lower"][i]},
        "trend": trend,
        "week52High": max(highs) if highs else None,
        "week52Low": min(lows) if lows else None,
        "fromWeek52High": (close / max(highs) - 1) if highs else None,
        "volume": vols[-1],
        "avgVolume50": (sum(vols[-50:]) / min(50, len(vols))) if vols else None,
        "volumeRatio": (vols[-1] / (sum(vols[-50:]) / min(50, len(vols)))) if vols and sum(vols[-50:]) else None,
        "levels": swing_levels(bars),
        "returns": returns(bars),
        "signals": signals,
        "disclaimer": "기술적 지표는 매수·매도 시점 참고용이다. 이것만으로 장기투자를 판단하지 않는다 (문서 §70).",
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: indicators.py <bars.json|->", file=sys.stderr)
        return 2
    src = sys.stdin.read() if sys.argv[1] == "-" else open(sys.argv[1]).read()
    payload = json.loads(src)
    bars = payload.get("bars") if isinstance(payload, dict) else payload
    if isinstance(payload, dict) and payload.get("data"):
        bars = payload["data"].get("bars", bars)
    json.dump(analyze(bars), sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
