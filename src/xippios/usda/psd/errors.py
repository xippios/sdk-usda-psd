"""PSD Online failure modes with a distinct meaning (conventions §5).

A code or attribute id the packaged lists lack is refused with core's
``xippios.core.UnknownCode`` (``params``, ADR-0022).
"""

from xippios.core import NotFoundError

from xippios.usda.psd._client import SOURCE

__all__ = ["NoDataForYear"]


class NoDataForYear(NotFoundError):
    """PSD's own answer for a market year without data (HTTP 404, empty ``text/plain``).

    Recorded for 1900 on all three data forms: one country
    (``get_country_commodity_data_by_year/unknown_year.json``), every country
    (``get_commodity_data_by_year/year_1900.json``) and the world
    (``get_world_commodity_data_by_year/year_1900.json``): status 404, an empty body,
    ``content-type: text/plain; charset=utf-8``. ``_client.classify`` raises it for that
    answer on a data path only. The gateway's 404 (``{"error": {"code": "NOT_FOUND",
    ...}}``, no such route) stays a plain ``NotFoundError``: it says the request is wrong,
    not that the year is empty. ``get_time_series`` skips a year that raises this and
    lets every other error through; the other data tasks raise it again with a message
    naming commodity, country and market year.

    Attributes:
        path: The request path, e.g. ``"/api/psd/commodity/0410000/country/US/year/1900"``.
    """

    def __init__(self, path: str, message: str | None = None) -> None:
        super().__init__(
            message or f"PSD Online has no data for {path} (HTTP 404 with an empty body)",
            source=SOURCE,
        )
        self.path = path
