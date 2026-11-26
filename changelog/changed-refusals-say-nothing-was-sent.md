- Every refusal of a call as given says `Nothing was sent.` after its first sentence: an
  unknown code, a market year that is not four digits, a `since` that is not a release month, a
  region code that is not text, a series that starts before 1960 or runs backwards, and the MCP
  adapter's refusal of an argument. The attribute ids are checked by one call of
  xippios-core's `check`, in its wording, which names the first id it refuses, the integer to
  pass for a text of digits and refuses an empty list. The refusals' classes are unchanged.
  (https://github.com/xippios/sdk-core/issues/481,
  https://github.com/xippios/sdk-usda-psd/issues/30)
