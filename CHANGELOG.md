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
