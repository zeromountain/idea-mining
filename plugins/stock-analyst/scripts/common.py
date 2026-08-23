"""stock-analyst 공용 유틸 — HTTP, 캐시, 메타데이터, 출력.

파이썬 표준 라이브러리만 사용한다 (pip 설치 없음).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("STOCK_RESEARCH_HOME", Path.home() / "stock-research"))
CACHE = ROOT / "cache"

# 문서 §39 Freshness 정책 (초 단위)
TTL = {
    "quote": 300,          # 5m
    "history": 900,        # 15m
    "indicators": 900,     # 15m
    "news": 3600,          # 1h
    "financials": 604800,  # 7d
    "filings": 604800,     # 7d
    "macro": 86400,        # 1d
    "profile": 2592000,    # 30d
    "tickermap": 2592000,  # 30d
    "peers": 604800,       # 7d
    "etf": 604800,         # 7d
}

# SEC는 연락처가 담긴 User-Agent를 요구한다 (10 req/s 제한).
SEC_UA = os.environ.get("SEC_USER_AGENT", "stock-analyst research contact@example.com")
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Yahoo의 429는 IP 전체가 아니라 (IP, User-Agent) 버킷 단위로 걸린다 —
# 실측으로 확인했다. 한 UA가 막히면 다른 UA로 즉시 재시도하면 통과한다.
UA_POOL = [
    BROWSER_UA,
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "stock-analyst/0.1 (+research)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
]

# FRED는 Mozilla 계열 UA를 차단한다 (실측: Mozilla → 응답 없음, urllib/curl → 200).
# 호스트별로 기본 UA를 다르게 준다.
HOST_UA = {
    "fred.stlouisfed.org": "Python-urllib/3",
}

_last_call: dict[str, float] = {}
_MIN_INTERVAL = {"data.sec.gov": 0.12, "www.sec.gov": 0.12}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class FetchError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _throttle(host: str) -> None:
    gap = _MIN_INTERVAL.get(host)
    if not gap:
        return
    prev = _last_call.get(host, 0.0)
    wait = gap - (time.time() - prev)
    if wait > 0:
        time.sleep(wait)
    _last_call[host] = time.time()


def http_get(url: str, headers: dict | None = None, timeout: int = 15,
             retries: int = 2, as_json: bool = True, as_bytes: bool = False):
    """GET 요청. 429/5xx는 지수 백오프로 재시도하고, 끝내 실패하면 FetchError를 던진다."""
    host = urllib.parse.urlparse(url).netloc
    hdrs = {"User-Agent": HOST_UA.get(host, BROWSER_UA), "Accept": "*/*"}
    if host.endswith("sec.gov"):
        hdrs["User-Agent"] = SEC_UA
        hdrs["Accept-Encoding"] = "gzip, deflate"
    if headers:
        hdrs.update(headers)

    # UA 로테이션은 Yahoo에만 의미가 있다 (429가 UA 버킷 단위).
    # SEC는 연락처 UA를 고정해야 하고, 나머지 호스트는 로테이션할 이유가 없다.
    pool = list(UA_POOL) if host.endswith("finance.yahoo.com") else [hdrs["User-Agent"]]
    last = None
    total = (retries + 1) * len(pool)
    for attempt in range(total):
        hdrs["User-Agent"] = pool[attempt % len(pool)]
        _throttle(host)
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                if as_bytes:
                    # ZIP 등 바이너리는 디코딩하면 복구 불가능하게 깨진다.
                    return raw
                text = raw.decode("utf-8", errors="replace")
                if not as_json:
                    return text
                try:
                    return json.loads(text)
                except json.JSONDecodeError as exc:
                    raise FetchError("invalid-payload", f"{host}: JSON 파싱 실패 ({exc})")
        except urllib.error.HTTPError as exc:
            last = FetchError(
                "rate-limited" if exc.code == 429 else f"http-{exc.code}",
                f"{host}: HTTP {exc.code}",
            )
            if exc.code in (429, 500, 502, 503, 504) and attempt < total - 1:
                # 429는 UA만 바꿔 즉시 재시도하고, 한 바퀴 다 돌았으면 그때 백오프한다.
                if exc.code != 429 or (attempt + 1) % len(pool) == 0:
                    time.sleep(1.5 * (2 ** (attempt // max(len(pool), 1))))
                continue
            raise last
        except urllib.error.URLError as exc:
            last = FetchError("provider-unavailable", f"{host}: {exc.reason}")
            if attempt < total - 1:
                time.sleep(1.0 * (2 ** (attempt // max(len(pool), 1))))
                continue
            raise last
        except TimeoutError:
            last = FetchError("provider-timeout", f"{host}: 타임아웃")
            if attempt < total - 1:
                continue
            raise last
    raise last or FetchError("provider-unavailable", host)


def cache_path(kind: str, key: str) -> Path:
    safe = str(key).replace("/", "_").replace(" ", "_").upper() or "_GLOBAL"
    return CACHE / safe / f"{kind}.json"


def read_cache(kind: str, key: str, ttl: int | None = None):
    path = cache_path(kind, key)
    if not path.exists():
        return None
    ttl = TTL.get(kind, 3600) if ttl is None else ttl
    if ttl >= 0 and (time.time() - path.stat().st_mtime) > ttl:
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_cache(kind: str, key: str, payload: dict) -> Path:
    path = cache_path(kind, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def envelope(kind: str, key: str, source: str, source_url: str, data,
             confidence: str = "high", tier: int = 3, as_of: str | None = None) -> dict:
    """문서 §38 DataPoint 메타데이터를 붙인 성공 응답."""
    return {
        "ok": True,
        "meta": {
            "type": kind,
            "key": key,
            "source": source,
            "sourceUrl": source_url,
            "tier": tier,
            "asOf": as_of or now_iso(),
            "retrievedAt": now_iso(),
            "confidence": confidence,
        },
        "data": data,
    }


def failure(kind: str, key: str, code: str, message: str, tried: list[str] | None = None) -> dict:
    """문서 §67 Graceful Degradation — 실패도 정상 반환값이다."""
    return {
        "ok": False,
        "meta": {
            "type": kind,
            "key": key,
            "retrievedAt": now_iso(),
            "confidence": "none",
        },
        "error": {"code": code, "message": message, "providersTried": tried or []},
        "data": None,
    }


def emit(payload: dict, path: Path | None = None) -> None:
    if path is not None:
        payload.setdefault("meta", {})["cachePath"] = str(path)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
