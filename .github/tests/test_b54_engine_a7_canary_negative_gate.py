"""Provider-free negative gates for the A7 authenticated USER canary (#3298).

The existing ``test_b54_engine_a7_authenticated_canary.py`` asserts the canary's
*source text* and the CP-minted ``sub_`` subject regex. Nothing executed the
canary's own fail-closed branches, so a regression that let the probe proceed on
a missing/unsafe explicit model id, a missing or malformed protected subject, or
that echoed either value, would have shipped silently.

This module runs the real script as a subprocess with a deliberately
unreachable ``ENGINE_BASE_URL``. That makes the assertions decisive and
network-free:

* a genuine fail-closed verdict is produced *before* any request, so the run
  ends with the exact gate code and no transport failure;
* if a gate ever regressed, the run would instead reach the network and report
  a transport failure (or a PASS), failing the test.

Per #3523 the run's model is an **explicit Owner-selected input**: there is no
canonical primary, no default and no fallback. Every value here is synthetic;
no credentials, no provider call, no Production contact.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a7_authenticated_user_production_canary.py"

# Unreachable on purpose: if the canary reaches the network at all, the run
# fails differently and the assertions below go red.
UNREACHABLE_ENGINE = "http://127.0.0.1:1"

SYNTHETIC_CALLER_ID = "synthetic-a7-caller"
SYNTHETIC_CALLER_SECRET = "synthetic-a7-credential-never-real"
SYNTHETIC_SUBJECT = "sub_" + "0123456789abcdef" * 2
# Two distinct valid registered-model id shapes.
MODEL_SHAPE_A = "synthetic-a7-model"
MODEL_SHAPE_B = "vendor/family-2.1:2026-10"

TRANSPORT_FAILURE_MARKER = "A7 authenticated canary transport failed"


def _run_canary(*, model_id: str | None = MODEL_SHAPE_A,
                subject: str | None = SYNTHETIC_SUBJECT,
                caller_id: str | None = SYNTHETIC_CALLER_ID,
                caller_secret: str | None = SYNTHETIC_CALLER_SECRET):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "ENGINE_BASE_URL": UNREACHABLE_ENGINE,
        "GITHUB_RUN_ID": "synthetic-3298",
    }
    if caller_id is not None:
        env["CALLER_ID"] = caller_id
    if caller_secret is not None:
        env["CALLER_SECRET"] = caller_secret
    if subject is not None:
        env["PADIEM_A7_CANARY_SUBJECT_ID"] = subject
    if model_id is not None:
        env["A7_CANARY_MODEL_ID"] = model_id
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        env=env,
    )


def _combined(result) -> str:
    return result.stdout + result.stderr


def _canary_module():
    spec = importlib.util.spec_from_file_location("a7_canary_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# ── 1. explicit model id is required ────────────────────────────────────

@pytest.mark.parametrize("model_id", [None, ""])
def test_missing_explicit_model_id_skips_before_any_request(model_id) -> None:
    result = _run_canary(model_id=model_id)
    assert result.returncode == 2
    assert "A7_AUTHENTICATED_USER_CANARY=SKIPPED_MISSING_EXPLICIT_MODEL_ID" in result.stderr
    assert "A7_AUTHENTICATED_USER_CANARY=PASS" not in _combined(result)
    assert TRANSPORT_FAILURE_MARKER not in _combined(result)


@pytest.mark.parametrize(
    "bad_model",
    [
        " leading-space",
        "trailing-space ",
        "embedded space",
        "with\tTab",
        "with\nNewline",
        "-leading-hyphen",
        ".leading-dot",
        "x" * 129,               # over the bounded length
        "model,other",           # comma could smuggle a fallback list
        "model|other",
        "model;other",
    ],
)
def test_invalid_explicit_model_id_fails_closed_before_any_request(bad_model) -> None:
    result = _run_canary(model_id=bad_model)
    assert result.returncode == 1
    assert "A7_AUTHENTICATED_USER_CANARY=FAIL_INVALID_EXPLICIT_MODEL_ID" in result.stderr
    assert "A7_AUTHENTICATED_USER_CANARY=PASS" not in _combined(result)
    # no health and no orchestrate request is attempted
    assert TRANSPORT_FAILURE_MARKER not in _combined(result)


@pytest.mark.parametrize("good_model", [MODEL_SHAPE_A, MODEL_SHAPE_B])
def test_two_valid_model_shapes_both_pass_the_gate(good_model) -> None:
    """Distinct valid shapes are accepted; the gate is shape-based, not fixed."""
    result = _run_canary(model_id=good_model)
    combined = _combined(result)
    assert "SKIPPED_MISSING_EXPLICIT_MODEL_ID" not in combined
    assert "FAIL_INVALID_EXPLICIT_MODEL_ID" not in combined
    # it moved past the configuration gates and therefore reached the network
    assert TRANSPORT_FAILURE_MARKER in combined or result.returncode != 2


# ── 2. the exact chosen id is the one sent ──────────────────────────────

@pytest.mark.parametrize("chosen", [MODEL_SHAPE_A, MODEL_SHAPE_B])
def test_payload_carries_exactly_the_chosen_model_with_no_fallback(chosen) -> None:
    module = _canary_module()
    payload = module._payload(SYNTHETIC_SUBJECT, chosen)
    policy = payload["agent"]["model_policy"]
    assert policy == {"model": chosen}
    assert payload["subject_id"] == SYNTHETIC_SUBJECT
    # exactly one model, no fallback list and no secondary
    assert "fallback" not in repr(payload).lower()
    assert "models" not in policy
    assert payload["max_retries"] == 0


def test_payload_builder_requires_both_values() -> None:
    module = _canary_module()
    with pytest.raises(TypeError):
        module._payload(SYNTHETIC_SUBJECT)          # model missing
    with pytest.raises(TypeError):
        module._payload(model_id=MODEL_SHAPE_A)     # subject missing


# ── 3. protected subject gates ──────────────────────────────────────────

@pytest.mark.parametrize(
    "kwargs",
    [
        {"subject": None},
        {"subject": ""},
        {"subject": SYNTHETIC_SUBJECT, "caller_secret": None},
        {"subject": SYNTHETIC_SUBJECT, "caller_id": None},
    ],
)
def test_absent_protected_input_skips_before_any_request(kwargs) -> None:
    result = _run_canary(**kwargs)
    assert result.returncode == 2
    assert "A7_AUTHENTICATED_USER_CANARY=SKIPPED_MISSING_PROTECTED_INPUT" in result.stderr
    assert "A7_AUTHENTICATED_USER_CANARY=PASS" not in _combined(result)
    assert TRANSPORT_FAILURE_MARKER not in _combined(result)


@pytest.mark.parametrize(
    "bad_subject",
    [
        "usr_" + "0123456789abcdef" * 2,   # product-local id, not a CP subject
        "sub_" + "a" * 31,                  # truncated CP reference
        "sub_" + "g" * 32,                  # not hexadecimal
        "sub_" + "A" * 32,                  # CP mint is lowercase
        SYNTHETIC_SUBJECT + " ",            # untrusted suffix
        SYNTHETIC_SUBJECT + "\\n",          # newline bypass attempt
        "someone@example.com",              # provider identity is not a subject
        "sub_0123456789abcdef",             # too short
        " " + SYNTHETIC_SUBJECT,            # leading space
    ],
)
def test_malformed_subject_fails_closed_before_any_request(bad_subject) -> None:
    result = _run_canary(subject=bad_subject)
    assert result.returncode == 1
    assert "A7_AUTHENTICATED_USER_CANARY=FAIL_INVALID_SUBJECT_REFERENCE" in result.stderr
    assert "A7_AUTHENTICATED_USER_CANARY=PASS" not in _combined(result)
    assert TRANSPORT_FAILURE_MARKER not in _combined(result)


# ── 4. false match: shape-valid but not server-validated ────────────────

def test_regex_valid_synthetic_inputs_are_never_a_local_pass() -> None:
    """Shape-valid inputs must still be validated by the server."""
    result = _run_canary()
    assert result.returncode != 0
    combined = _combined(result)
    assert "A7_AUTHENTICATED_USER_CANARY=PASS" not in combined
    assert "CANONICAL_IDENTITY_REVALIDATION=PASS" not in combined
    assert "EXECUTION_COMPLETED=PASS" not in combined


# ── 5. no secret material may ever be emitted ───────────────────────────

@pytest.mark.parametrize(
    "subject",
    [None, SYNTHETIC_SUBJECT, "sub_" + "a" * 31, "someone@example.com"],
)
def test_subject_and_caller_secret_are_never_echoed(subject) -> None:
    result = _run_canary(subject=subject)
    combined = _combined(result)
    assert SYNTHETIC_CALLER_SECRET not in combined
    if subject:
        assert subject not in combined


def test_source_never_prints_the_subject_or_the_model() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "print(CANARY_SUBJECT_ID" not in source
    assert 'print(f"{CANARY_SUBJECT_ID}' not in source
    assert "print(CANARY_MODEL_ID" not in source
    assert 'print(f"{CANARY_MODEL_ID}' not in source
    # the subject only ever travels inside the request payload
    assert source.count("_payload(CANARY_SUBJECT_ID, CANARY_MODEL_ID)") == 1
