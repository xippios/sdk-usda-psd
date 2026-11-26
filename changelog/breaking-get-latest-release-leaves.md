- `get_latest_release` leaves, with its MCP tool and its route, by the boundary of a source
  package: a task that picks the newest release for the caller is not the package's. A caller
  polls with `get_release_dates(commodity_code, since=...)` and picks the newest records of
  the list itself. (sdk-core ADR-0060, https://github.com/xippios/sdk-usda-psd/issues/55)
