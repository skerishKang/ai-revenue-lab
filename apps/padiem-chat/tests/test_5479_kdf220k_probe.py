"""#5479 follow-up: the 220,000-iteration KDF evidence cases.

The runtime probe must carry the REAL production KDF contract (the stored
``pbkdf2_sha512$220000$`` format through the async dispatch) and the
stdlib-primitive fallback with its real CPU cost, so a runtime migration is
judged on measured evidence instead of a low-iteration proxy.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

_PROBE_PATH = Path(__file__).resolve().parents[1] / "worker_runtime_combined_probe.py"
_LANE_PATH = (
    Path(__file__).resolve().parents[3] / ".github/scripts/b62_worker_probe_shared_runtime.sh"
)


def _probe_module():
    """Load only the pure-KDF pieces of the probe: the module top level imports
    the Workers SDK, which only exists inside the workerd runtime."""
    source = _PROBE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            "_pbkdf2_sha512_pure",
            "_password_kdf_state",
            "_password_kdf_async_state",
            "_timezone_database_state",
        }:
            keep.append(node)
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_PURE_VECTORS" for t in node.targets
        ):
            keep.append(node)
    module = ast.Module(body=keep, type_ignores=[])
    namespace: dict = {"hashlib": hashlib}
    exec(compile(module, str(_PROBE_PATH), "exec"), namespace)
    return namespace


def test_the_pure_fallback_matches_the_c_pbkdf2_at_220k():
    """Byte-identity with the C implementation at the production cost."""
    pure = _probe_module()["_pbkdf2_sha512_pure"](b"password", b"salt", 220000, 64)
    c_ref = hashlib.pbkdf2_hmac("sha512", b"password", b"salt", 220000, 64)
    assert pure == c_ref


def test_the_pure_fallback_matches_the_pinned_external_vectors():
    """Correctness independent of the local C path (fixed external vectors)."""
    probe = _probe_module()
    for iterations, expected in probe["_PURE_VECTORS"].items():
        got = probe["_pbkdf2_sha512_pure"](b"password", b"salt", iterations, 64).hex()
        assert got == expected, f"iteration count {iterations}"


def test_the_probe_source_carries_the_220k_cases():
    """The probe exposes the real-algorithm case and the benchmark case."""
    source = _PROBE_PATH.read_text(encoding="utf-8")
    assert "webcrypto-iteration-cap" in source
    assert "_kdf220k_state" in source
    assert "_kdfbench_state" in source
    assert "PBKDF2_ITERATIONS" in source
    assert "cryptography" in source


def test_the_lane_asserts_the_220k_contract():
    """The CI lane must prove the real-algorithm round trip and the bench."""
    script = _LANE_PATH.read_text(encoding="utf-8")
    assert "B62_WORKER_KDF220K=" in script
    assert "UNVERIFIED_PY314" in script
    assert "PASS_WEB314_ITERATION_CAP" not in script
    assert "runtime_minor" in script
    assert "B62_WORKER_KDF_BENCH=" in script
    assert "B62_WORKER_KDF_BENCH_VECTOR=PASS" in script
    assert "B62_WORKER_KDF_BENCH_IDENTITY=PASS" in script


def test_h1_py314_local_ok_is_never_an_edge_pass():
    """Local 3.14 must never be labelled as certifying the Production edge.

    #5743's rule is preserved exactly: a 3.14 result carries
    ``UNVERIFIED_PY314`` and is never reported as the 3.13 pass. What the lane
    does not do is stop on it — the manifest's runtime is a deploy decision,
    and a lane that can only pass on 3.13 would red every 3.14 build without
    producing edge evidence. Real refusals (the WebCrypto cap) still fail.
    """
    import json
    import shutil
    import subprocess
    import sys

    # Native Windows Git Bash can inherit a non-UTF8 console encoding;
    # the CI lane under test executes on Linux.
    if sys.platform == "win32":
        import pytest
        pytest.skip("shell decision matrix runs on Linux CI")
    if not shutil.which("bash"):
        import pytest
        pytest.skip("bash required for shell contract")

    source = _LANE_PATH.read_text(encoding="utf-8")
    shell_gate = source.split("# H1 (#5743)", 1)[1].split(
        "# #5479: the 220,000-iteration alternatives", 1
    )[0]
    # The fragment contains shell ``${...}`` expansions, so it is concatenated
    # rather than ``str.format()``-ed: formatting it raised KeyError once the
    # provider gate added ``${EXPECTED_KDF_PROVIDER}`` to this region.
    prelude = "B62_WORKER_PASSWORD_KDF_C_PATH='missing'\n"
    matrix = [
        (13, "ok", 0, "B62_WORKER_KDF220K_STATE=PASS_PY313_LOCAL"),
        (14, "ok", 0, "B62_WORKER_KDF220K_EDGE_COMPAT=UNVERIFIED_PY314"),
        (14, "ok", 0, "B62_WORKER_KDF220K_STATE=PASS_PY314_LOCAL_KDF_ONLY"),
        (14, "webcrypto-iteration-cap", 1, "B62_WORKER_KDF220K_STATE=FAIL"),
        (13, "webcrypto-iteration-cap", 1, "B62_WORKER_KDF220K_STATE=FAIL"),
    ]
    for minor, state, expected_code, marker in matrix:
        body = json.dumps(
            {"state": state, "runtime_minor": minor, "provider": "cryptography"}
        )
        script = (
            prelude + "KDF220K_BODY='" + body + "'\n" + "# H1 (#5743)" + shell_gate
        )
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True
        )
        output = result.stdout + result.stderr
        assert result.returncode == expected_code, (minor, state, output)
        assert marker in output, (minor, state, output)
        if minor == 14:
            # The forbidden shape: a local 3.14 run reported as the 3.13 pass.
            assert "PASS_PY313_LOCAL" not in output, (minor, state, output)
        else:
            assert "UNVERIFIED_PY314" not in output, (minor, state, output)
