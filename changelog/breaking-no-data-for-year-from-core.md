- `NoDataForYear`, raised for a market year PSD holds no data for, is xippios-core's
  `xippios.core.data_gov.NoDataForYear`, and `xippios.usda.psd.errors` is gone. The class
  is still a `NotFoundError` with `path`, its message still names commodity, country and
  market year, and an `except NotFoundError` catches it as before.
  (https://github.com/xippios/sdk-core/issues/106)
