"""The configured ``xippios.core`` client for USDA FAS PSD Online.

One ``AsyncClient`` for the whole package, shared by the tasks, the sync facades and the
MCP server, on api.data.gov's gateway at ``BASE_URL`` (API Umbrella, named in the
``via`` header of every recorded answer) with ``Accept: application/json``. It keeps a
pace of its own, ``RATE_LIMIT``, since the snapshot documents none, and keeps upstream's
answers in core's response cache, ``MemoryCache`` at core's default lifetime of 300 s for
every path, since the package only reads public data (conventions §6; sdk-core ADR-0061,
decision 11): a second read of a path within the lifetime, a continuation of a cut answer
over MCP among them, sends no request. The gateway is the shared package's,
``xippios.usda.fas``'s ``Gateway`` (sdk-core ADR-0032, decision 5; sdk-core ADR-0065,
decision 1): ``gateway.auth`` sends the key from ``DATA_GOV_API_KEY`` in the ``X-Api-Key``
header; ``Gateway.policy``, the one ``QuotaPolicy`` per process for that key, keeps
api.data.gov's hourly quota from every answer from the wire and never fires a request into a
spent one, waiting within the policy's ``pause_cap`` or refusing without sending, a refusal
that speaks for ``api.data.gov`` (sdk-core ADR-0033, sdk-core ADR-0037); and
``gateway.classify`` maps the gateway's ``API_KEY_*`` answers to ``AuthError``, its 429 to
``RateLimitError``, its ``NOT_FOUND`` to ``NotFoundError`` and, since
``Gateway(SOURCE, data_path=DATA_PATH)`` names the data paths, PSD's empty 404 there to the
shared package's ``NoDataForYear`` (https://github.com/xippios/sdk-core/issues/106).
``classify`` asks the gateway first and then answers an empty 404 anywhere else.
"""

import re

import httpx
from xippios.core import (
    AsyncClient,
    ClientConfig,
    EnvVar,
    MemoryCache,
    NotFoundError,
    RateLimit,
    XippiosError,
)
from xippios.core.errors import request_description
from xippios.usda.fas import API_KEY_ENV, Gateway

from xippios.usda.psd._version import __version__

SOURCE = "usda-psd"
BASE_URL = "https://api.fas.usda.gov"
ENV_VARS: tuple[EnvVar, ...] = (EnvVar(API_KEY_ENV, secret=True, required=True),)
"""The variables the package reads, for a host (conventions §7; sdk-core ADR-0026, amendment
2026-11-18, point c): the gateway's key alone. An ``EnvVar`` names a variable and reads none;
a variable the source reads beside these joins the list."""
# A self-imposed pace: upstream documents no per-second or per-minute limit (sdk-core ADR-0033
# decision 1).
RATE_LIMIT = RateLimit(per_minute=60, burst=1)
"""One request per second, no burst: a pace of our own, since the snapshot documents none.

At this pace the gateway's 1,000 requests per hour, shared with every other package using
the same key, last about 17 minutes; past that the quota policy takes over.
"""

DATA_PATH = re.compile(r"/api/psd/commodity/[^/]+/(?:country/[^/]+|world)/year/[^/]+")
"""The three data forms: one country, ``country/all`` and ``world``, by market year."""

# api.data.gov's key, its documented answers and its hourly quota, kept by one policy per
# process that every source behind the gateway shares (sdk-core ADR-0032).
gateway = Gateway(SOURCE, data_path=DATA_PATH)
"""api.data.gov for this package: ``auth``, ``classify`` and ``install``.

``classify`` maps PSD's empty ``text/plain`` 404 on ``DATA_PATH`` to the shared package's
``NoDataForYear``, in this package's name.

``Gateway.policy`` reads ``x-ratelimit-limit: 1000`` and ``x-ratelimit-remaining``, which
count requests per rolling hour per key, not a pace, on every recorded keyed answer
(2026-10-23), shared by every package and process using the same ``DATA_GOV_API_KEY``
(sdk-core ADR-0032). The gateway sends no reset header: a spent quota comes back after a 429's
``Retry-After`` (recorded: 3151 s, ``over_rate_limit.json``), else after the policy's
``window``, one hour, from api.data.gov's developer manual
(https://api.data.gov/docs/developer-manual/, read 2026-10-23): "The block will
automatically be lifted by waiting an hour". That applies to the 200 that left
``remaining`` at 0, which carries no ``Retry-After``, and to a 429 without one.
``Gateway.policy.snapshot()`` reads the quota as the last answer reported it.
"""


def classify(response: httpx.Response) -> XippiosError | None:
    """The gateway's and PSD's error shapes as taxonomy errors (sdk-core ADR-0031, decision 2).

    The gateway's answers come first, mapped by ``gateway.classify``: its ``API_KEY_*``
    refusals as ``AuthError`` naming the code and the variable, never the key (recorded:
    ``API_KEY_INVALID``, ``get_commodities/invalid_key.json``); its 429
    (``OVER_RATE_LIMIT``) as ``RateLimitError`` whose ``retry_after`` is the wait
    ``Gateway.policy`` keeps the quota spent for, from ``Retry-After``, else the hour
    (recorded after spending the quota on 2026-10-23,
    ``get_commodities/over_rate_limit.json``: ``Retry-After: 3151``,
    ``x-ratelimit-remaining: 0``); core asks ``classify`` before it retries, so a wait
    beyond ``RetryPolicy.backoff_max`` is raised after one request; and its ``NOT_FOUND``
    404 as ``NotFoundError``: no such path; and, given ``DATA_PATH``, PSD's own answer for
    a market year without data, a 404 with an empty ``text/plain`` body on a data path,
    recorded for 1900 on every data form: one country
    (``get_country_commodity_data_by_year/unknown_year.json``), every country
    (``get_commodity_data_by_year/year_1900.json``) and the world
    (``get_world_commodity_data_by_year/year_1900.json``), as the shared package's
    ``NoDataForYear``, a ``NotFoundError``, whose message names the request. PSD's own
    follows:

    - An empty 404 anywhere else, off a data path or not ``text/plain``, is a plain
      ``NotFoundError`` that names the request by core's ``request_description`` and says
      that it is not PSD's answer for a market year without data: the request is wrong, not
      the year
      (https://github.com/xippios/sdk-usda-psd/issues/50).

    An unknown commodity or country code answers HTTP 200 with ``[]`` (``unknown_commodity``,
    ``unknown_country``), and so do valid codes without data (wheat for Bermuda in 2023,
    ``no_data_valid_codes``): empty means empty, not an error. Everything else falls
    through to core's status mapping. Messages name the method and the path, never the host.
    """
    error = gateway.classify(response)
    if error is not None:
        return error
    if response.status_code == 404 and not response.content.strip():
        return NotFoundError(
            f"PSD Online answered {request_description(response)} with HTTP 404 and an empty "
            "body, not as it answers a market year without data on a data path: the request "
            "is wrong, not the year.",
            source=SOURCE,
        )
    return None


config = gateway.install(
    ClientConfig(
        source=SOURCE,
        version=__version__,
        base_url=BASE_URL,
        rate_limit=RATE_LIMIT,
        cache=MemoryCache(),
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
    "DATA_PATH",
    "ENV_VARS",
    "RATE_LIMIT",
    "SOURCE",
    "auth",
    "classify",
    "client",
    "config",
    "gateway",
]
