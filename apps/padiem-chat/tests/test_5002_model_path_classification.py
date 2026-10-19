"""#5002: every model-boundary test declares its execution path."""

from __future__ import annotations

import re
from pathlib import Path

from app.model_policy import AUTO_B14_MODEL_ID, EXECUTABLE_B14_MODEL_IDS
import model_path_manifest

TESTS = Path(__file__).resolve().parent
B14_IMPORT = re.compile(
    r"^\s*(?:from\s+app\.b14_client\s+import|import\s+app\.b14_client"
    r"|from\s+app\s+import\s+b14_client)\b",
    re.MULTILINE,
)
# These execute the checked-in B14 source or read its authority directly.
B14_SOURCE_READERS = frozenset({
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


def test_categories_are_the_four_independent_paths():
    assert set(model_path_manifest.CATEGORIES) == {
        model_path_manifest.BYOK_DIRECT,
        model_path_manifest.B14_MANAGED,
        model_path_manifest.NO_MODEL,
        model_path_manifest.MOCK,
    }
    assert model_path_manifest.DEFAULT_CATEGORY == model_path_manifest.NO_MODEL


def test_every_b14_client_importer_is_classified():
    importers = _modules_importing_b14_client() - model_path_manifest.BYOK_DIRECT_MODULES
    assert importers, "expected at least one B14 boundary test"
    declared = model_path_manifest.B14_MANAGED_MODULES - B14_SOURCE_READERS
    assert importers == declared, (
        "new app.b14_client importer must be added to model_path_manifest: "
        f"{sorted(importers ^ declared)}"
    )
    assert B14_SOURCE_READERS <= model_path_manifest.B14_MANAGED_MODULES


def test_manifest_modules_exist_and_have_one_path():
    listed = set(model_path_manifest.MODULE_CATEGORIES)
    missing = {name for name in listed if not (TESTS / name).is_file()}
    assert not missing
    for name in listed:
        category = model_path_manifest.path_for_module(name)
        assert category in model_path_manifest.CATEGORIES


def test_byok_test_is_direct_and_not_b14_managed():
    byok = "test_5121_byok_chat_direct.py"
    assert model_path_manifest.path_for_module(byok) == model_path_manifest.BYOK_DIRECT
    assert byok in _modules_importing_b14_client()
    assert byok in model_path_manifest.BYOK_DIRECT_MODULES


def test_mock_modules_are_never_reported_as_live_e2e():
    # A substitute transport or relay is a logic contract, not LIVE evidence.
    for name in (
        "test_3930_b54_live_sse_relay.py",
        "test_4379_local5_chat_core_integration.py",
        "test_b66_3906_reasoning_level.py",
    ):
        category = model_path_manifest.path_for_module(name)
        assert category in (model_path_manifest.MOCK, model_path_manifest.B14_MANAGED)
    assert "LIVE" not in model_path_manifest.CATEGORIES


def test_disabled_auto_stays_out_of_the_executable_set():
    assert AUTO_B14_MODEL_ID == "b14/auto"
    assert AUTO_B14_MODEL_ID not in EXECUTABLE_B14_MODEL_IDS
