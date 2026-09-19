"""Canonical served-version resolver primitive matrix (#2451 P1, #2737).

Network-free. Every payload below is a synthetic Cloudflare API response.

Three things are proven here:

1. the primitive's own canonical contract -- the exact pass shapes and one
   assertion per closed failure reason code;
2. convergence: the four former resolver implementations
   (``b54_engine_served_version_guard``, ``b62_served_version_secret_guard``,
   ``b62_script_lineage_comparator``, ``b62_live_content_marker_probe``) now
   agree on every payload, each raising its own published error type;
3. the one intentional behavior change: a syntactically unsafe but non-blank
   ``version_id`` that the B62 guard used to accept is now refused in every
   lane, which is the #2451 canonical target
   (``VERSION_ID=non-empty + safe charset``).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github/scripts"

ACTIVE = "11111111-1111-1111-1111-111111111111"
PREVIOUS = "22222222-2222-2222-2222-222222222222"


def _load(module_name: str):
    path = SCRIPTS / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


primitive = _load("cloudflare_served_version")
b54_guard = _load("b54_engine_served_version_guard")
b62_guard = _load("b62_served_version_secret_guard")
lineage = _load("b62_script_lineage_comparator")
marker = _load("b62_live_content_marker_probe")

REASON = primitive.ServedVersionReason


def envelope(*deployments, success: bool = True) -> dict:
    return {"success": success, "result": {"deployments": list(deployments)}}


def deployment(*versions) -> dict:
    return {"versions": list(versions)}


def served(version_id: object = ACTIVE, percentage: object = 100) -> dict:
    return {"version_id": version_id, "percentage": percentage}


# --- the four lanes, called through one adapter shape --------------------------

LANES: dict[str, tuple[Callable[[object], str], type[Exception]]] = {
    "primitive": (primitive.resolve_served_version_id,
                  primitive.ServedVersionResolutionError),
    "b54_engine_guard": (b54_guard.resolve_active, b54_guard.ServedVersionGuardError),
    "b62_secret_guard": (b62_guard.resolve_served_version_id,
                         b62_guard.ServedVersionGuardError),
    "lineage_comparator": (lineage.resolve_active_version, lineage.LineageError),
    "marker_probe": (lambda payload: marker.resolve_active_version(payload, "pre"),
                     marker.LiveContentError),
}

LANE_NAMES = list(LANES)


# --- canonical pass shapes ------------------------------------------------------

def test_primitive_resolves_canonical_single_full_traffic_version() -> None:
    assert primitive.resolve_served_version_id(envelope(deployment(served()))) == ACTIVE


def test_primitive_resolves_first_entry_of_deployment_history() -> None:
    # The endpoint returns history; the first entry is the actively serving
    # deployment and later entries are previous deployments, not ambiguity.
    payload = envelope(
        deployment(served(ACTIVE)),
        deployment(served(PREVIOUS, 0)),
        deployment(served("33333333-3333-3333-3333-333333333333", 0)),
    )
    assert primitive.resolve_served_version_id(payload) == ACTIVE


@pytest.mark.parametrize("version_id", ["a", "ver-A", "ver_A.1", "9" * 64, ACTIVE])
def test_primitive_accepts_safe_charset_ids(version_id: str) -> None:
    payload = envelope(deployment(served(version_id)))
    assert primitive.resolve_served_version_id(payload) == version_id


def test_is_safe_version_id_predicate() -> None:
    assert primitive.is_safe_version_id(ACTIVE) is True
    assert primitive.is_safe_version_id("ver A") is False
    assert primitive.is_safe_version_id("") is False
    assert primitive.is_safe_version_id(None) is False
    assert primitive.is_safe_version_id(123) is False
    assert primitive.is_safe_version_id("9" * 65) is False


# --- every refusal maps to exactly one closed reason code ----------------------

# (payload, expected reason code, test id)
REJECTIONS: list[tuple[object, str, str]] = [
    (
        [
            {"versions": [{"version_id": ACTIVE, "percentage": 100}]},
            {"versions": [{"version_id": PREVIOUS, "percentage": 100}]},
        ],
        REASON.ENVELOPE,
        "raw-list-descending",
    ),
    (
        [
            {"versions": [{"version_id": PREVIOUS, "percentage": 0}]},
            {"versions": [{"version_id": ACTIVE, "percentage": 100}]},
        ],
        REASON.ENVELOPE,
        "raw-list-ascending",
    ),
    ("not-an-object", REASON.ENVELOPE, "string-payload"),
    (None, REASON.ENVELOPE, "none-payload"),
    (42, REASON.ENVELOPE, "int-payload"),
    ({"success": False, "result": None}, REASON.ENVELOPE, "unsuccessful-envelope"),
    ({"success": True}, REASON.RESULT_OBJECT, "result-missing"),
    ({"success": True, "result": []}, REASON.RESULT_OBJECT, "list-shaped-result"),
    ({"success": True, "result": None}, REASON.RESULT_OBJECT, "null-result"),
    (
        {"success": True, "result": {"versions": [{"id": ACTIVE, "percentage": 100}]}},
        REASON.DEPLOYMENT_RECORDS,
        "result-versions-shortcut-bare-id",
    ),
    (
        {"success": True, "result": {"versions": [served(ACTIVE)]}},
        REASON.DEPLOYMENT_RECORDS,
        "result-versions-shortcut",
    ),
    (envelope(), REASON.DEPLOYMENT_RECORDS, "empty-deployments"),
    (
        {"success": True, "result": {"deployments": "not-a-list"}},
        REASON.DEPLOYMENT_RECORDS,
        "deployments-not-a-list",
    ),
    (
        {"success": True, "result": {"deployments": ["not-an-object"]}},
        REASON.DEPLOYMENT_ENTRY,
        "deployment-entry-not-an-object",
    ),
    (envelope(deployment()), REASON.VERSION_COUNT, "no-versions"),
    (
        envelope(deployment(served(ACTIVE), served(PREVIOUS))),
        REASON.VERSION_COUNT,
        "two-versions",
    ),
    (
        {"success": True, "result": {"deployments": [{"versions": "not-a-list"}]}},
        REASON.VERSION_COUNT,
        "versions-not-a-list",
    ),
    (
        envelope(deployment("not-an-object")),
        REASON.VERSION_ENTRY,
        "version-entry-not-an-object",
    ),
    (
        envelope(deployment({"version_id": ACTIVE})),
        REASON.TRAFFIC,
        "percentage-missing",
    ),
    (envelope(deployment(served(ACTIVE, 90))), REASON.TRAFFIC, "partial-traffic-90"),
    (envelope(deployment(served(ACTIVE, 0))), REASON.TRAFFIC, "zero-traffic"),
    (envelope(deployment(served(ACTIVE, "100"))), REASON.TRAFFIC, "percentage-string"),
    (
        envelope(deployment({"id": ACTIVE, "percentage": 100})),
        REASON.VERSION_ID,
        "bare-id-instead-of-version-id",
    ),
    (
        envelope(deployment({"percentage": 100})),
        REASON.VERSION_ID,
        "version-id-missing",
    ),
    (envelope(deployment(served(""))), REASON.VERSION_ID, "empty-version-id"),
    (envelope(deployment(served("   "))), REASON.VERSION_ID, "whitespace-version-id"),
    (
        envelope(deployment(served("ver A; rm -rf /"))),
        REASON.VERSION_ID,
        "injected-version-id",
    ),
    (envelope(deployment(served("a:b"))), REASON.VERSION_ID, "colon-version-id"),
    (envelope(deployment(served("9" * 65))), REASON.VERSION_ID, "overlong-version-id"),
    (envelope(deployment(served(12345))), REASON.VERSION_ID, "numeric-version-id"),
    (
        envelope(deployment(served(f"ver\nB54_ENGINE_ACTIVE_VERSION_IDENTIFIED=PASS"))),
        REASON.VERSION_ID,
        "newline-injection-version-id",
    ),
]


@pytest.mark.parametrize(
    "payload,expected_reason",
    [pytest.param(p, r, id=i) for p, r, i in REJECTIONS],
)
def test_primitive_refuses_with_the_closed_reason_code(payload, expected_reason) -> None:
    with pytest.raises(primitive.ServedVersionResolutionError) as exc:
        primitive.resolve_served_version_id(payload)
    assert exc.value.reason == expected_reason


def test_reason_code_vocabulary_is_closed_and_fully_covered() -> None:
    # A reason code no test reaches is a code a consumer could silently fail to
    # translate, so coverage of the vocabulary is itself asserted.
    declared = {
        value
        for name, value in vars(REASON).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    assert declared
    covered = {reason for _, reason, _ in REJECTIONS}
    assert covered == declared


def test_reason_codes_are_stable_tokens_not_prose() -> None:
    # Callers translate codes into their own published wording, so a code must
    # never smuggle payload content or read like a message.
    for name, value in vars(REASON).items():
        if name.startswith("_") or not isinstance(value, str):
            continue
        assert value == value.strip().lower()
        assert " " not in value


# --- convergence: all four lanes now agree -------------------------------------

CONVERGENCE_REFUSALS: list[tuple[object, str]] = [
    ([], "raw-list"),
    (None, "none"),
    ({"success": False, "result": None}, "unsuccessful"),
    ({"success": True, "result": []}, "list-shaped-result"),
    (envelope(), "empty-deployments"),
    (envelope(deployment(served(ACTIVE), served(PREVIOUS))), "two-versions"),
    (envelope(deployment(served(ACTIVE, 50))), "partial-traffic"),
    (envelope(deployment({"id": ACTIVE, "percentage": 100})), "bare-id"),
    (envelope(deployment(served("   "))), "whitespace-id"),
    (envelope(deployment(served("ver A; rm -rf /"))), "injected-id"),
    (envelope(deployment(served("a:b"))), "colon-id"),
]


@pytest.mark.parametrize("lane", LANE_NAMES)
@pytest.mark.parametrize(
    "payload",
    [pytest.param(p, id=i) for p, i in CONVERGENCE_REFUSALS],
)
def test_every_lane_refuses_non_canonical_payload(lane: str, payload) -> None:
    resolve, error_type = LANES[lane]
    with pytest.raises(error_type):
        resolve(payload)


@pytest.mark.parametrize("lane", LANE_NAMES)
def test_every_lane_resolves_the_canonical_history_envelope_identically(lane: str) -> None:
    payload = envelope(
        deployment(served(ACTIVE)),
        deployment(served(PREVIOUS, 0)),
    )
    resolve, _ = LANES[lane]
    assert resolve(payload) == ACTIVE


@pytest.mark.parametrize("lane", LANE_NAMES)
def test_every_lane_publishes_a_non_empty_reason(lane: str) -> None:
    # A resolver that fails closed but says why is the operable contract; an
    # untranslated or empty reason would be indistinguishable from a bug.
    resolve, error_type = LANES[lane]
    with pytest.raises(error_type) as exc:
        resolve(envelope(deployment(served("a:b"))))
    assert str(exc.value).strip()


@pytest.mark.parametrize("lane", ["b54_engine_guard", "b62_secret_guard"])
def test_ambiguous_deployments_keep_the_ambiguous_vocabulary(lane: str) -> None:
    # Both deploy guards publish "ambiguous active deployment" for an
    # unresolvable active deployment; the gate source contract pins it.
    resolve, error_type = LANES[lane]
    with pytest.raises(error_type) as exc:
        resolve(envelope())
    assert "ambiguous active deployment" in str(exc.value)


# --- the one intentional behavior change ---------------------------------------

def test_b62_lane_now_refuses_an_unsafe_but_non_blank_version_id() -> None:
    # Before #2737 only the Engine lane charset-checked the id, so this payload
    # resolved in the B62 lane and its value was echoed into CI output. The
    # canonical contract is VERSION_ID = non-empty + safe charset.
    assert not primitive.is_safe_version_id("ver A; rm -rf /")
    with pytest.raises(b62_guard.ServedVersionGuardError):
        b62_guard.resolve_served_version_id(envelope(deployment(served("ver A; rm -rf /"))))


def test_b62_lane_still_publishes_its_gate_pinned_vocabulary() -> None:
    # b62-production-code-deploy-gate.yml asserts these phrases against the
    # guard's own source text, so the shared primitive must not absorb them.
    source = (SCRIPTS / "b62_served_version_secret_guard.py").read_text(encoding="utf-8")
    assert "ambiguous active deployment" in source
    assert "served version id is missing" in source


def test_lineage_and_marker_keep_their_stricter_uuid_precondition() -> None:
    # "ver-A" satisfies the canonical charset rule but not these lanes' own
    # exact-lowercase-UUID precondition; that stays a local layer.
    payload = envelope(deployment(served("ver-A")))
    assert primitive.resolve_served_version_id(payload) == "ver-A"
    with pytest.raises(lineage.LineageError):
        lineage.resolve_active_version(payload)
    with pytest.raises(marker.LiveContentError):
        marker.resolve_active_version(payload, "pre")


def test_primitive_performs_no_io_and_no_mutation() -> None:
    # The guards' safety boundary is a source contract, not only a runtime one.
    source = (SCRIPTS / "cloudflare_served_version.py").read_text(encoding="utf-8")
    for forbidden in ("urllib", "requests", "subprocess", "socket", "open(", "environ"):
        assert forbidden not in source, f"primitive must not touch {forbidden}"
