"""The configured ``xippios.core`` client for USDA FAS PSD Online.

One ``AsyncClient`` for the whole package, shared by the tasks, the sync facades and the
MCP server, on api.data.gov's gateway at ``BASE_URL`` (API Umbrella, named in the
``via`` header of every recorded answer) with ``Accept: application/json``. It keeps a
pace of its own, ``RATE_LIMIT``, since the snapshot documents none. The gateway is core's,
``xippios.core.data_gov``'s ``Gateway`` (ADR-0009): ``gateway.auth`` sends the key from
``DATA_GOV_API_KEY`` in the ``X-Api-Key`` header; ``Gateway.policy``, the one
``QuotaPolicy`` per process for that key, keeps api.data.gov's hourly quota from every
answer and never fires a request into a spent one, waiting within the policy's
``pause_cap`` or refusing without sending, a refusal that speaks for ``api.data.gov``
(ADR-0010, ADR-0015); and ``gateway.classify`` maps the gateway's ``API_KEY_*`` answers to
``AuthError``, its 429 to ``RateLimitError`` and its ``NOT_FOUND`` to ``NotFoundError``.
``classify`` asks the gateway first and then maps PSD's empty 404 on a data path to
``errors.NoDataForYear``.
"""

import re

import httpx
from xippios.core import AsyncClient, ClientConfig, NotFoundError, RateLimit, XippiosError
from xippios.core.data_gov import API_KEY_ENV, Gateway

from xippios.usda.psd._version import __version__

SOURCE = "usda-psd"
BASE_URL = "https://api.fas.usda.gov"
# A self-imposed pace: upstream documents no per-second or per-minute limit (ADR-0010 decision 1).
RATE_LIMIT = RateLimit(per_minute=60, burst=1)
"""One request per second, no burst: a pace of our own, since the snapshot documents none.

At this pace the gateway's 1,000 requests per hour, shared with every other package using
the same key, last about 17 minutes; past that the quota policy takes over.
"""

DATA_PATH = re.compile(r"/api/psd/commodity/[^/]+/(?:country/[^/]+|world)/year/[^/]+")
"""The three data forms: one country, ``country/all`` and ``world``, by market year."""

# api.data.gov's key, its documented answers and its hourly quota, kept by one policy per
# process that every source behind the gateway shares (ADR-0009).
gateway = Gateway(SOURCE)
"""api.data.gov for this package: ``auth``, ``classify`` and ``install``.

``Gateway.policy`` reads ``x-ratelimit-limit: 1000`` and ``x-ratelimit-remaining``, which
count requests per rolling hour per key, not a pace, on every recorded keyed answer
(2026-10-23), shared by every package and process using the same ``DATA_GOV_API_KEY``
(ADR-0009). The gateway sends no reset header: a spent quota comes back after a 429's
``Retry-After`` (recorded: 3151 s, ``over_rate_limit.json``), else after the policy's
``window``, one hour, from api.data.gov's developer manual
(https://api.data.gov/docs/developer-manual/, read 2026-10-23): "The block will
automatically be lifted by waiting an hour". That applies to the 200 that left
``remaining`` at 0, which carries no ``Retry-After``, and to a 429 without one.
``Gateway.policy.snapshot()`` reads the quota as the last answer reported it.
"""


def classify(response: httpx.Response) -> XippiosError | None:
    """The gateway's documented and PSD's observed error shapes, mapped once (ADR-0008).

    The gateway's answers come first, mapped by ``gateway.classify``: its ``API_KEY_*``
    refusals as ``AuthError`` naming the code and the variable, never the key (recorded:
    ``API_KEY_INVALID``, ``PSDData_GetCommodities/invalid_key.json``); its 429
    (``OVER_RATE_LIMIT``) as ``RateLimitError`` whose ``retry_after`` is the wait
    ``Gateway.policy`` keeps the quota spent for, from ``Retry-After``, else the hour
    (recorded after spending the quota on 2026-10-23,
    ``PSDData_GetCommodities/over_rate_limit.json``: ``Retry-After: 3151``,
    ``x-ratelimit-remaining: 0``); core asks ``classify`` before it retries, so a wait
    beyond ``RetryPolicy.backoff_max`` is raised after one request; and its ``NOT_FOUND``
    404 as ``NotFoundError``: no such path. PSD's own follows:

    - 404 with an empty ``text/plain`` body on a data path is PSD's own answer for a
      market year without data, recorded for 1900 on every data form: one country
      (``PSDData_GetCountryCommodityDataByYear/unknown_year.json``), every country
      (``PSDData_GetCommodityDataByYear/year_1900.json``) and the world
      (``PSDData_GetWorldCommodityDataByYear/year_1900.json``). It is
      ``errors.NoDataForYear``, a ``NotFoundError``; the gateway's ``NOT_FOUND``, and an
      empty 404 anywhere else, are a plain ``NotFoundError``.

    An unknown commodity or country code answers HTTP 200 with ``[]`` (``unknown_commodity``,
    ``unknown_country``), and so do valid codes without data (wheat for Bermuda in 2023,
    ``no_data_valid_codes``): empty means empty, not an error. Everything else falls
    through to core's status mapping. Messages name the path, never the host.
    """
    error = gateway.classify(response)
    if error is not None:
        return error
    if response.status_code == 404 and not response.content.strip():
        path = response.request.url.path
        content_type = response.headers.get("content-type", "").lower()
        if content_type.startswith("text/plain") and DATA_PATH.fullmatch(path):
            # errors imports SOURCE from this module, so it is imported here, not above
            from xippios.usda.psd.errors import NoDataForYear

            return NoDataForYear(path)
        return NotFoundError(
            f"PSD Online has no data for {path} (HTTP 404 with an empty body)",
            source=SOURCE,
        )
    return None


config = gateway.install(
    ClientConfig(
        source=SOURCE,
        version=__version__,
        base_url=BASE_URL,
        rate_limit=RATE_LIMIT,
        headers={"Accept": "application/json"},
        classify=classify,
    )
)
# The key is read from the environment on the first request, never at import.
auth = gateway.auth
client = AsyncClient(config, auth=auth)


__all__ = [
    "API_KEY_ENV",
    "BASE_URL",
    "RATE_LIMIT",
    "SOURCE",
    "auth",
    "classify",
    "client",
    "config",
    "gateway",
]
