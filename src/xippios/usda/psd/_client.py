"""The configured ``xippios.core`` client for USDA FAS PSD Online.

One ``AsyncClient`` for the whole package: task functions share its rate limiter, and
the same instance serves the sync facades and the MCP server. It asks for JSON
(``Accept: application/json``): the snapshot's operations produce JSON and XML, and
without the header httpx sends ``Accept: */*``.

``https://api.fas.usda.gov`` is the api.data.gov gateway (API Umbrella, named in the
``via`` header of every recorded answer); every path keeps its documented ``/api/psd/``
prefix and the key travels in the ``X-Api-Key`` header (``securityDefinitions`` in
``docs/upstream/openapi/portal-document.json``).

Rate limits. The snapshot documents none, so the client keeps its own pace,
``RATE_LIMIT``. The gateway enforces api.data.gov's quota: 1,000 requests per rolling
hour per key, reported as ``x-ratelimit-limit: 1000`` and ``x-ratelimit-remaining`` on
every recorded answer (2026-10-23) and shared by every package that uses the same
``DATA_GOV_API_KEY`` (ADR-0009). The policy is ADR-0010's, implemented here as its
proving package: the quota may be spent quickly when the data is worth it; the client
interprets the gateway's answers and pauses instead:

- every response's quota headers land in a module-level snapshot, ``quota()``;
- a 429 becomes ``RateLimitError`` with ``retry_after`` from ``Retry-After``, which the
  recorded 429 carries (``over_rate_limit.json``: 3151 s), or ``QUOTA_WINDOW`` when a
  429 comes without one;
- when the last response left ``remaining`` at 0, the next request does not fire into a
  429 (``QuotaAwareClient``): it waits the quota out when the wait is within the client's
  ``RetryPolicy.backoff_max`` (30 s by default, the same bound core uses for a
  ``Retry-After``), and otherwise raises ``RateLimitError`` with ``retry_after`` without
  sending, so MCP and HTTP callers read "retry after N s" instead of hanging. A
  long-running script that would rather wait raises ``backoff_max`` in its own config.
  A request the client's cache can answer is never delayed or refused, and a cache hit
  never updates the snapshot: its headers are as old as the entry.
"""

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from xippios.core import (
    AsyncClient,
    AuthError,
    ClientConfig,
    HeaderKeyAuth,
    NotFoundError,
    RateLimit,
    RateLimitError,
    XippiosError,
)
from xippios.core.client import Params
from xippios.core.errors import parse_retry_after

from xippios.usda.psd._version import __version__

SOURCE = "usda-psd"
BASE_URL = "https://api.fas.usda.gov"
API_KEY_ENV = "DATA_GOV_API_KEY"  # pragma: allowlist secret (a variable name, not a key)
RATE_LIMIT = RateLimit(per_minute=60, burst=1)
"""One request per second, no burst: a pace of our own, since the snapshot documents none.

At this pace the gateway's 1,000 requests per hour last about 17 minutes; past that the
quota handling below takes over.
"""
QUOTA_WINDOW = 3600.0
"""Seconds to wait once api.data.gov's quota is spent and the gateway names no time.

api.data.gov's developer manual (https://api.data.gov/docs/developer-manual/, read
2026-10-23): "The hourly counters for your API key reset on a rolling basis" and "The
block will automatically be lifted by waiting an hour." The recorded 429 names its own
wait in ``Retry-After`` (3151 s, ``over_rate_limit.json``), which wins; this fallback
applies to the 200 that left ``x-ratelimit-remaining`` at 0, which carries no
``Retry-After``, and to a 429 without one. One hour is the only wait known to suffice; on
a rolling window the quota may return sooner.
"""

logger = logging.getLogger("xippios.usda.psd")


@dataclass(frozen=True, slots=True)
class Quota:
    """api.data.gov's hourly request quota for the key, as the last response reported it.

    Attributes:
        limit: ``x-ratelimit-limit``: requests per rolling hour (1,000 observed).
        remaining: ``x-ratelimit-remaining``; set to 0 by a 429 even without the header.
        observed_at: When the response that reported it arrived, UTC.
        retry_after: Seconds from the ``Retry-After`` of a 429, when the gateway sent one.
    """

    limit: int | None
    remaining: int | None
    observed_at: datetime
    retry_after: float | None = None

    @property
    def resumes_at(self) -> datetime | None:
        """When the quota should be back, while ``remaining`` is 0; ``None`` otherwise."""
        if self.remaining != 0:
            return None
        wait = self.retry_after if self.retry_after is not None else QUOTA_WINDOW
        return self.observed_at + timedelta(seconds=wait)

    def describe(self) -> str:
        """One line for messages, e.g. ``"994 of 1000 requests left (as of ...Z)"``."""
        left = "?" if self.remaining is None else str(self.remaining)
        limit = "?" if self.limit is None else str(self.limit)
        return (
            f"{left} of {limit} requests left in the rolling hour (as of {_utc(self.observed_at)})"
        )


def _utc(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


_quota: Quota | None = None
_quota_lock = threading.Lock()


def quota() -> Quota | None:
    """The gateway's quota as the last response reported it; ``None`` before the first one.

    Read-only: the snapshot is replaced by every response that carries quota headers.
    """
    return _quota


def _header_int(response: httpx.Response, name: str) -> int | None:
    value = response.headers.get(name)
    if value is None or not value.strip().isdigit():
        return None
    return int(value)


def observe_quota(response: httpx.Response, *, now: datetime | None = None) -> Quota | None:
    """Update the snapshot from ``response``'s ``x-ratelimit-*`` headers and status.

    A response without quota headers leaves the snapshot alone, except a 429, which
    marks the quota spent. Returns the snapshot after the update.
    """
    global _quota
    limit = _header_int(response, "x-ratelimit-limit")
    remaining = _header_int(response, "x-ratelimit-remaining")
    limited = response.status_code == 429
    if limit is None and remaining is None and not limited:
        return _quota
    with _quota_lock:
        previous = _quota
        if limit is None and previous is not None:
            limit = previous.limit
        _quota = Quota(
            limit=limit,
            remaining=0 if limited else remaining,
            observed_at=now or datetime.now(UTC),
            retry_after=parse_retry_after(response.headers.get("Retry-After")) if limited else None,
        )
        return _quota


def quota_pause(*, now: datetime | None = None) -> float:
    """Seconds the next request should wait for the quota to come back; 0 when it need not."""
    snapshot = _quota
    resumes_at = snapshot.resumes_at if snapshot is not None else None
    if resumes_at is None:
        return 0.0
    return max(0.0, (resumes_at - (now or datetime.now(UTC))).total_seconds())


def _gateway_error(response: httpx.Response) -> tuple[str | None, str]:
    """api.data.gov's ``{"error": {"code": ..., "message": ...}}``, or ``(None, "")``."""
    try:
        payload = response.json()
    except ValueError:
        return None, ""
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict) or not isinstance(error.get("code"), str):
        return None, ""
    message = error.get("message")
    return error["code"], message if isinstance(message, str) else ""


def classify(response: httpx.Response) -> XippiosError | None:
    """The gateway's documented and PSD's observed error shapes, mapped once (ADR-0008).

    Every response passes through here first, so this is also where the quota snapshot
    is updated (``observe_quota``).

    - 401/403 with an api.data.gov ``error.code`` starting ``API_KEY_`` (developer manual:
      ``API_KEY_MISSING``, ``API_KEY_INVALID``, ``API_KEY_DISABLED``,
      ``API_KEY_UNAUTHORIZED``, ``API_KEY_UNVERIFIED``) is ``AuthError`` naming the code
      and the variable, never the key. Recorded: ``API_KEY_INVALID``
      (``PSDData_GetCommodities/invalid_key.json``).
    - 429 (``OVER_RATE_LIMIT``) is ``RateLimitError`` with ``retry_after`` from
      ``Retry-After``, else ``QUOTA_WINDOW``. Recorded after spending the quota on
      2026-10-23 (``PSDData_GetCommodities/over_rate_limit.json``): ``Retry-After:
      3151``, ``x-ratelimit-remaining: 0``, body ``{"error": {"code":
      "OVER_RATE_LIMIT", "message": "You have exceeded your rate limit. ..."}}``.
    - 404 with ``error.code`` ``NOT_FOUND`` is the gateway's: no such path.
    - 404 with an empty body is PSD's own answer for a query without data, recorded for
      market year 1900 (``PSDData_GetCountryCommodityDataByYear/unknown_year.json``).
      Both are ``NotFoundError``.

    An unknown commodity or country code answers HTTP 200 with ``[]`` (``unknown_commodity``,
    ``unknown_country``): empty means empty, not an error. Everything else falls through
    to core's status mapping.
    """
    observe_quota(response)
    status = response.status_code
    if status in (401, 403):
        code, message = _gateway_error(response)
        if code is not None and code.startswith("API_KEY_"):
            return AuthError(
                f"api.data.gov refused the key in {API_KEY_ENV} (HTTP {status} {code}: "
                f"{message}). Check that the variable holds a valid, active api.data.gov key.",
                status=status,
                source=SOURCE,
            )
    if status == 429:
        code, message = _gateway_error(response)
        retry_after = parse_retry_after(response.headers.get("Retry-After"))
        wait = retry_after if retry_after is not None else QUOTA_WINDOW
        upstream = ": ".join(part for part in (code, message) if part)
        snapshot = quota()
        allowance = (
            f"{snapshot.limit} requests per rolling hour per key"
            if snapshot is not None and snapshot.limit is not None
            else "an hourly quota per key"
        )
        state = f" Quota: {snapshot.describe()}." if snapshot is not None else ""
        back = _utc(datetime.now(UTC) + timedelta(seconds=wait))
        return RateLimitError(
            f"api.data.gov rate limit reached for the key in {API_KEY_ENV} "
            f"(HTTP 429{' ' + upstream if upstream else ''}). The gateway allows {allowance}, "
            f"shared by every package using that key; it should be back at {back}.{state}",
            retry_after=wait,
            source=SOURCE,
        )
    if status == 404:
        code, message = _gateway_error(response)
        path = response.request.url.path
        if code == "NOT_FOUND":
            return NotFoundError(
                f"api.data.gov has no route for {path} (HTTP 404 NOT_FOUND: {message})",
                source=SOURCE,
            )
        if not response.content.strip():
            return NotFoundError(
                f"PSD Online has no data for {path} (HTTP 404 with an empty body)",
                source=SOURCE,
            )
    return None


class QuotaAwareClient(AsyncClient):
    """``AsyncClient`` that never fires into a 429 once api.data.gov's quota is spent.

    Before each request (not before each retry of it) it asks ``quota_pause()`` how long
    the quota needs to come back. Within ``config.retry.backoff_max``, the bound core
    uses for a ``Retry-After``, it sleeps that long and sends; beyond it, it raises
    ``RateLimitError`` with ``retry_after`` and the quota snapshot, sending nothing. A
    request the configured cache can answer skips the gate: it costs no quota. Core has
    no hook before a request, so this subclass overrides ``request``, which ``get`` and
    ``get_json`` call, and finds the cache entry the way core's ``request`` does (its
    ``_pool`` and ``_cache_key``); the rest is core's.
    """

    def __init__(
        self,
        config: ClientConfig,
        *,
        auth: httpx.Auth | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(config, auth=auth, transport=transport, sleep=sleep)
        self._quota_sleep = sleep

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Params = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        raise_on_error: bool = True,
    ) -> httpx.Response:
        """Wait for or refuse on a spent quota, then ``AsyncClient.request``.

        Raises:
            RateLimitError: Before sending, when the quota needs longer than
                ``config.retry.backoff_max`` seconds to come back.
        """
        wait = 0.0 if self._cached(method, path, params) else quota_pause()
        if wait > 0:
            snapshot = quota()
            state = snapshot.describe() if snapshot is not None else "spent"
            bound = self.config.retry.backoff_max
            if wait > bound:
                back = _utc(datetime.now(UTC) + timedelta(seconds=wait))
                raise RateLimitError(
                    f"api.data.gov quota for the key in {API_KEY_ENV} is spent ({state}). "
                    f"Nothing was sent: the quota should be back at {back}, later than the "
                    f"client waits inside a call (RetryPolicy.backoff_max, {bound:.0f} s).",
                    retry_after=wait,
                    source=SOURCE,
                )
            logger.warning(
                "%s: api.data.gov quota spent (%s); waiting %.0f s before %s %s",
                SOURCE,
                state,
                wait,
                method,
                path,
            )
            await self._quota_sleep(wait)
        response = await super().request(
            method, path, params=params, json=json, headers=headers, raise_on_error=raise_on_error
        )
        if not raise_on_error and response.extensions.get("xippios_cache") != "hit":
            # classify, which records the quota otherwise, only runs when errors are raised
            # (and never on a cache hit, whose quota headers are as old as the entry).
            observe_quota(response)
        return response

    def _cached(self, method: str, path: str, params: Params) -> bool:
        """True when the configured cache holds a live entry for this request."""
        cache = self.config.cache
        if cache is None or method.upper() != "GET":
            return False
        probe = self._pool().build_request("GET", path, params=params)
        key = self._cache_key("GET", probe.url)
        return key is not None and cache.get(key) is not None


config = ClientConfig(
    source=SOURCE,
    version=__version__,
    base_url=BASE_URL,
    rate_limit=RATE_LIMIT,
    headers={"Accept": "application/json"},
    classify=classify,
)
# The key is read from the environment on the first request, never at import.
auth = HeaderKeyAuth("X-Api-Key", API_KEY_ENV, source=SOURCE)
client = QuotaAwareClient(config, auth=auth)


__all__ = [
    "API_KEY_ENV",
    "BASE_URL",
    "QUOTA_WINDOW",
    "RATE_LIMIT",
    "SOURCE",
    "Quota",
    "QuotaAwareClient",
    "auth",
    "classify",
    "client",
    "config",
    "observe_quota",
    "quota",
    "quota_pause",
]
