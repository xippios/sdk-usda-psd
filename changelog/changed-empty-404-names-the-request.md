- PSD's empty HTTP 404 off a data path, or without `text/plain`, is a `NotFoundError` that
  names the request, its method and its path, and says that the request is wrong, where it
  said that PSD had no data for the path. (https://github.com/xippios/sdk-usda-psd/issues/50)
