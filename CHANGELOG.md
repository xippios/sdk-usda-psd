# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: breaking changes bump the minor).

## [Unreleased]

### Added

- Scaffold from [sdk-template](https://github.com/xippios/sdk-template): configured
  client for USDA FAS PSD Online, empty task layer, MCP server and FastAPI router
  wired to it, test harness, CI and publishing.
- Upstream documentation snapshot in `docs/upstream/` (2026-10-23): the PSD part of
  the FAS Open Data Services Swagger 2.0 document as the portal loads it
  (`openapi/portal-document.json`) and as the API serves it itself
  (`openapi/backend-docs-v1.json`), nine `/api/psd/` operations each, the
  ESR and GATS paths left out. `FETCHED.md` records the full documents' sizes and
  sha256 and the pages that hold no documentation text.
- `scripts/refresh_upstream.py`: regenerates the snapshot reproducibly, stdlib only and
  without a key (`uv run scripts/refresh_upstream.py`).
- Endpoint wrappers for the five PSD reference operations, `PSDData_GetCommodities`,
  `PSDData_GetCountries`, `PSDData_GetRegions`, `PSDData_GetUnitsOfMeasure` and
  `PSDData_GetCommodityAttributes`, with models built from the recorded records.
- Client: `classify` maps api.data.gov's `API_KEY_*` answers to `AuthError` naming the
  code and `DATA_GOV_API_KEY`, a 429 to `RateLimitError` (`Retry-After`, else one hour),
  the gateway's `NOT_FOUND` and PSD's empty-body 404 to `NotFoundError`. The client keeps
  60 requests per minute, one at a time, records the gateway's `x-ratelimit-*` headers in
  `quota()`, and waits before the next request once the hourly quota is spent.
- Packaged reference data: the five lists under `reference/` with provenance, written by
  `scripts/refresh_reference.py` through `api/`; `enums.AttributeId` and `enums.UnitId`
  (`IntEnum`, named after upstream's names); `params.validate_commodity_code`,
  `validate_country_code` (raising `errors.UnknownCode` with the closest packaged codes)
  and `validate_market_year`.
- Recorded fixtures for the five lists, an unknown commodity, country and market year,
  and an invalid key; `CLAUDE.md` records what each answered.
- Tasks `get_data(commodity_code, market_year, country_code=None)` (one country, or every
  country through the `country/all` path), `get_world_data(commodity_code, market_year)`
  and `get_release_dates(commodity_code)`, as MCP tools `usda_psd_get_data`,
  `usda_psd_get_world_data`, `usda_psd_get_release_dates` and HTTP routes. Codes and the
  market year are checked before any call. The data tasks fill `meta.published_at` from
  PSD's release dates (first of the release month, UTC); a market year without data is
  `NotFoundError` naming commodity, country and year.
- Endpoint wrappers `PSDData_GetCountryCommodityDataByYear`,
  `PSDData_GetCommodityDataByYear`, `PSDData_GetWorldCommodityDataByYear` and
  `PSDData_GetDataReleaseInfo`, models `CommodityData` (`value` as `Decimal`, ids as the
  packaged enums) and `DataReleaseInfo`; release dates are cached for an hour.
- A spent api.data.gov quota is waited out only within the client's
  `RetryPolicy.backoff_max`; a longer wait raises `RateLimitError` with `retry_after`
  without sending.
- Recorded the gateway's 429 (`OVER_RATE_LIMIT`, `Retry-After: 3151`,
  `x-ratelimit-remaining: 0`) after spending the hourly quota; `classify` was already
  right for it, and the tests now use the recording.
- `scripts/check-siblings.sh` and the CI job `siblings`: this wheel and
  `xippios-usda-nass` install side by side, import, pass `uv pip check`, and add no
  `__init__.py` to `xippios/` or `xippios/usda/` (ADR-0006).

### Fixed

- Cached release dates failed to decode when upstream had sent them gzip-compressed:
  core's cache keeps `content-encoding` over the decoded body. The package's cache
  backend drops the wire-encoding headers until core does.
