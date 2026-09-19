"""Network-free contract tests for the mutation-class evidence primitive (#2752).

Synthetic version ids only. No HTTP, no Cloudflare payloads, no credentials.

The three classes must not be interchangeable, so most of this file is about
the boundaries between them: a code deploy that never changes fails, a secret
PUT that never changes is admissible only past the stable-observation floor, and
a rollback passes only on equality with the named target.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/cloudflare_mutation_evidence.py"

A = "ver-pre"
B = "ver-post"
T = "ver-target"


def _load():
    spec = importlib.util.spec_from_file_location("cloudflare_mutation_evidence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load()


def ok(*ids: str):
    return [(True, value) for value in ids]


def reject(count: int = 1):
    return [(False, None)] * count


# --- closed vocabulary ---------------------------------------------------------

def test_classes_are_the_closed_three_and_obligations_are_declared() -> None:
    assert mod.MUTATION_CLASSES == (mod.CODE_DEPLOY, mod.SECRET_PUT, mod.ROLLBACK)
    assert mod.REQUIRES_CHANGE[mod.CODE_DEPLOY] is True
    assert mod.REQUIRES_CHANGE[mod.SECRET_PUT] is False
    # None, not False: rollback's obligation is equality with a target, which is
    # a different question from "did the version change".
    assert mod.REQUIRES_CHANGE[mod.ROLLBACK] is None


def test_issue_2453_provenance_constants_are_preserved() -> None:
    assert mod.POLL_ATTEMPTS == 30
    assert mod.MIN_SAME_VERSION_OBSERVATIONS == 15


@pytest.mark.parametrize(
    "mutation_class,pre_version,observations",
    [
        pytest.param(mod.ROLLBACK, A, ok(A), id="rollback-without-target"),
        pytest.param(mod.CODE_DEPLOY, "", ok(A), id="empty-pre-version"),
        pytest.param(mod.CODE_DEPLOY, None, ok(A), id="null-pre-version"),
        pytest.param("NOT_A_CLASS", A, ok(A), id="unknown-class"),
    ],
)
def test_malformed_questions_are_rejected_not_silently_passed(
    mutation_class, pre_version, observations
) -> None:
    with pytest.raises(mod.EvidenceInputError):
        mod.decide(mutation_class, pre_version, observations)


def test_rollback_refuses_to_infer_a_target() -> None:
    with pytest.raises(mod.EvidenceInputError) as exc:
        mod.decide(mod.ROLLBACK, A, ok(B), target_version_id="   ")
    assert "explicit target" in str(exc.value)


# --- CODE_DEPLOY ---------------------------------------------------------------

def test_code_deploy_passes_only_when_the_served_version_changed() -> None:
    verdict = mod.decide(mod.CODE_DEPLOY, A, ok(A, B))
    assert (verdict.verdict, verdict.final) == ("YES", True)
    assert verdict.post_version_id == B
    assert verdict.diverged_at == 2


def test_code_deploy_window_still_open_is_not_yet_a_failure() -> None:
    verdict = mod.decide(mod.CODE_DEPLOY, A, ok(A), window_open=True)
    assert (verdict.verdict, verdict.final) == ("FAIL", False)


def test_code_deploy_exhausted_window_without_change_fails_closed() -> None:
    verdict = mod.decide(mod.CODE_DEPLOY, A, ok(A, A, A))
    assert (verdict.verdict, verdict.final) == ("FAIL", True)
    assert verdict.same_observations == 3


def test_code_deploy_never_returns_no() -> None:
    # "NO" would mean "provably unchanged, and that is acceptable" -- a
    # contradiction for a class that requires change.
    for window in (True, False):
        assert mod.decide(mod.CODE_DEPLOY, A, ok(A), window_open=window).verdict != mod.NO


# --- SECRET_PUT ----------------------------------------------------------------

def test_secret_put_change_is_evidence_and_passes() -> None:
    verdict = mod.decide(mod.SECRET_PUT, A, ok(A, B))
    assert (verdict.verdict, verdict.final) == ("YES", True)
    assert verdict.diverged_at == 2


def test_secret_put_no_change_is_admissible_only_past_the_floor() -> None:
    # Below the floor the stable state is not established: with the window open
    # the caller keeps reading, and with it closed that is a FAIL, never a NO.
    below_open = mod.decide(mod.SECRET_PUT, A, ok(*[A] * 14), window_open=True)
    assert (below_open.verdict, below_open.final) == ("FAIL", False)
    below_closed = mod.decide(mod.SECRET_PUT, A, ok(*[A] * 14))
    assert (below_closed.verdict, below_closed.final) == ("FAIL", True)
    at_floor = mod.decide(mod.SECRET_PUT, A, ok(*[A] * 15))
    assert (at_floor.verdict, at_floor.final) == ("NO", True)
    assert at_floor.same_observations == 15


def test_secret_put_no_is_evidence_only_and_never_a_mutation_failure() -> None:
    # #2453: NO must not be readable as "the PUT failed".
    verdict = mod.decide(mod.SECRET_PUT, A, ok(*[A] * 20))
    assert verdict.verdict == mod.NO
    assert "evidence only" in verdict.reason
    assert "failed" not in verdict.reason.lower()


def test_divergence_wins_over_the_floor() -> None:
    # A single differing acceptable read finalizes YES even if most reads agreed.
    verdict = mod.decide(mod.SECRET_PUT, A, ok(*([A] * 5 + [B])))
    assert (verdict.verdict, verdict.diverged_at) == ("YES", 6)


# --- ROLLBACK ------------------------------------------------------------------

def test_rollback_passes_on_equality_with_the_named_target() -> None:
    verdict = mod.decide(mod.ROLLBACK, A, ok(A, B), target_version_id=B)
    assert (verdict.verdict, verdict.final) == ("YES", True)
    assert verdict.post_version_id == B


def test_rollback_ignores_that_the_version_changed_at_all() -> None:
    # Moving is not the rollback obligation; arriving is. A change to a version
    # that is not the target must not pass.
    verdict = mod.decide(mod.ROLLBACK, A, ok(A, "ver-wrong"), target_version_id=B)
    assert verdict.verdict == mod.FAIL
    assert verdict.final is True


def test_rollback_window_open_and_closed_differ() -> None:
    assert mod.decide(mod.ROLLBACK, A, ok(A), target_version_id=B, window_open=True).final is False
    assert mod.decide(mod.ROLLBACK, A, ok(A), target_version_id=B).final is True


# --- rejected reads ------------------------------------------------------------

def test_rejected_reads_never_finalize_in_either_direction() -> None:
    # #2453 provenance: a transport failure or a non-canonical payload is not
    # evidence, so it can produce neither YES nor a closed NO/FAIL.
    only_rejects = mod.decide(mod.ROLLBACK, A, reject(2), target_version_id=B, window_open=True)
    assert (only_rejects.verdict, only_rejects.final) == ("FAIL", False)
    assert only_rejects.post_version_id is None
    exhausted = mod.decide(mod.ROLLBACK, A, reject(2), target_version_id=B)
    assert (exhausted.verdict, exhausted.final) == ("FAIL", True)
    # A rejected read inside an otherwise-unchanged code-deploy window must not
    # be counted as a same-version observation either.
    mixed = mod.decide(mod.CODE_DEPLOY, A, ok(A) + reject(3), window_open=True)
    assert mixed.same_observations == 1


def test_rejected_read_between_agreement_and_target_still_converges() -> None:
    verdict = mod.decide(mod.ROLLBACK, A, ok(A) + reject(1) + ok(B), target_version_id=B)
    assert verdict.verdict == mod.YES


def test_acceptable_read_without_a_usable_id_cannot_satisfy_a_claim() -> None:
    for cls, kwargs in (
        (mod.CODE_DEPLOY, {}),
        (mod.SECRET_PUT, {}),
        (mod.ROLLBACK, {"target_version_id": B}),
    ):
        verdict = mod.decide(cls, A, [(True, "   "), (True, None)], **kwargs)
        assert (verdict.verdict, verdict.final) == ("FAIL", True), cls


def test_malformed_observation_shape_is_an_input_error() -> None:
    with pytest.raises(mod.EvidenceInputError):
        mod.decide(mod.CODE_DEPLOY, A, [("not-a-pair")])  # type: ignore[list-item]


# --- purity: this module decides, it never observes ----------------------------

def test_primitive_performs_no_io_and_no_envelope_parsing() -> None:
    # Asserted on the syntax tree rather than by substring: a naive text scan
    # also matches the module's own prose, which proves nothing either way.
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    # No network, no shell, no HTTP client library, and not even JSON: the
    # caller hands over already-resolved observations.
    assert imported <= {"__future__", "argparse", "sys", "pathlib", "typing"}, imported

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for forbidden in ("open", "exec", "eval", "compile", "system", "popen", "__import__"):
        assert forbidden not in called

    attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }
    for forbidden in ("urlopen", "request", "post", "Popen", "Connection"):
        assert forbidden not in attributes

    # The caller-provided observation file is the only thing it touches.
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.count("read_text") == 1


def test_primitive_never_names_a_cloudflare_envelope_field() -> None:
    # Quoted field literals, not prose: envelope shape stays owned by
    # cloudflare_served_version.py (#2740), so this module must not be able to
    # reach into a payload even accidentally.
    source = SCRIPT.read_text(encoding="utf-8")
    for field in ('"result"', '"deployments"', '"versions"', '"percentage"', '"version_id"'):
        assert field not in source, f"primitive must not read {field}"


def test_cli_reports_the_decision_and_bounded_exit_vocabulary() -> None:
    def run(lines: list[str], extra: list[str], window_open: bool) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.txt"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            argv = [
                "evaluate", "--class", *extra,
                "--pre-version", A, "--observations", str(path),
            ]
            if window_open:
                argv.append("--window-open")
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = mod.main(argv)
        return code, out.getvalue() + err.getvalue()

    code, out = run(["ok " + B], [mod.CODE_DEPLOY, ], True)
    assert code == 0
    assert "MUTATION_CLASS_VERDICT=YES" in out
    assert "HTTP_CALLS=0" in out
    assert "CLOUDFLARE_ENVELOPE_PARSING=0" in out
    assert "PRODUCTION_MUTATION=0" in out

    code, out = run(["ok " + A], [mod.CODE_DEPLOY], True)
    assert code == 3  # keep polling
    code, out = run(["ok " + A], [mod.CODE_DEPLOY], False)
    assert code == 1  # closed failure
    code, out = run(["ok " + A] * 15, [mod.SECRET_PUT], True)
    assert code == 0 and "MUTATION_CLASS_VERDICT=NO" in out
    code, out = run(["reject -"], [mod.ROLLBACK, ], True)
    assert code == 1  # rollback needs --target-version


def test_cli_output_is_bounded_key_value_evidence_only() -> None:
    # Every emitted line must be a bounded NAME=VALUE token. The primitive never
    # receives a Cloudflare payload at all, so there is nothing for it to leak;
    # this asserts the output shape that keeps it that way.
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "obs.txt"
        path.write_text(f"ok {B}\n", encoding="utf-8")
        with contextlib.redirect_stdout(out):
            code = mod.main([
                "evaluate", "--class", mod.CODE_DEPLOY, "--pre-version", A,
                "--observations", str(path),
            ])
    assert code == 0
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    assert lines
    for line in lines:
        assert "=" in line and " " not in line.split("=", 1)[0], line
    assert "MUTATION_EVIDENCE_REASON=code deploy converged: served version differs from pre-deploy" in lines
