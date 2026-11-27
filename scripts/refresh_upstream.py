"""Refresh the upstream documentation snapshot in ``docs/upstream/`` (``/refresh-upstream``).

The script declares the snapshot, a ``Snapshot`` of ``xippios.core.refresh``, and runs it on
core's frame (conventions §3): the fetch through core's client, which the frame builds without
credentials and names after the package, the attribution check, ``FETCHED.md``, the write and
``--check`` are the frame's, the same in every source. The FAS Open Data Services portal
(https://apps.fas.usda.gov/opendatawebV2/) documents ESR, GATS and PSD alike, and what the three
FAS sources read of it is the kit of the shared package, ``xippios.usda.fas.portal``'s
``Portal``: the portal's pages, the cut of its two Swagger documents to one service's paths, the
backend document that the classic Swagger UI names, the comparison of the two, and the
paragraphs that say how. This script keeps what is PSD's own: the prefix ``/api/psd/``, PSD
Online's page, FAS's data page, their notes and the paragraph on them. It writes:

- ``openapi/portal-document.json``: the PSD part of the portal's document;
- ``openapi/backend-docs-v1.json``: the PSD part of the API's own document;
- ``FETCHED.md``: written whole by the frame, one row per file and per page recorded without
  a file (the two shells of the portal and PSD Online's page), and FAS's data page, which the
  CDN refuses to headless clients, under ``Not fetched``.

No key is needed or read. Run from the repository root::

    uv run python scripts/refresh_upstream.py            # fetch and write
    uv run python scripts/refresh_upstream.py --check    # fetch and compare, write nothing
"""

from xippios.core.refresh import Page, Row, Snapshot, run
from xippios.usda.fas.portal import Portal, shell_text

PORTAL = Portal("/api/psd/")
"""The portal as PSD's snapshot reads it: its pages first, and its hooks."""

PSDONLINE_URL = "https://apps.fas.usda.gov/psdonline/"
"""PSD Online, this package's ``Upstream`` URL, which redirects to its application's shell."""
PSDONLINE_MARKER = 'ng-app="app"'
"""The mount point of PSD Online's client-rendered shell."""
FAS_DATA_URL = "https://www.fas.usda.gov/data"
"""FAS's data page, which the CDN refuses to headless clients."""


def note(row: Row) -> str:
    """The row's note: PSD Online's page held to a shell, else the kit's or the page's own."""
    if row.page.url == PSDONLINE_URL:
        shell_text(row.response, PSDONLINE_MARKER)
        return "client-rendered shell, no documentation text"
    return PORTAL.note(row)


OWN = (
    f"PSD Online's page, {PSDONLINE_URL}, redirects to its application's page, a "
    "client-rendered shell without documentation text like the portal's, and gets no file, "
    f"only a row with its HTTP status and the size and sha256 of the body. FAS's data page, "
    f"{FAS_DATA_URL}, answers 403 Access Denied at the CDN edge to headless clients, a body "
    "that carries a per-request reference number."
)
"""PSD's own paragraph of "How this is captured", after the kit's four."""


SNAPSHOT = Snapshot(
    name="USDA FAS PSD Online",
    slug="usda-psd",
    pages=(
        *PORTAL.pages,
        Page(PSDONLINE_URL),
        Page(
            FAS_DATA_URL,
            status=403,
            stable=False,
            names="Access Denied",
            note="FAS's data page; 403 Access Denied at the CDN edge",
        ),
    ),
    capture=f"{PORTAL.capture}\n\n{OWN}",
    reduce=PORTAL.reduce,
    linked=PORTAL.linked,
    note=note,
    sections=PORTAL.sections,
)
"""The snapshot: the portal's shell and its document, the classic Swagger UI and the backend
document it names, PSD Online's page and FAS's data page that the CDN refuses. Neither
document states a copyright line, a licence or terms, so the attribution is empty, and the
frame stops a run on a page that comes to state one."""


if __name__ == "__main__":
    raise SystemExit(run(SNAPSHOT))
