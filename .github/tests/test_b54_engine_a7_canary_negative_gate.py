"""Provider-free negative gates for the A7 authenticated USER canary (#3298).

The existing ``test_b54_engine_a7_authenticated_canary.py`` asserts the canary's
*source text* and the CP-minted ``sub_`` subject regex. Nothing executed the
canary's own fail-closed branches, so a regression that let the probe proceed on
a missing or malformed protected subject — or that echoed the subject — would
have shipped silently.

Two independent gate families are covered, both network-free:

1. the model-primary HOLD gate. ``padiem_ai_core.model_primary`` currently
   declares ``TEXT_PRIMARY_MODEL_ID = None`` (#3568 successor pending), so the
   canary must stop at ``BLOCKED_NO_PRIMARY_MODEL`` before any request. This test
   pins that behaviour so the hold cannot silently become a dispatch.
2. the protected-subject gate. A synthetic model-primary shim is injected on
   ``PYTHONPATH`` so the subject branches are reachable, then absent / malformed
   / shape-valid-but-unvalidated subjects are exercised.

Both families point ``ENGINE_BASE_URL`` at a deliberately unreachable address.
That makes the assertions decisive: a genuine fail-closed verdict is produced
*before* any request, so the run ends with the exact gate code; if a gate ever
regressed, the run would instead reach the network and fail differently.

No credentials, no provider call, no Production contact. All values synthetic.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a7_authenticated_user_production_canary.py"
CORE_PACKAGE = ROOT / "packages" / "padiem-ai-core"

# Unreachable on purpose: if the canary reaches the network at all, the run
# fails differently and the assertions below go red.
UNREACHABLE_ENGINE = "http://127.0.0.1:1"

SYNTHETIC_CALLER_ID = "synthetic-a7-caller"
SYNTHETIC_CALLER_SECRET = "synthetic-a7-credential-never-real"
SYNTHETIC_SUBJECT = "sub_" + "0123456789abcdef" * 2
SYNTHETIC_MODEL_ID = "synthetic-a7-model"

TRANSPORT_FAILURE_MARKER = "A7 authenticated canary transport failed"


def _shim_path() -> Path:
    """A throwaway ``padiem_ai_core`` that declares a synthetic primary model.

    Injected only so the subject gate is reachable while the real package is on
    HOLD. It shadows the real package purely by ``PYTHONPATH`` order.
    """
    temp = Path(tempfile.mkdtemp(prefix="a7-model-shim-"))
    package = temp / "padiem_ai_core"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "model_primary.py").write_text(
        f'TEXT_PRIMARY_MODEL_ID = "{SYNTHETIC_MODEL_ID}"\n', encoding="utf-8"
    )
    return temp


def _run_canary(*, subject: str | None, caller_id: str | None = SYNTHETIC_CALLER_ID,
                caller_secret: str | None = SYNTHETIC_CALLER_SECRET,
                shim: bool = False):
    python_path = [str(CORE_PACKAGE)]
    if shim:
        python_path.insert(0, str(_shim_path()))
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        python_path.append(existing)

    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "ENGINE_BASE_URL": UNREACHABLE_ENGINE,
        "GITHUB_RUN_ID": "synthetic-3298",
        "PYTHONPATH": os.pathsep.join(python_path),
    }
    if caller_id is not None:
        env["CALLER_ID"] = caller_id
    if caller_secret is not None:
        env["CALLER_SECRET"] = caller_secret
    if subject is not None:
        env["PADIEM_A7_CANARY_SUBJECT_ID"] = subject
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


# ── 1. model-primary HOLD gate ──────────────────────────────────────────

def test_model_primary_hold_blocks_before_any_request() -> None:
    """#3568 leaves TEXT_PRIMARY_MODEL_ID unset; the canary must hold, not dispatch.

    Judged from the probe's own output rather than an in-process import, so the
    assertion holds under any interpreter that can run the script.
    """
    result = _run_canary(subject=SYNTHETIC_SUBJECT)
    combined = _combined(result)
    if "ModuleNotFoundError" in combined:
        pytest.skip("real padiem_ai_core dependencies unavailable in this interpreter")
    if "BLOCKED_NO_PRIMARY_MODEL" not in combined:
        pytest.skip("a successor primary model is selected; HOLD gate not applicable")
    assert result.returncode == 2
    assert "A7_AUTHENTICATED_USER_CANARY=PASS" not in combined
    assert TRANSPORT_FAILURE_MARKER not in combined


# ── 2. absent protected input ───────────────────────────────────────────

@pytest.mark.parametrize(
    "kwargs",
    [
        {"subject": None},                                       # subject secret absent
        {"subject": ""},                                         # subject secret empty
        {"subject": SYNTHETIC_SUBJECT, "caller_secret": None},    # caller credential absent
        {"subject": SYNTHETIC_SUBJECT, "caller_id": None},        # caller id absent
    ],
)
def test_absent_protected_input_skips_before_any_request(kwargs) -> None:
    result = _run_canary(shim=True, **kwargs)
    assert result.returncode == 2
    assert "A7_AUTHENTICATED_USER_CANARY=SKIPPED_MISSING_PROTECTED_INPUT" in result.stderr
    assert "A7_AUTHENTICATED_USER_CANARY=PASS" not in _combined(result)
    # fail-closed happens before dispatch, so the network is never touched
    assert TRANSPORT_FAILURE_MARKER not in _combined(result)


# ── 3. malformed subject reference ──────────────────────────────────────

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
    result = _run_canary(subject=bad_subject, shim=True)
    assert result.returncode == 1
    assert "A7_AUTHENTICATED_USER_CANARY=FAIL_INVALID_SUBJECT_REFERENCE" in result.stderr
    assert "A7_AUTHENTICATED_USER_CANARY=PASS" not in _combined(result)
    assert TRANSPORT_FAILURE_MARKER not in _combined(result)


# ── 4. false match: shape-valid but not server-validated ────────────────

def test_regex_valid_synthetic_subject_is_never_a_local_pass() -> None:
    """A shape-valid subject must still be validated by the server.

    With an unreachable Engine the probe cannot obtain a server verdict, so it
    must not report PASS, and it must not fall back to trusting the local shape.
    """
    result = _run_canary(subject=SYNTHETIC_SUBJECT, shim=True)
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
    result = _run_canary(subject=subject, shim=True)
    combined = _combined(result)
    assert SYNTHETIC_CALLER_SECRET not in combined
    if subject:
        assert subject not in combined


def test_canary_source_never_prints_the_subject() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "print(CANARY_SUBJECT_ID" not in source
    assert 'print(f"{CANARY_SUBJECT_ID}' not in source
    # the subject only ever travels inside the request payload
    assert source.count("_payload(CANARY_SUBJECT_ID)") == 1
