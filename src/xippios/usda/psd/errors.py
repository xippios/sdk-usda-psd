"""PSD Online failure modes with a distinct meaning (conventions §5)."""

from xippios.core import InvalidRequestError

from xippios.usda.psd._client import SOURCE

__all__ = ["UnknownCode"]


class UnknownCode(InvalidRequestError):
    """A code the packaged PSD reference list does not contain (HTTP 422).

    PSD answers an unknown commodity or country code with HTTP 200 and an empty list
    (``tests/fixtures/PSDData_GetCountryCommodityDataByYear/unknown_commodity.json`` and
    ``unknown_country.json``), which is indistinguishable from a query without data. The
    package therefore checks codes against the packaged lists before calling upstream
    and refuses unknown ones, naming the closest known codes.

    Attributes:
        param: The parameter, as the package names it, e.g. ``"commodity_code"``.
        value: The value given.
        list_name: The packaged list checked, as upstream names it, e.g. ``"commodities"``.
        closest: The closest known codes with their upstream names, best match first;
            empty when ``hint`` explains the value instead.
    """

    def __init__(
        self,
        param: str,
        value: str,
        *,
        list_name: str,
        fetched: str,
        closest: list[tuple[str, str]],
        hint: str | None = None,
    ) -> None:
        if hint is None and closest:
            hint = "Did you mean " + ", ".join(f"{code} ({name})" for code, name in closest) + "?"
        super().__init__(
            f"{value!r} is not a {param} in PSD's {list_name} list (packaged, fetched "
            f"{fetched}).{' ' + hint if hint else ''} PSD answers unknown codes with an empty "
            "result, so the package refuses them. If PSD added the code since, the packaged "
            "lists need a refresh (/refresh-reference-data).",
            source=SOURCE,
        )
        self.param = param
        self.value = value
        self.list_name = list_name
        self.closest = closest
