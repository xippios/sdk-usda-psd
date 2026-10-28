"""Refresh the packaged reference data from upstream (``/refresh-reference-data``).

Every list in ``LISTS``, ``ID_LISTS`` or ``TABLES`` is fetched through its layer-1 wrapper
in ``api/``, never through a task that might answer from the package; once all are
fetched, each is written to ``reference/<name>.json`` by core's ``PackagedList.write``:
the list's name, the operation it came from, the UTC time of the fetch to the second and
upstream's records under upstream's field names (``dump_upstream``), a value list as
records of one field named by the list (conventions §3). Then ``enums.py`` is regenerated
from the packaged files by one ``xippios.core.reference.render_enums`` call, a ``StrEnum``
per value list in ``LISTS`` and an ``IntEnum`` per list of integer ids and names in
``ID_LISTS`` (``id_name_pairs``), so that a member compares equal to the id in upstream's
data, each class naming the day its list was fetched; and formatted with ``ruff format``
and ``ruff check --fix``, as it is committed (ADR-0008). ``TABLES``, this package's own
and now the template's too, are record lists packaged without an enum. Where a member
name derives to nothing, or two collide, name it by hand in ``render``'s call:
``render_enums(member_names=...)``, per list and value (an id for an ``IntEnum``).

PSD publishes five lists, all of them records: ``unitsOfMeasure`` and
``commodityAttributes`` are id lists, which make ``UnitId`` and ``AttributeId``;
``commodities``, ``countries`` and ``regions`` stay tables, not enums. PSD has no value
list, so ``LISTS`` stays empty. The list endpoints take the api.data.gov key, so
``DATA_GOV_API_KEY`` must be in the environment; run from the repository root::

    uv run python scripts/refresh_reference.py

Five requests against api.data.gov's hourly quota, shared with every package using the
key. Then update the times in ``reference/README.md``. Only lists that are the same for
every caller are packaged; a multi-tenant source packages no tenant data (ADR-0014),
which PSD is not.

``--render-only`` regenerates ``enums.py`` from the packaged ``reference/*.json`` alone,
without a request and without a key: after a core release changes the renderer
(conventions §15, item 6), it changes ``enums.py`` and nothing else.

PSD's ids are integers (``attributeId: 28``) and the data records carry them as integers,
so a member must compare equal to one, which an ``IntEnum`` does and a ``StrEnum`` of
``"28"`` would not; and upstream's names are not unique (``"Total Disappearance"`` is
both 126 and 173), so a name several ids share gets ``_<id>`` appended
(``TOTAL_DISAPPEARANCE_126``, ``TOTAL_DISAPPEARANCE_173``).
"""

import argparse
import subprocess
import sys
from collections.abc import Callable, Coroutine, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xippios.core import PackagedList, UpstreamModel, sync
from xippios.core.reference import id_name_pairs, render_enums

from xippios.usda.psd import api
from xippios.usda.psd.params import PACKAGED_LISTS

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "src/xippios/usda/psd"
REFERENCE = PACKAGE_DIR / "reference"
ENUMS = PACKAGE_DIR / "enums.py"
GENERATOR = "scripts/refresh_reference.py"

Values = Callable[[], Coroutine[Any, Any, Sequence[str]]]
"""An async fetcher of a list's values through ``api/``."""

Records = Callable[[], Coroutine[Any, Any, Sequence[UpstreamModel]]]
"""An async fetcher of a list's records through ``api/``, e.g. the wrapper itself."""

LISTS: dict[str, tuple[str, Values]] = {}
"""Value lists, one ``StrEnum`` each: PSD publishes none, its lists are records."""

ID_LISTS: dict[str, tuple[str, Records, str, str]] = {
    "unitsOfMeasure": (
        "PSDData_GetUnitsOfMeasure",
        api.get_units_of_measure,
        "unitId",
        "unitDescription",
    ),
    "commodityAttributes": (
        "PSDData_GetCommodityAttributes",
        api.get_commodity_attributes,
        "attributeId",
        "attributeName",
    ),
}
"""Lists of integer ids and names, one ``IntEnum`` each (conventions §3), in module order.

List name, as the upstream path names it, to (upstream operation, wrapper, id field, name
field), the operation verbatim as the snapshot's ``operationId`` and the fields as
upstream names them. Each enum is keyed by its id field and named after it, so ``unitId``
makes ``UnitId``, whose docstring reads "Values of ``unitId``".
"""

TABLES: dict[str, tuple[str, Records]] = {
    "commodities": ("PSDData_GetCommodities", api.get_commodities),
    "countries": ("PSDData_GetCountries", api.get_countries),
    "regions": ("PSDData_GetRegions", api.get_regions),
}
"""Record lists packaged as tables, with no enum: commodity, country and region codes.

List name, as the upstream path names it, to (upstream operation, wrapper). Packaged like
an id list, as upstream's records under upstream's field names, which ``params`` reads;
the three lists together with ``ID_LISTS`` are ``params.PACKAGED_LISTS``.
"""


def packaged(name: str, endpoint: str, records: Sequence[dict[str, Any]]) -> PackagedList:
    """The list ``name`` as just fetched from ``endpoint``, for ``reference/<name>.json``.

    ``endpoint`` is the upstream operation verbatim, never the wrapper's name, which drops
    the ``PSDData_`` prefix (conventions §2): it becomes the file's ``endpoint`` and so the
    ``list_*`` tasks' ``meta.endpoint``.
    """
    return PackagedList(
        param=name, endpoint=endpoint, fetched=datetime.now(UTC), records=list(records)
    )


def read(name: str) -> PackagedList:
    """The packaged ``reference/<name>.json``, as ``refresh`` wrote it."""
    path = REFERENCE / f"{name}.json"
    if not path.is_file():
        raise SystemExit(f"{path.name} is not packaged yet: run the script without --render-only")
    return PackagedList.model_validate_json(path.read_text(encoding="utf-8"))


def render() -> None:
    """Regenerate ``enums.py`` from the packaged files and format it as it is committed."""
    lists: dict[str, Sequence[str] | Sequence[tuple[int, str]]] = {}
    fetched: dict[str, str] = {}
    class_names: dict[str, str] = {}
    keys = [*LISTS, *(id_field for _, _, id_field, _ in ID_LISTS.values())]
    if len(set(keys)) < len(keys):
        raise SystemExit("an id field of ID_LISTS names a list of LISTS: one enum each")
    for name in LISTS:
        values = read(name)
        lists[name] = [record[name] for record in values.records]
        fetched[name] = f"{values.fetched:%Y-%m-%d}"
    for name, (_, _, id_field, name_field) in ID_LISTS.items():
        ids = read(name)
        lists[id_field] = id_name_pairs(ids.records, id_field=id_field, name_field=name_field)
        fetched[id_field] = f"{ids.fetched:%Y-%m-%d}"
        class_names[id_field] = id_field[:1].upper() + id_field[1:]
    module = render_enums(lists, fetched=fetched, class_names=class_names, generator=GENERATOR)
    ENUMS.write_text(module, encoding="utf-8")
    sys.stdout.flush()
    for command in (["format"], ["check", "--fix"]):
        run = subprocess.run([sys.executable, "-m", "ruff", *command, str(ENUMS)], cwd=ROOT)
        if run.returncode:
            raise SystemExit(f"ruff {' '.join(command)} left {ENUMS.name} failing")
    print(f"{ENUMS.name}: {len(lists)} enums")  # noqa: T201


def refresh() -> None:
    """Fetch every list, then write its file, then regenerate ``enums.py`` from the files."""
    if sorted([*LISTS, *ID_LISTS, *TABLES]) != sorted(PACKAGED_LISTS):
        raise SystemExit("LISTS, ID_LISTS and TABLES name other lists than params.PACKAGED_LISTS")
    lists = [
        *(
            packaged(name, endpoint, [{name: value} for value in sync(fetch)()])
            for name, (endpoint, fetch) in LISTS.items()
        ),
        *(
            packaged(name, endpoint, [record.dump_upstream() for record in sync(fetch)()])
            for name, (endpoint, fetch) in TABLES.items()
        ),
        *(
            packaged(name, endpoint, [record.dump_upstream() for record in sync(fetch)()])
            for name, (endpoint, fetch, _, _) in ID_LISTS.items()
        ),
    ]
    REFERENCE.mkdir(exist_ok=True)
    for fetched in lists:
        path = REFERENCE / f"{fetched.param}.json"
        fetched.write(path)
        print(f"{path.name}: {len(fetched.records)} records from {fetched.endpoint}")  # noqa: T201
    render()


def main() -> None:
    """Refresh from upstream, or with ``--render-only`` regenerate ``enums.py`` alone."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="regenerate enums.py from the packaged reference/*.json, without a request or a key",
    )
    args = parser.parse_args()
    if args.render_only:
        render()
    else:
        refresh()


if __name__ == "__main__":
    main()
