- `get_time_series` fetches its market years by xippios-core's `fetch_periods`: a request after
  the first that fails raises its error, its class kept, naming the market years answered
  before it by their count, the first and the last, and the task returns nothing.
  (https://github.com/xippios/sdk-core/issues/315,
  https://github.com/xippios/sdk-usda-psd/issues/32)
