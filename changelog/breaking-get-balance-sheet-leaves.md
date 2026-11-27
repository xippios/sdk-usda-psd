- `get_balance_sheet` leaves, with its MCP tool, its route and the models `BalanceSheet`
  and `BalanceSheetEntry`, by the boundary of a source package: a task that pivots records
  into a shape and keys of the package's own is not the package's. A caller reads the same
  records from `get_data` with a country. (sdk-core ADR-0060,
  https://github.com/xippios/sdk-usda-psd/issues/55)
