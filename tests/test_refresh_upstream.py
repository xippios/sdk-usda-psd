"""``scripts/refresh_upstream.py``'s own code, offline: its ``Snapshot`` and its own hooks.

The script declares a ``Snapshot`` that sdk-core's frame runs, ``xippios.core.refresh``
(conventions §3): the fetch through core's client, ``FETCHED.md``, the write and ``--check``
are the frame's, and core's tests hold them. The portal's pages, the hooks that read them and
the paragraphs that say how are the kit of the FAS portal in ``xippios.usda.fas``, whose tests
hold its units. The tests here hold what the script declares on the kit, its own pages, its
own paragraph and its own note, and that the kit's cut reproduces the committed PSD part.
Nothing here sends a request or writes under ``docs/upstream/``. ``OBSERVED.md`` is the one
file under ``docs/upstream/`` written by hand (conventions §3, sdk-core ADR-0028).
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from xippios.core.refresh import Page, Response, Row
from xippios.usda.fas.portal import Portal

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_upstream.py"
UPSTREAM = ROOT / "docs" / "upstream"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_upstream", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


PORTAL_FILE = "openapi/portal-document.json"
"""The committed PSD part of the portal's document, the file of the kit's second page."""
PORTAL = UPSTREAM / PORTAL_FILE


def portal_page() -> Page:
    pages: tuple[Page, ...] = script.SNAPSHOT.pages
    (page,) = [page for page in pages if page.file == PORTAL_FILE]
    return page


def answer(url: str, status: int, body: bytes, content_type: str) -> Response:
    """An answer as a run reads it, composed by the test.

    It is an input of the test, not an answer from USDA FAS PSD Online.
    """
    return Response(
        url=url,
        status=status,
        body=body,
        content_type=content_type,
        etag=None,
        last_modified=None,
        redirects=(),
    )


def portal_answer() -> Response:
    """The portal's document as a run reads it, here composed from the snapshot.

    NOT RECORDED as served: the body is composed from what the snapshot documents, the PSD
    part of the portal's document that the capture of 2026-10-28 kept in ``PORTAL``, read at
    test time without its final newline, in the shape upstream answered the whole document,
    the text ``json.dumps(indent=2, ensure_ascii=False)`` reproduces. The tests assert what
    the script makes of it, never that upstream sends it. The answer is an input of the test,
    not an answer from USDA FAS PSD Online. (conventions §10; sdk-core ADR-0064, decision 9)
    """
    return answer(
        portal_page().url, 200, PORTAL.read_bytes().removesuffix(b"\n"), "application/json"
    )


def test_the_script_builds_on_the_kit_of_the_portal_for_psd() -> None:
    """One ``Portal`` for PSD's prefix, whose hooks the snapshot takes, but ``note``, which
    names the script's own page first."""
    assert isinstance(script.PORTAL, Portal)
    assert (script.PORTAL.prefix, script.PORTAL.service) == ("/api/psd/", "PSD")
    snapshot = script.SNAPSHOT
    assert (snapshot.name, snapshot.slug) == ("USDA FAS PSD Online", "usda-psd")
    assert snapshot.reduce == script.PORTAL.reduce
    assert snapshot.linked == script.PORTAL.linked
    assert snapshot.sections == script.PORTAL.sections
    assert snapshot.note is script.note


def test_reduce_cuts_a_document_to_its_psd_part_as_committed() -> None:
    """The kit's cut, applied to the PSD part itself, gives back the committed part byte for
    byte: its paths, the definitions they reference, in upstream order,
    ``json.dumps(indent=2, ensure_ascii=False)`` and a final newline."""
    assert script.SNAPSHOT.reduce(portal_page(), portal_answer()) == PORTAL.read_bytes()


def test_a_document_row_counts_the_paths_kept_and_dropped() -> None:
    """The script's ``note`` leaves a document's row to the kit, which names what the cut
    kept; the frame adds that the row's Bytes and sha256 are the whole document's
    (``excerpt``)."""
    page, response = portal_page(), portal_answer()
    assert page.excerpt
    content = script.SNAPSHOT.reduce(page, response)
    note = script.SNAPSHOT.note(Row(page, response, content, page.note))
    assert note == (
        "PSD part: kept 9 `/api/psd/` paths; dropped none (out of scope here, own packages); "
        "kept 0 of 0 definitions"
    )


def test_the_snapshot_declares_its_pages_in_order() -> None:
    """The kit's pages first, the portal's three, whose own tests hold them; then PSD's own:
    PSD Online's page, a shell, and FAS's data page, which the CDN refuses and which goes to
    ``Not fetched``."""
    pages = script.SNAPSHOT.pages
    assert pages[:3] == script.PORTAL.pages
    assert [(page.url, page.file, page.status) for page in pages[3:]] == [
        (script.PSDONLINE_URL, None, 200),
        (script.FAS_DATA_URL, None, 403),
    ]
    assert portal_page() in pages[:3], "the kit's document page writes the committed part"
    refused = pages[4]
    assert (refused.stable, refused.names) == (False, "Access Denied")
    assert script.SNAPSHOT.attribution == (), "neither document states a copyright line"


def test_psd_onlines_row_holds_the_page_to_a_shell() -> None:
    """The script's own note for PSD Online's page, from its answer: a small shell that holds
    its mount point, which the kit's ``shell_text`` checks; a page that lost it stops the run."""
    page = next(page for page in script.SNAPSHOT.pages if page.url == script.PSDONLINE_URL)
    shell = answer(
        script.PSDONLINE_URL, 200, b'<html ng-app="app"><body></body></html>', "text/html"
    )
    assert script.note(Row(page, shell, None, page.note)) == (
        "client-rendered shell, no documentation text"
    )
    other = answer(script.PSDONLINE_URL, 200, b"<html><body>text</body></html>", "text/html")
    with pytest.raises(SystemExit, match="mount point"):
        script.note(Row(page, other, None, page.note))


def test_the_capture_is_the_kit_s_then_psd_s_own_paragraph() -> None:
    """How this is captured: the kit's four paragraphs, then PSD's own on PSD Online's page and
    FAS's data page, which leaves the shells' bound to the kit's."""
    capture = script.SNAPSHOT.capture
    assert capture.startswith(f"{script.PORTAL.capture}\n\n")
    own = capture.removeprefix(f"{script.PORTAL.capture}\n\n")
    assert own.startswith("PSD Online's page")
    assert "\n\n" not in own, "one paragraph of the script's own"
    assert "bytes" not in own, "the shells' bound is the kit's to state"


def test_fetched_md_says_when_and_where_the_portal_document_was_found() -> None:
    """How this is captured dates the find of the portal's Swagger document.

    It states what was fetched, when and where the URL stood, which a reader of the snapshot
    can check against the portal, and names nobody who fetched it or where they kept the
    copies; nor does the script's own text.
    """
    text = " ".join(script.SNAPSHOT.capture.split())
    found = (
        "On 2026-10-23, when sdk-usda-psd's snapshot was set up, the portal page and its"
        " JavaScript bundle were fetched into a temporary directory and that URL was found in"
        " the bundle's Swagger UI configuration; those copies have since been deleted, and this"
        " script reuses the URL."
    )
    assert found in text
    assert "scratch" not in text
    assert "scratch" not in SCRIPT.read_text(encoding="utf-8")
