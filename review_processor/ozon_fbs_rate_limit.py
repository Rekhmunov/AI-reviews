"""Ozon Seller API rate limiting (per Client-Id).

Ozon documents a global ceiling of **50 requests per second** per Client-Id
across all methods. Exceeding it yields HTTP 429 (often with ``Retry-After``);
repeated bursts can temporarily block the method («circle is open»).

This module:
- paces outbound calls with a shared token bucket per Client-Id;
- defaults to a conservative rate below 50 rps (override via env);
- parses ``Retry-After`` for backoff helpers used by the HTTP client.

Env:
- ``OZON_API_MAX_RPS`` — float, default ``40`` (cap hard-clamped to 50);
- ``OZON_API_RATE_LIMIT`` — ``0``/``false``/``off`` disables pacing (tests/debug).
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

# Documented Ozon Seller API global limit per Client-Id.
OZON_DOCUMENTED_MAX_RPS = 50.0
# Stay under the published ceiling by default.
_DEFAULT_MAX_RPS = 40.0


def _env_flag_disabled(name: str) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    return raw in {"0", "false", "no", "off", "disable", "disabled"}


def configured_max_rps() -> float:
    """Effective requests/sec budget (≤ documented 50)."""
    if _env_flag_disabled("OZON_API_RATE_LIMIT"):
        return 0.0
    raw = str(os.environ.get("OZON_API_MAX_RPS", "") or "").strip()
    try:
        val = float(raw) if raw else _DEFAULT_MAX_RPS
    except ValueError:
        val = _DEFAULT_MAX_RPS
    if val <= 0:
        return 0.0
    return min(float(val), OZON_DOCUMENTED_MAX_RPS)


class TokenBucketLimiter:
    """Thread-safe token bucket: ``rate`` tokens/sec, burst ≈ ``rate``."""

    def __init__(self, *, rate: float) -> None:
        self.rate = max(0.0, float(rate))
        self.capacity = max(self.rate, 1.0) if self.rate > 0 else 0.0
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        if self.rate <= 0:
            return
        need = max(0.0, float(tokens))
        if need <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = max(0.0, now - self._updated)
                self._updated = now
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                if self._tokens >= need:
                    self._tokens -= need
                    return
                deficit = need - self._tokens
                wait = deficit / self.rate if self.rate > 0 else 0.0
            # Sleep outside the lock so other Client-Ids are not blocked.
            time.sleep(min(max(wait, 0.001), 2.0))


_LIMITERS: dict[str, TokenBucketLimiter] = {}
_LIMITERS_LOCK = threading.Lock()


def limiter_for_client(client_id: str) -> TokenBucketLimiter:
    key = str(client_id or "").strip() or "_anonymous"
    rate = configured_max_rps()
    with _LIMITERS_LOCK:
        lim = _LIMITERS.get(key)
        if lim is None or abs(lim.rate - rate) > 1e-9:
            lim = TokenBucketLimiter(rate=rate)
            _LIMITERS[key] = lim
        return lim


def acquire_client_slot(client_id: str) -> None:
    """Block until one request slot is available for this Client-Id."""
    limiter_for_client(client_id).acquire(1.0)


def reset_limiters_for_tests() -> None:
    """Clear shared limiters (unit tests only)."""
    with _LIMITERS_LOCK:
        _LIMITERS.clear()


def parse_retry_after_seconds(headers: Any) -> float | None:
    """Parse ``Retry-After`` / common Ozon rate-limit headers to seconds."""
    if headers is None:
        return None

    def _get(name: str) -> str:
        try:
            if hasattr(headers, "get"):
                val = headers.get(name) or headers.get(name.lower())
                if val is not None:
                    return str(val).strip()
        except Exception:
            return ""
        try:
            # email.message.Message style
            val = headers[name]
            if val is not None:
                return str(val).strip()
        except Exception:
            return ""
        return ""

    for key in (
        "Retry-After",
        "retry-after",
        "X-RateLimit-Retry-After",
        "x-ratelimit-retry-after",
    ):
        raw = _get(key)
        if not raw:
            continue
        try:
            return max(0.0, float(raw))
        except ValueError:
            continue
    return None


def backoff_seconds_for_429(*, attempt: int, retry_after: float | None) -> float:
    """Prefer Retry-After; else exponential backoff capped for operator UX."""
    if retry_after is not None and retry_after > 0:
        return min(float(retry_after), 60.0)
    # 0.5, 1, 2, 4 … capped
    return min(0.5 * (2 ** max(0, int(attempt))), 8.0)
