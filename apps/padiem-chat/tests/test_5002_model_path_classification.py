"""#5002: every model-boundary test declares its execution path.

The manifest is JSON so the shared conftest can load it without adding an
import that another workflow would have to install.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.model_policy import EXECUTABLE_B14_MODEL_IDS

TESTS = Path(__file__).resolve().parent
MANIFEST = json.loads(
    (TESTS / "model_path_manifest.json").read_text(encoding="utf-8")
)
B14_IMPORT = re.compile(
    r"^\s*(?:from\s+app\.b14_client\s+import|import\s+app\.b14_client"
    r"|from\s+app\s+import\s+b14_client)\b",
    re.MULTILINE,
)
# These are B14-managed boundary tests that reach the checked-in B14 source or
# the shared dispatch authority without a static app.b14_client import. The
# two route-level Chat tests read the identity authority from Core after the
# #5347 tier-aware instruction replaced the fixed module constant.
B14_SOURCE_READERS = frozenset({
    "test_attachments.py",
    "test_auto_grounding.py",
    "test_b66_3906_reasoning_level.py",
    "test_b66_real_b14_source_authority.py",
    "test_tier_route_consumer_coverage.py",
})


def _modules_importing_b14_client() -> set[str]:
    found: set[str] = set()
    for path in TESTS.glob("test_*.py"):
        if B14_IMPORT.search(path.read_text(encoding="utf-8")):
            found.add(path.name)
    return found


def _modules_in(category: str) -> set[str]:
    return {
        module
        for module, declared in MANIFEST["modules"].items()
        if declared == category
    }


def test_categories_are_the_four_independent_paths():
    assert MANIFEST["categories"] == [
        "BYOK_DIRECT",
        "B14_MANAGED",
        "NO_MODEL",
        "MOCK",
    ]
    assert MANIFEST["default_category"] == "NO_MODEL"
    assert set(MANIFEST["markers"]) == set(MANIFEST["categories"])


def test_every_b14_client_importer_is_classified():
    importers = _modules_importing_b14_client() - _modules_in("BYOK_DIRECT")
    assert importers, "expected at least one B14 boundary test"
    declared = _modules_in("B14_MANAGED") - B14_SOURCE_READERS
    assert importers == declared, (
        "new app.b14_client importer must be added to model_path_manifest.json: "
        f"{sorted(importers ^ declared)}"
    )
    assert B14_SOURCE_READERS <= _modules_in("B14_MANAGED")


def test_manifest_modules_exist_and_have_one_path():
    for name, category in MANIFEST["modules"].items():
        assert category in MANIFEST["categories"], name
        assert (TESTS / name).is_file(), name


def test_byok_test_is_direct_and_not_b14_managed():
    byok = "test_5121_byok_chat_direct.py"
    assert MANIFEST["modules"][byok] == "BYOK_DIRECT"
    assert byok in _modules_importing_b14_client()
    assert byok not in _modules_in("B14_MANAGED")


def test_byok_product_e2e_is_direct():
    # #5002 product E2E: real ASGI/D1, substituted provider transport.
    byok = "test_5002_byok_product_e2e.py"
    assert MANIFEST["modules"][byok] == "BYOK_DIRECT"
    assert MANIFEST["markers"][MANIFEST["modules"][byok]] == "byok_direct"


def test_mock_modules_are_never_reported_as_live_e2e():
    # A substitute transport or relay is a logic contract, not LIVE evidence.
    for name in (
        "test_3930_b54_live_sse_relay.py",
        "test_4379_local5_chat_core_integration.py",
        "test_b66_3906_reasoning_level.py",
    ):
        assert MANIFEST["modules"][name] in ("MOCK", "B14_MANAGED")
    assert "LIVE" not in MANIFEST["categories"]


def test_disabled_auto_stays_out_of_the_executable_set():
    from app import model_policy as model_policy_module

    # B1: the retired automatic-selection id is no longer a catalog name at all.
    assert not hasattr(model_policy_module, "AUTO_B14_MODEL_ID")
    assert "b14/auto" not in EXECUTABLE_B14_MODEL_IDS
