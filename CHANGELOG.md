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
