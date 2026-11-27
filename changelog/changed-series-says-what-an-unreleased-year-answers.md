- The docstring of `get_time_series`, and with it the input schema of the MCP tool
  `usda_psd_get_time_series`, says under `end_year` that a market year PSD has not released is
  expected to answer its empty 404 and is passed over in `meta.notes`, still costing its
  request. Under `attribute_id` it says that the package keeps the records of the ids asked for
  after each fetch, since PSD's data operations take no attribute. (sdk-core ADR-0061,
  https://github.com/xippios/sdk-usda-psd/issues/66)
