"""Refresh the packaged reference data from upstream (``/refresh-reference-data``).

For every list in ``LISTS`` this fetches the records through the layer-1 wrapper in
``api/`` (never through a task that might answer from the package) and writes
``reference/<name>.json``: the upstream records verbatim, under upstream's field names,
with the operation and the fetch date. It then regenerates ``enums.py`` with one
``IntEnum`` per id list in ``ENUMS_FROM``: ``UnitId`` from ``unitsOfMeasure`` and
``AttributeId`` from ``commodityAttributes``. Commodity and country codes stay packaged
tables, not enums. Run from the repository root; the list endpoints take the
api.data.gov key, so ``DATA_GOV_API_KEY`` must be in the environment::

    uv run python scripts/refresh_reference.py

Five requests against api.data.gov's hourly quota. Then update the dates in
``reference/README.md``. ``enums.py`` is written as core renders it, ASCII-only and
ruff-clean, with no formatting step after it. ``--render-only`` regenerates
``enums.py`` from the packaged files alone, without a request and without a key.

The enums come from ``xippios.core.reference.render_int_enums`` fed by ``id_name_pairs``
(ADR-0008 amendment): PSD's ids are integers (``attributeId: 28``) and the data records
carry them as integers, so a member must compare equal to one, which an ``IntEnum``
does and a ``StrEnum`` of ``"28"`` would not; and upstream's names are not unique
(``"Total Disappearance"`` is both 126 and 173), so a name several ids share gets
``_<id>`` appended (``TOTAL_DISAPPEARANCE_126``, ``TOTAL_DISAPPEARANCE_173``).
"""

import argparse
import json
from collections.abc import Callable, Coroutine, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xippios.core import UpstreamModel, sync
from xippios.core.reference import id_name_pairs, render_int_enums

from xippios.usda.psd import api
from xippios.usda.psd.params import PACKAGED_LISTS

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "src/xippios/usda/psd"
REFERENCE = PACKAGE_DIR / "reference"
ENUMS = PACKAGE_DIR / "enums.py"
GENERATOR = "scripts/refresh_reference.py"

LISTS: dict[str, tuple[str, Callable[[], Coroutine[Any, Any, Sequence[UpstreamModel]]]]] = {
    "commodities": ("PSDData_GetCommodities", api.PSDData_GetCommodities),
    "countries": ("PSDData_GetCountries", api.PSDData_GetCountries),
    "regions": ("PSDData_GetRegions", api.PSDData_GetRegions),
    "unitsOfMeasure": ("PSDData_GetUnitsOfMeasure", api.PSDData_GetUnitsOfMeasure),
    "commodityAttributes": ("PSDData_GetCommodityAttributes", api.PSDData_GetCommodityAttributes),
}
"""List name, as the upstream path names it, to its operation and wrapper.

Keep the keys in step with ``params.PACKAGED_LISTS``.
"""

ENUMS_FROM: dict[str, tuple[str, str, str]] = {
    "unitsOfMeasure": ("UnitId", "unitId", "unitDescription"),
    "commodityAttributes": ("AttributeId", "attributeId", "attributeName"),
}
"""List name to (enum class, upstream id field, upstream name field), in module order."""


def upstream_record(record: UpstreamModel) -> dict[str, Any]:
    """The record under upstream's field names, as the wrapper's model parsed it."""
    fields = type(record).model_fields
    return {
        str(info.validation_alias or name): getattr(record, name) for name, info in fields.items()
    }


def render_enums(records: Mapping[str, Sequence[Mapping[str, Any]]], *, fetched: str) -> str:
    """``enums.py``: one ``IntEnum`` per list in ``ENUMS_FROM``, rendered by core.

    Args:
        records: List name to its upstream records, e.g. ``{"unitsOfMeasure": [...]}``.
        fetched: The fetch date each class docstring names, e.g. ``"2026-10-23"``.
    """
    lists: dict[str, list[tuple[int, str]]] = {}
    class_names: dict[str, str] = {}
    for name, (cls, id_field, name_field) in ENUMS_FROM.items():
        lists[id_field] = id_name_pairs(records[name], id_field=id_field, name_field=name_field)
        class_names[id_field] = cls
    return render_int_enums(lists, class_names=class_names, fetched=fetched, generator=GENERATOR)


def render_only() -> None:
    """Regenerate ``enums.py`` from the packaged files, without a request."""
    records: dict[str, list[dict[str, Any]]] = {}
    dates: set[str] = set()
    for name in ENUMS_FROM:
        payload = json.loads((REFERENCE / f"{name}.json").read_text(encoding="utf-8"))
        records[name] = payload["records"]
        dates.add(payload["fetched"])
    if len(dates) != 1:
        raise SystemExit(f"the enum lists were fetched on different days: {sorted(dates)}")
    ENUMS.write_text(render_enums(records, fetched=dates.pop()), encoding="utf-8")
    print(f"{ENUMS.name}: {len(records)} enums, from the packaged files")  # noqa: T201


def refresh() -> None:
    """Fetch every list, write its file and regenerate ``enums.py``."""
    if set(LISTS) != set(PACKAGED_LISTS):
        raise SystemExit("LISTS and params.PACKAGED_LISTS name different lists")
    today = datetime.now(UTC).date().isoformat()
    fetched: dict[str, list[dict[str, Any]]] = {}
    REFERENCE.mkdir(exist_ok=True)
    for name, (endpoint, fetch) in LISTS.items():
        records = [upstream_record(record) for record in sync(fetch)()]
        path = REFERENCE / f"{name}.json"
        payload = {"param": name, "endpoint": endpoint, "fetched": today, "records": records}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{path.name}: {len(records)} records")  # noqa: T201
        fetched[name] = records
    ENUMS.write_text(render_enums(fetched, fetched=today), encoding="utf-8")
    print(f"{ENUMS.name}: {len(ENUMS_FROM)} enums")  # noqa: T201


def main() -> None:
    """Refresh from upstream, or with ``--render-only`` regenerate ``enums.py`` alone."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="regenerate enums.py from the packaged files, without a request or a key",
    )
    if parser.parse_args().render_only:
        render_only()
    else:
        refresh()


if __name__ == "__main__":
    main()
