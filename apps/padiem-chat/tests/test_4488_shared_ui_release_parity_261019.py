"""#4488: the shared conversation UI copies are guarded on the release paths.

Both products now load `shared-conversation-composer.js` and
`shared-conversation-scroll.js` from `packages/padiem-conversation-ui/`. The
composer bytes were already checked in the B62 production gate and the B66
Pages release, while the scroll copy had no release-path check at all — a
diverged scroll module could ship while both products still claim parity.

This contract fails if either release path stops verifying either module: the
copy is only "shared" while the shipped bytes are proven equal to the canonical
source at release time.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github/workflows"
B62_GATE = WORKFLOWS / "b62-production-code-deploy-gate.yml"
B66_PAGES = WORKFLOWS / "b66-neutral-pages-beta.yml"
SYNC_COMPOSER = "scripts/sync_shared_conversation_composer.py --check"
SYNC_SCROLL = "scripts/sync_shared_conversation_scroll.py --check"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_b62_production_gate_checks_both_shared_modules():
    text = _text(B62_GATE)
    assert SYNC_COMPOSER in text
    assert SYNC_SCROLL in text


def test_b66_pages_release_checks_both_shared_modules():
    text = _text(B66_PAGES)
    assert SYNC_COMPOSER in text
    assert SYNC_SCROLL in text


def test_release_paths_run_the_check_after_source_verification():
    """The parity check must sit in the verified-source step, not before it."""
    b66 = _text(B66_PAGES)
    assert b66.index('test -f "${SOURCE_DIR}/index.html"') < b66.index(SYNC_SCROLL)


def test_shared_module_changes_trigger_the_release_paths():
    """A canonical edit alone must be able to trigger both release checks."""
    for path in (B62_GATE, B66_PAGES):
        text = _text(path)
        assert "packages/padiem-conversation-ui/**" in text, path.name
        assert "scripts/sync_shared_conversation_scroll.py" in text, path.name


def test_products_ship_the_canonical_scroll_bytes():
    canonical = (ROOT / "packages/padiem-conversation-ui/scroll-follow.js").read_bytes()
    for relative in (
        "apps/padiem-chat/static/shared-conversation-scroll.js",
        "reference/business-66-padiem-quote-v1/shared-conversation-scroll.js",
    ):
        assert (ROOT / relative).read_bytes() == canonical, relative
