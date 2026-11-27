- The endpoint wrappers under `api/` return core's `Answer`, the parsed answer as its
  `payload` beside the time it was retrieved as its `retrieved_at`, where they returned the
  parsed records themselves, so a caller of `api.get_commodities()` or another wrapper reads
  its `.payload`. (https://github.com/xippios/sdk-core/issues/479,
  https://github.com/xippios/sdk-usda-psd/issues/53)
