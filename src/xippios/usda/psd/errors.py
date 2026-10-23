"""PSD Online failure modes with a distinct meaning (conventions §5)."""

from xippios.core import InvalidRequestError, NotFoundError

from xippios.usda.psd._client import SOURCE

__all__ = ["NoDataForYear", "UnknownCode"]


class NoDataForYear(NotFoundError):
    """PSD's own answer for a market year without data (HTTP 404, empty ``text/plain``).

    Recorded for 1900 on all three data forms: one country
    (``PSDData_GetCountryCommodityDataByYear/unknown_year.json``), every country
    (``PSDData_GetCommodityDataByYear/year_1900.json``) and the world
    (``PSDData_GetWorldCommodityDataByYear/year_1900.json``): status 404, an empty body,
    ``content-type: text/plain; charset=utf-8``. ``_client.classify`` raises it for that
    answer on a data path only. The gateway's 404 (``{"error": {"code": "NOT_FOUND",
    ...}}``, no such route) stays a plain ``NotFoundError``: it says the request is wrong,
    not that the year is empty. ``get_time_series`` skips a year that raises this and
    lets every other error through.

    Attributes:
        path: The request path, e.g. ``"/api/psd/commodity/0410000/country/US/year/1900"``.
    """

    def __init__(self, path: str) -> None:
        super().__init__(
            f"PSD Online has no data for {path} (HTTP 404 with an empty body)", source=SOURCE
        )
        self.path = path


class UnknownCode(InvalidRequestError):
    """A code the packaged PSD reference list does not contain (HTTP 422).

    PSD answers an unknown commodity or country code with HTTP 200 and an empty list
    (``tests/fixtures/PSDData_GetCountryCommodityDataByYear/unknown_commodity.json`` and
    ``unknown_country.json``), which is indistinguishable from a query without data. The
    package therefore checks codes against the packaged lists before calling upstream
    and refuses unknown ones, naming the closest known codes.

    The same check covers the attribute id a task filters records by (``attribute_id``
    of ``get_time_series`` and ``get_top_countries``): an id the packaged list lacks
    would select nothing, an empty result like an unknown code's, so it is refused the
    same way, with its own ``reason``.

    Attributes:
        param: The parameter, as the package names it, e.g. ``"commodity_code"``.
        value: The value given, e.g. ``"0410001"``, or ``999`` for an ``attribute_id``.
        list_name: The packaged list checked, as upstream names it, e.g. ``"commodities"``.
        closest: The closest known codes with their upstream names, best match first;
            empty when ``hint`` explains the value instead.
    """

    def __init__(
        self,
        param: str,
        value: str | int,
        *,
        list_name: str,
        fetched: str,
        closest: list[tuple[str, str]],
        hint: str | None = None,
        reason: str = "PSD answers unknown codes with an empty result, so the package "
        "refuses them.",
    ) -> None:
        if hint is None and closest:
            hint = "Did you mean " + ", ".join(f"{code} ({name})" for code, name in closest) + "?"
        article = "an" if param[:1] in set("aeiou") else "a"
        super().__init__(
            f"{value!r} is not {article} {param} in PSD's {list_name} list (packaged, fetched "
            f"{fetched}).{' ' + hint if hint else ''} {reason} If PSD added the code since, "
            "the packaged lists need a refresh (/refresh-reference-data).",
            source=SOURCE,
        )
        self.param = param
        self.value = value
        self.list_name = list_name
        self.closest = closest
