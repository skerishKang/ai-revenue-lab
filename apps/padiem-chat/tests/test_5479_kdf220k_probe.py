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
    assert "webcrypto-iteration-cap" in script
    assert "B62_WORKER_KDF_BENCH=" in script
    assert "B62_WORKER_KDF_BENCH_VECTOR=PASS" in script
    assert "B62_WORKER_KDF_BENCH_IDENTITY=PASS" in script
