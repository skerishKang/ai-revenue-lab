"""Canonical latest==active lineage precondition matrix (#2451 P1 item 7, #2895).

Network-free and mutation-free. The primitive only compares two ids that the
canonical served-version resolver has already accepted, so every case here is a
plain function call.

Proven here:

1. the three outcomes and their closed reason codes;
2. fail-closed behaviour on missing / unsafe / malformed ids;
3. authority separation: no resolver reimplementation and no mutation-evidence
   duplication (asserted structurally, by import surface and by source scan);
4. the bounded marker vocabulary an adopter publishes, and that an unsafe id is
   never echoed.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github/scripts"

ACTIVE = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


def _load(module_name: str):
    path = SCRIPTS / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before execution: the primitive uses @dataclass(slots=True), which
    # resolves cls.__module__ through sys.modules at class creation time.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


lineage = _load("cloudflare_served_version_lineage")
resolver = _load("cloudflare_served_version")

REASON = lineage.LineageReason


# --- LATEST_EQUALS_ACTIVE = PASS -------------------------------------------


def test_latest_equals_active_passes() -> None:
    decision = lineage.evaluate_latest_equals_active(ACTIVE, ACTIVE)

    assert decision.outcome == lineage.PASS
    assert decision.reason == REASON.EQUAL
    assert decision.passed is True
    assert decision.failed is False
    assert decision.fail_closed is False
    assert decision.active_version_id == ACTIVE
    assert decision.latest_version_id == ACTIVE
    assert f"{lineage.LINEAGE_MARKER}=PASS" in decision.render()


# --- LATEST_DIFFERS_ACTIVE = FAIL ------------------------------------------


def test_latest_differs_active_fails() -> None:
    decision = lineage.evaluate_latest_equals_active(ACTIVE, OTHER)

    assert decision.outcome == lineage.FAIL
    assert decision.reason == REASON.DIFFERENT
    assert decision.passed is False
    assert decision.fail_closed is False
    assert f"{lineage.LINEAGE_MARKER}=FAIL" in decision.render()


# --- FAIL_CLOSED cases ------------------------------------------------------


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_missing_active_fails_closed(missing: object) -> None:
    decision = lineage.evaluate_latest_equals_active(missing, ACTIVE)
    assert decision.outcome == lineage.FAIL_CLOSED
    assert decision.reason == REASON.MISSING_ACTIVE
    assert decision.passed is False


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_missing_latest_fails_closed(missing: object) -> None:
    decision = lineage.evaluate_latest_equals_active(ACTIVE, missing)
    assert decision.outcome == lineage.FAIL_CLOSED
    assert decision.reason == REASON.MISSING_LATEST
    assert decision.latest_version_id is None


@pytest.mark.parametrize(
    "unsafe",
    [
        "bad id with spaces",
        "semi;colon",
        "dollar$sign",
        "back`tick",
        "newline\nid",
        "x" * 65,
        123,
        True,
        {"version_id": ACTIVE},
        [ACTIVE],
    ],
)
def test_unsafe_active_id_fails_closed(unsafe: object) -> None:
    decision = lineage.evaluate_latest_equals_active(unsafe, ACTIVE)
    assert decision.outcome == lineage.FAIL_CLOSED
    assert decision.reason == REASON.UNSAFE_ACTIVE
    assert decision.active_version_id is None


@pytest.mark.parametrize(
    "unsafe",
    ["bad id with spaces", "x" * 65, 123, True, {"id": ACTIVE}],
)
def test_unsafe_latest_id_fails_closed(unsafe: object) -> None:
    decision = lineage.evaluate_latest_equals_active(ACTIVE, unsafe)
    assert decision.outcome == lineage.FAIL_CLOSED
    assert decision.reason == REASON.UNSAFE_LATEST
    assert decision.latest_version_id is None


# --- authority separation ---------------------------------------------------


def test_reuses_canonical_id_contract_without_reimplementing_the_resolver() -> None:
    # The precondition and the resolver must agree on the id charset, and the
    # precondition must not carry its own copy of the rule.
    for value in (ACTIVE, "bad id with spaces", "", 123, None, "x" * 65):
        assert lineage.is_safe_version_id(value) is resolver.is_safe_version_id(value)

    source = (SCRIPTS / "cloudflare_served_version_lineage.py").read_text(encoding="utf-8")
    assert "is_safe_version_id" in source
    # No second resolver: these definitions belong to the canonical resolver only
    # and must not be restated here (checked against definitions, not prose).
    for forbidden in (
        "class ServedVersionReason",
        "class ServedVersionResolutionError",
        "def resolve_served_version_id(",
        "SERVED_VERSION_ID_RE =",
        "FULL_TRAFFIC_PERCENTAGE =",
    ):
        assert forbidden not in source, forbidden


def test_does_not_duplicate_mutation_evidence_authority() -> None:
    source = (SCRIPTS / "cloudflare_served_version_lineage.py").read_text(encoding="utf-8")
    for forbidden in (
        "MUTATION_CLASSES",
        "CODE_DEPLOY",
        "SECRET_PUT",
        "ROLLBACK",
        "MIN_SAME_VERSION_OBSERVATIONS",
        "POLL_ATTEMPTS",
    ):
        assert forbidden not in source, forbidden


def test_module_performs_no_network_mutation_or_secret_read() -> None:
    source = (SCRIPTS / "cloudflare_served_version_lineage.py").read_text(encoding="utf-8")
    for forbidden in (
        "import urllib",
        "import httpx",
        "import requests",
        "import socket",
        "import subprocess",
        "os.environ",
        "getenv",
    ):
        assert forbidden not in source, forbidden

    decision = lineage.evaluate_latest_equals_active(ACTIVE, OTHER)
    payload = decision.safe_dict()
    assert payload["http_calls"] == 0
    assert payload["envelope_fetch"] == 0
    assert payload["cloudflare_mutation"] == 0
    assert payload["secret_read"] == 0
    assert json.loads(json.dumps(payload)) == payload


# --- bounded, non-leaking output -------------------------------------------


def test_render_never_echoes_an_unsafe_id() -> None:
    unsafe = "secret-looking value; rm -rf /"
    decision = lineage.evaluate_latest_equals_active(ACTIVE, unsafe)
    rendered = "\n".join(decision.render())

    assert unsafe not in rendered
    assert lineage.REFUSED_PLACEHOLDER in rendered
    assert f"{lineage.LINEAGE_MARKER}=FAIL" in rendered
    assert "SERVED_VERSION_LINEAGE_SECRET_READ=0" in rendered
    assert decision.safe_dict()["latest_version_id"] == lineage.REFUSED_PLACEHOLDER


def test_rendered_marker_keys_are_stable() -> None:
    decision = lineage.evaluate_latest_equals_active(ACTIVE, ACTIVE)
    keys = [line.split("=", 1)[0] for line in decision.render()]
    assert keys == [
        lineage.LINEAGE_MARKER,
        "SERVED_VERSION_LINEAGE_OUTCOME",
        "SERVED_VERSION_LINEAGE_REASON",
        "SERVED_VERSION_LINEAGE_ACTIVE_VERSION",
        "SERVED_VERSION_LINEAGE_LATEST_VERSION",
        "SERVED_VERSION_LINEAGE_HTTP_CALLS",
        "SERVED_VERSION_LINEAGE_ENVELOPE_FETCH",
        "SERVED_VERSION_LINEAGE_MUTATION",
        "SERVED_VERSION_LINEAGE_SECRET_READ",
    ]


def test_unknown_outcome_is_refused() -> None:
    with pytest.raises(ValueError):
        lineage.LineageDecision("MAYBE", REASON.EQUAL, ACTIVE, ACTIVE)


# --- CLI --------------------------------------------------------------------


def test_cli_exit_codes_and_markers(capsys) -> None:
    assert lineage.main(["--active-version", ACTIVE, "--latest-version", ACTIVE]) == 0
    assert f"{lineage.LINEAGE_MARKER}=PASS" in capsys.readouterr().out

    assert lineage.main(["--active-version", ACTIVE, "--latest-version", OTHER]) == 1
    assert f"{lineage.LINEAGE_MARKER}=FAIL" in capsys.readouterr().out

    assert lineage.main(["--active-version", "", "--latest-version", ACTIVE]) == 2
    out = capsys.readouterr().out
    assert "SERVED_VERSION_LINEAGE_OUTCOME=FAIL_CLOSED" in out
    assert "SERVED_VERSION_LINEAGE_REASON=missing-active" in out

    assert lineage.main(
        ["--active-version", ACTIVE, "--latest-version", ACTIVE, "--format", "json"]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == lineage.PASS


def test_cli_accepts_resolved_id_objects(capsys) -> None:
    assert lineage.main(
        [
            "--active-version",
            json.dumps({"version_id": ACTIVE}),
            "--latest-version",
            json.dumps({"version_id": ACTIVE}),
        ]
    ) == 0
    assert f"{lineage.LINEAGE_MARKER}=PASS" in capsys.readouterr().out
