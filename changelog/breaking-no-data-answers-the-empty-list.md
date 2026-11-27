- `get_data` and `get_world_data` answer a market year that PSD holds no data for, its HTTP
  404 with an empty body, with the empty list and a note in `meta.notes` that names PSD's
  answer and points to `get_release_dates`, and send no second request, where they raised
  `NoDataForYear`. A caller that caught the error reads the empty list, and the class, which
  `xippios.core.data_gov` held, now stands in `xippios.usda.fas`.
  (https://github.com/xippios/sdk-usda-esr/issues/88,
  https://github.com/xippios/sdk-usda-psd/issues/53)
