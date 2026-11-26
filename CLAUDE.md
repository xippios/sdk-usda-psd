# sdk-usda-psd — instructions for Claude Code

`xippios-usda-psd` wraps USDA FAS PSD Online as a typed Python client, an MCP server
and FastAPI routes, built on `xippios-core`. This file holds what an agent needs to work on
the package: what it wraps, its layout, its commands and what only it knows. The documents it
follows, sdk-core's conventions among them, are listed under
[`## Documents` in the README](README.md#documents); read them before you change a file. The
rules that no change breaks stand in `.claude/rules/never.md`, which Claude Code loads with
this file.

## What this package wraps

| | |
| --- | --- |
| Upstream | USDA FAS PSD Online, https://apps.fas.usda.gov/psdonline/ |
| API base URL | `https://api.fas.usda.gov` |
| Documentation | https://apps.fas.usda.gov/opendatawebV2/, snapshotted in `docs/upstream/` |
| Credentials | `DATA_GOV_API_KEY` from the environment, sent as the `X-Api-Key` header by the `Gateway` of `xippios.usda.fas`, the shared package of the FAS sources (`_client.auth` is `gateway.auth`); the key is api.data.gov's, shared by every package that reads it. sdk-core ADR-0032: one key variable per issuer when one key serves several sources, so every source reached through api.data.gov (`usda-psd`, `usda-esr`, `usda-gats`) reads `DATA_GOV_API_KEY`, and one key is one gateway quota |
| Rate limit | sdk-core ADR-0033, decisions 1–5. Pace: 60 requests per minute, burst 1 (`RateLimit(per_minute=60, burst=1)` in `_client.py`, enforced client-side): a self-imposed pace, upstream documents none (the snapshot names no limit). Quota: api.data.gov's 1,000 requests per rolling hour per key, reported in `x-ratelimit-limit` / `x-ratelimit-remaining` (the hourly quota, not a pace) and shared by every package and process using the same `DATA_GOV_API_KEY`; it may be spent, it is not pre-rationed. The quota is the gateway's: `Gateway.policy` of `xippios.usda.fas`, one `QuotaPolicy` per process for the key, which `_client.py` installs with `gateway.install` (sdk-core ADR-0032, sdk-core ADR-0037), keeps the snapshot from every answer from the wire, never a cache hit's, and gates: once the quota is spent the next request waits it out inside the call, logged, when that is within the policy's `pause_cap` (30 s by default), and otherwise raises `RateLimitError` with `retry_after` without sending, a refusal that says `quota spent` and speaks for `api.data.gov` (its `source`). The wait counts from the last answer: a 429's `Retry-After`, else the policy's `window` of one hour (the gateway sends no reset header, and the 200 that leaves `remaining` at 0 no `Retry-After`). `gateway.classify`, which `classify` asks first, maps the 429 to `RateLimitError` with `retry_after` the wait the policy keeps the quota spent for, from `Retry-After` (recorded: 3151 s, `over_rate_limit.json`), else 3600 s, and core shapes its retries from that: a wait beyond `RetryPolicy.backoff_max` is raised after one request. In offline tests core's pytest plugin bypasses the limiter and the quota policy and forgets the snapshot around each test; a test that asserts a wait or a refusal is marked `rate_limited` |
| Write tools | no, this package is read-only |
| Depends on | `xippios-usda-fas~=0.1.0`, key `DATA_GOV_API_KEY`: a source package's task layer and its models only, never `api/` or `_client`, and this package's servers serve its own tasks, so an agent that wants that source's tools runs its server (sdk-core ADR-0021); a publisher's shared package's public names (sdk-core ADR-0065 decision 3). `xippios-usda-fas` is the shared package of the FAS sources, which holds no task and serves no tool: the package takes from it the api.data.gov gateway, `Gateway` and `API_KEY_ENV`, for `_client.py`, FAS's `NoDataForYear` for `tasks.py`, `REMAINING_HEADER` for the reference script, all four from its root, and the kit of the FAS portal, `Portal` and `shell_text` of `xippios.usda.fas.portal`, for the snapshot script (sdk-core ADR-0021, decision 6) |

The snapshot listed in `docs/upstream/FETCHED.md` is the reference for names, parameters and
semantics; a wrapper is never written from memory of the API.

`_client.py` builds on the `Gateway` of `xippios.usda.fas` (sdk-core ADR-0032, decision 5;
sdk-core ADR-0065, decision 1), which holds what every source behind api.data.gov shares: the
`X-Api-Key` auth, the one `QuotaPolicy` per process on `x-ratelimit-*`, the `API_KEY_*`,
`OVER_RATE_LIMIT` and `NOT_FOUND` mappings with host-free messages, and, since
`Gateway(SOURCE, data_path=DATA_PATH)` names PSD's three data paths, PSD's empty 404 there as
the shared package's `NoDataForYear` (https://github.com/xippios/sdk-core/issues/106). The
client keeps upstream's answers in core's `MemoryCache` at its default lifetime, 300 s for
every path, since the package reads public data alone (conventions §6; sdk-core ADR-0061,
decision 11). `classify` asks `gateway.classify` first and keeps PSD's own answer after it, an
empty 404 elsewhere, which names its request.

## Layout

What this package adds to the family's tree, and its import path, stand in `docs/layout.md`,
imported here:

@docs/layout.md

## Commands

```bash
uv sync --all-extras
uv run pytest                      # offline, replays the fixtures
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pre-commit run --all-files
python3 -I scripts/adr_index.py --check   # the index matches the records in docs/adr/
uv run pytest -m live --tb=short --assert=plain   # needs XIPPIOS_LIVE_TESTS=1, DATA_GOV_API_KEY

uv run xippios-usda-psd-mcp   # stdio; add --http for streamable HTTP
```

`.github/workflows/live.yml` runs the live tests nightly at 01:25 UTC, a time derived from
the slug so that sources sharing a key never start together, and on demand; a pull request never runs them.
Only its `uv run pytest -m live --tb=short --assert=plain` step sees the key, from the org secret `DATA_GOV_API_KEY`.
Every live run takes `--tb=short --assert=plain`, since the log of `live.yml` is public:
the first keeps a failing test's frame arguments out of it, a raw upstream payload among
them, and the second the values a failed `assert` compares. A live test asserts on shapes
and counts, never on a raw payload.

## Template updates

This repository is generated from sdk-template, at the tag `.copier-answers.yml` records. A
template release reaches it in a pull request of its own, with
`uvx --from 'copier>=9.19' copier update --defaults --vcs-ref=<tag>` (conventions §15). The
update never overwrites a file this package fills, those that `_skip_if_exists` lists in
sdk-template's [`copier.yml`](https://github.com/xippios/sdk-template/blob/main/copier.yml),
and sdk-template's
[CHANGELOG](https://github.com/xippios/sdk-template/blob/main/CHANGELOG.md) says, per
release, what to port into those by hand in the same pull request.

The update writes every other file it renders again, since they are the template's,
`.claude/rules/never.md` among them. This package keeps no text of its own in them, the
docstring of `mcp.py` included: its own words go into a file it fills. A line it has to
add to one, such as a dependency in `pyproject.toml`, the update carries into the new
render, silently where the release leaves the lines around it alone and as a conflict
where it changes them.

## Upstream behaviour established by fixtures

The snapshot types every response as `object`, so these facts come from the answers
recorded on 2026-10-23 under `tests/fixtures/`, and the three re-recorded cut on
2026-10-28 (sdk-core ADR-0040, decision 5); `_client.classify` maps them once. A fact of a whole
answer the cut fixtures no longer hold is dated 2026-10-23; those whole recordings are in
commit `07b88ad` on `main`.

- Record shapes of the five lists are in `models.py`, each naming its fixture. Unit
  descriptions are padded with spaces to 20 characters (kept); attribute names are not
  unique (`Total Disappearance` is 126 and 173); four countries sit in region `R15`,
  which `PSDData_GetRegions` does not list.
- Unknown commodity code (`commodity/9999999/country/US/year/2023`) and unknown country
  code (`commodity/0410000/country/XX/year/2023`): HTTP 200 with `[]`. Empty means
  empty, not an error; `params.validate_commodity_code` / `validate_country_code` refuse
  unknown codes before the call (`UnknownCode`, naming the closest packaged codes).
- Valid codes without data: wheat for Bermuda 2023 (`commodity/0410000/country/BD/year/2023`;
  PSD's `BM` is Burma, which has wheat data) answers HTTP 200 with `[]`
  (`no_data_valid_codes`). Empty means empty: `get_data` returns an empty list.
- Market year without data: HTTP 404 with an empty `text/plain` body on every data form,
  one country (`commodity/0410000/country/US/year/1900`, `unknown_year`), every country
  (`.../country/all/year/1900`) and the world (`.../world/year/1900`, both `year_1900`),
  mapped by the gateway of `xippios.usda.fas`, given `_client.DATA_PATH`, to that package's
  `NoDataForYear`, a `NotFoundError` (only that answer on a data path: an empty 404
  elsewhere stays PSD's own plain `NotFoundError`, which names the request, and the
  gateway's `NOT_FOUND` the gateway's). `get_time_series` passes such a year over and names
  it in its note; `get_data` and `get_world_data` answer the empty list with a note that
  names PSD's answer and points to `get_release_dates`, and send no second request
  (https://github.com/xippios/sdk-usda-esr/issues/88, the maintainer's decision of
  2026-11-26). A market year PSD has not released is expected to answer alike, not
  recorded. Any other `NotFoundError` (the gateway's `NOT_FOUND`) propagates unchanged
  from every task.
- Invalid key: HTTP 403 `{"error": {"code": "API_KEY_INVALID", "message": "An invalid
  api_key was supplied. Get one at https://api.fas.usda.gov:443"}}`, no quota headers;
  mapped to `AuthError` naming the code and `DATA_GOV_API_KEY`. The other documented
  `API_KEY_*` codes map the same way. The gateway's `NOT_FOUND` 404 is a plain
  `NotFoundError` (no such route; not recorded, `test_client` builds the documented shape).
- Quota: every keyed answer carries `x-ratelimit-limit: 1000` and
  `x-ratelimit-remaining`; `via` names api.data.gov's API Umbrella. Spent on purpose on
  2026-10-23 (987 calls at the client's pace; its own gate then refused to send) and
  recorded from a fresh process (`get_commodities/over_rate_limit.json`): HTTP 429,
  `{"error": {"code": "OVER_RATE_LIMIT", "message": "You have exceeded your rate limit.
  Try again later or contact us for assistance: https://api.fas.usda.gov:443"}}`,
  `Retry-After: 3151`, `x-ratelimit-limit: 1000`, `x-ratelimit-remaining: 0`. The client
  uses that `Retry-After`; the one-hour fallback (api.data.gov: "The block will
  automatically be lifted by waiting an hour") applies to the 200 that left `remaining`
  at 0, which carries no `Retry-After`, and to a 429 without one.
- Data records (`PSDData_GetCountryCommodityDataByYear`, `PSDData_GetCommodityDataByYear`,
  `PSDData_GetWorldCommodityDataByYear`; `models.CommodityData`): `commodityCode`,
  `countryCode` (`"00"` in world records), `marketYear`, `calendarYear` and `month` as
  digit strings (`"2023"`, `"2026"`, `"07"`, parsed to `int`), `attributeId` and `unitId`
  as integers (plain `int` in the model, so an id PSD adds before the next reference
  refresh never fails an answer; every recorded id is in the packaged lists, which
  `test_params` checks as a freshness test), `value` as a JSON number (`Decimal`). One
  record per country and attribute; wheat US 2023 has 15.
- `country/all` is the largest answer and has no paging: corn 2023 is 1,875 records,
  275,759 bytes of JSON (`corn_all_2023`), wheat 2023 1,845 records, 271,470 bytes, both
  ordered by country code; the fixtures are cut at 200,000 bytes and keep the countries
  from AF to RH (corn) and to RS (wheat), the whole sizes in their `original_count` and
  `original_bytes`. On 2026-10-23 the whole answers held 125 and 123 countries.
- Release dates (`PSDData_GetDataReleaseInfo`; `models.DataReleaseInfo`): one record per
  country and market year, `commodityCode`, `countryCode`, `marketYear`, `releaseYear`,
  `releaseMonth`, all digit strings; a month, no day, no time, no zone. Wheat: 7,754
  records, 837,433 bytes (`original_count`, `original_bytes`), ordered by market year,
  oldest first (within a year by country code on 2026-10-28, in another order on
  2026-10-23), so the cut fixture keeps market years 1960 to 1978, whose newest release
  is 2024-02. The whole list of 2026-10-23 held 145 countries, market years 1960 to
  2026 and no world record. `get_release_dates` serves it, filtered by market year,
  country and `since` after the call.
- A data record's `calendarYear`/`month` is the release that last revised it: for wheat
  2023 every one of the 123 countries matched its release record exactly, and the world
  records carried the latest of them (2026-10), in the whole answers of 2026-10-23.
- `meta.vintage` of `get_data` and `get_world_data` is the latest `calendarYear`-`month`
  across the result's records, `"YYYY-MM"` with the month zero-padded: `"2026-07"` for
  wheat US 2023, `"2026-10"` for wheat all countries and world 2023. In every case
  recorded with its whole release list (wheat 2023: US, all countries, world, on
  2026-10-23) it equals the release list's record for the same commodity, market year
  and country, or the latest across countries; the corn and soybeans recordings are
  internally consistent. So the data tasks make no second call. The cut release list
  ends at market year 1978, so no replay test re-checks this on 2023 any more; the
  whole recordings of commit `07b88ad` show it. `None` for an empty answer.
- `meta.published_at` is `None` for every task: PSD gives a month, no day, and the
  first of the month would predate the real mid-month release, a look-ahead bias in an
  as-of store.

## The time series

`get_time_series(commodity_code, country_code, start_year, end_year, attribute_id=None)` puts
together and orders the records of the request `get_data` makes for one country, once per
market year, conventions §4's period series, and changes none: no derived totals, no unit
conversion, no gap filling, nothing renamed (sdk-core ADR-0028). A ranking, a pivot and a pick
of the newest release are no task of a source package (conventions §14; sdk-core ADR-0060),
so `get_top_countries`, `get_balance_sheet` and `get_latest_release` left in 0.5.0.

- `attribute_id` is an id, a list of ids or, omitted, every attribute; the ids are checked
  by one call of core's `check` before the first request and an empty list is refused;
  records as upstream sent them, ordered by market year and within a year in upstream's
  order; `meta.request` carries `attribute_id` as given and leaves it out when omitted.
  Since the parameter takes a list, the HTTP route is a `POST` with a JSON body
  (conventions §9).
- One request per market year, oldest first, at the client's pace, by core's
  `fetch_periods`: a request after the first that fails raises its error naming the market
  years answered before it, and the task returns nothing. `start_year` from 1960 (the
  snapshot: "PSD Database has data for most commodities since year 1960", the maintainer's
  decision of 2026-11-26 keeps it); at most `tasks.SERIES` market years per call, core's
  `Ceiling`: 100 in Python and over HTTP and 24 on the MCP server, which `--series-years`
  sets from 1 to 100 (the maintainer's decision of 2026-11-26), so one call sends at most
  100 requests, 400 attempts with core's four for each, and 24 and 96 on the MCP server; the
  docstring and the cap's note state it, and a change of the requests the task sends changes
  both. A future year is expected to answer 404 like 1900 (not recorded) and costs its
  request.
- `meta.notes` names each market year answered with its count of rows, in the order of the
  rows, and each passed over: one PSD holds no data for, or whose answer has no record of
  the attributes asked for. Over MCP the cap keeps the family's 200 rows or 64 KB and shows
  the newest rows (`keep="last"`), with a note that names `attribute_id`, `start_year` and
  `end_year` (`tasks.MCP_CAPS`).

Attribute ids and region codes are checked against the packaged lists before any call
(`params.validate_attribute_id`, core's `check`; `params.validate_region_code`, `UnknownCode`
with the closest), and a release month against its form (`params.validate_since`,
`InvalidRequestError`), each refusal saying that nothing was sent (conventions §5).

## Reference data

`scripts/refresh_reference.py` declares the five packaged lists (`commodities`, `countries`,
`regions`, `unitsOfMeasure`, `commodityAttributes`) in one `Lists` of core's frame, one
`Listed` each, which packages them under `reference/`, writes the rows of the provenance table
in `reference/README.md` and renders `enums.py`, committed as the frame's `ruff format` and
`ruff check --fix` leave it; `--render-only` renders them from the packaged files without a
request. The two id lists, `unitsOfMeasure` and `commodityAttributes`, make the two enums by
their `Enumeration`; the three tables, `commodities`, `countries` and `regions`, are packaged
as JSON records under upstream's field names and rendered to no enum. Each `Listed` names its
upstream operation verbatim beside its wrapper (`"PSDData_GetCommodities"`,
`api.get_commodities`), and the file's `endpoint` is that operation, never the wrapper's name.
Every packaged list is in `params.PACKAGED_LISTS`, which the frame checks before a refresh.
Refresh policy: `/refresh-reference-data` inside `/release-prep`, and whenever a validation
failure names a code the package lacks.

The `list_*` tasks answer from these files and never call upstream: core's `PackagedList`
builds `meta` (sdk-core ADR-0041, decision 1), `meta.endpoint` the file's `endpoint`,
`meta.retrieved_at` its `fetched`, the UTC time of the list's fetch to the second as
`PackagedList.write` writes it (the refresh of 2026-10-28), `meta.vintage` `None`
(upstream gives the lists no version). Their filters select records client-side, codes
and names unchanged, upstream order kept; `list_countries` refuses a `region_code` that no
packaged country carries, `R15` passing and `R00` refused with its hint (the maintainer's
decision of 2026-11-26). Over MCP `list_countries` has a cap of its own, 300 rows
(`tasks.MCP_CAPS`, sdk-core ADR-0038), so its 251 countries arrive whole; `get_data` and
`get_release_dates` keep the family's limits, 200 rows or 64 KB, with a note naming their
filters, and are paged, since core's cache answers a continuation (sdk-core ADR-0061,
decision 9); every other tool keeps the family default with core's note. Core's nightly
comparison of the packaged lists, which `tests/test_live.py` collects with `LIVE_LISTS`,
holds each packaged list against the live one, the freshness check (sdk-core ADR-0055).

The records declare the packaged list of each of their codes, `NamedBy` (sdk-core ADR-0067,
decision 6): an answer names in `meta.names` the commodity, country, attribute and unit codes
of its rows and, by `names_codes`, the codes it was called with, and a code the list lacks is
said in `meta.notes`: the world's `"00"` on every answer of `get_world_data`, and `"R15"` on
the four countries of `list_countries` that sit in it.

`enums.AttributeId` and `enums.UnitId` are `IntEnum`s, as conventions §3 has it for integer
ids (sdk-core ADR-0031, decision 6, the rule that decision 5 of this package's
https://github.com/xippios/sdk-usda-psd/pull/3 led to): PSD's ids are integers in the lists
and in every data record, and fidelity to upstream wins. Where upstream gives two ids the
same name, both members carry the id (`TOTAL_DISAPPEARANCE_126`, `TOTAL_DISAPPEARANCE_173`).
The enums are for lookups and for `get_time_series`' `attribute_id`; the models keep the ids
as plain `int` (the NASS pattern), and members compare equal to them.

## USDA FAS PSD Online specifics

- Tests: a replay test goes into the module of its kind, `test_tasks.py` for the data
  tasks, `test_lists.py` for the `list_*` tasks, `test_series.py` for the time series
  (`/add-endpoint` step 6).
- The quota is the gateway's, not this package's: `_client.py` puts `Gateway.policy` of
  `xippios.usda.fas`, the one `QuotaPolicy` per process for the shared key, on `config` with
  `gateway.install(...)`, and `classify` asks `gateway.classify` first, which maps a spent
  quota's 429 to `RateLimitError` with `retry_after` (sdk-core ADR-0032, sdk-core ADR-0033,
  sdk-core ADR-0037). An endpoint added here installs no policy of its own; only PSD's own
  error shapes go into `classify`, after the gateway's.
- The live run, `uv run pytest -m live --tb=short --assert=plain`, spends keyed calls of the
  shared quota, one for each request that core's cache does not answer; core's testing plugin
  prints their count as `requests sent by the live run: <n>`.
