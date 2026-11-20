- A route answers an argument that its schema refuses, a `market_year` of `2023/24` or a
  missing `commodity_code` say, as problem details before the task runs: HTTP 422, the
  title `InvalidRequestError` and the detail `<argument>: <message>`, where FastAPI's own
  422 listed its error details with the input. (https://github.com/xippios/sdk-core/issues/66)
