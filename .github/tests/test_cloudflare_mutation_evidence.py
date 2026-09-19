"""Network-free contract tests for the mutation-class evidence primitive (#2752).

Synthetic version ids only. No HTTP, no Cloudflare payloads, no credentials.

The three classes must not be interchangeable, so most of this file is about the
boundaries between them. The second half covers the #2752 review blockers: the
30-observation ceiling, canonical validation of every version id, closed reason
codes that can never reflect a hostile id, and the rejected-observation count.
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
HOSTILE = "ver A; rm -rf /"


def _load():
    spec = importlib.util.spec_from_file_location("cloudflare_mutation_evidence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load()


def ok(*ids: object):
    return [(True, value) for value in ids]


def reject(count: int = 1):
    return [(False, None)] * count


def run(argv: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue() + err.getvalue()


def evaluate(tmp: Path, lines: list[str], extra: list[str], window_open: bool) -> tuple[int, str]:
    path = tmp / "obs.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    argv = ["evaluate", "--class", *extra, "--pre-version", A, "--observations", str(path)]
    if window_open:
        argv.append("--window-open")
    return run(argv)


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


def test_canonical_window_ceiling_matches_the_polling_contract() -> None:
    # The ceiling must equal the gates' 30-attempt window, so no caller can end
    # up with a wider evidence window than the reads it is allowed to take.
    assert mod.MAX_OBSERVATIONS == 30 == mod.POLL_ATTEMPTS


def test_reason_codes_are_a_closed_bounded_vocabulary() -> None:
    assert len(set(mod.REASON_CODES)) == len(mod.REASON_CODES)
    for code in mod.REASON_CODES:
        assert code == code.strip().upper()
        assert " " not in code
        assert not any(char in code for char in (";", "\n", "'", '"'))


# --- blocker 1: the observation ceiling ---------------------------------------

def test_more_than_the_canonical_window_fails_closed() -> None:
    verdict = mod.decide(mod.CODE_DEPLOY, A, ok(*([A] * 31)))
    assert (verdict.verdict, verdict.final) == ("FAIL", True)
    assert verdict.reason == "OBSERVATION_LIMIT_EXCEEDED"


def test_ceiling_applies_even_when_it_would_otherwise_pass() -> None:
    # A divergent read is present, but over-window input is refused rather than
    # quietly classified: the bound is not advisory.
    verdict = mod.decide(mod.ROLLBACK, A, ok(*([A] * 30 + [T])), target_version_id=T)
    assert (verdict.verdict, verdict.reason) == ("FAIL", "OBSERVATION_LIMIT_EXCEEDED")


def test_exactly_the_canonical_window_is_accepted() -> None:
    verdict = mod.decide(mod.CODE_DEPLOY, A, ok(*([A] * 29 + [B])))
    assert verdict.verdict == mod.YES
    assert verdict.observations == 30


def test_ceiling_is_not_widenable_through_the_public_surface() -> None:
    # No parameter or flag may raise the ceiling.
    import inspect

    signature = inspect.signature(mod.decide)
    assert "max_observations" not in signature.parameters
    assert "observations" in signature.parameters
    code = SCRIPT.read_text(encoding="utf-8")
    assert "--max-observations" not in code
    # A floor above the ceiling is a contradiction and is refused.
    with pytest.raises(mod.EvidenceInputError):
        mod.decide(mod.SECRET_PUT, A, ok(A), min_same_observations=31)


# --- blocker 2: every version id meets the canonical safe-id contract ----------

@pytest.mark.parametrize("pre_version", ["", "   ", None, HOSTILE, "a:b", 12345, "9" * 65])
def test_unsafe_pre_version_is_rejected_not_classified(pre_version) -> None:
    with pytest.raises(mod.EvidenceInputError):
        mod.decide(mod.CODE_DEPLOY, pre_version, ok(A))


@pytest.mark.parametrize("target", ["", "   ", None, HOSTILE, "a:b"])
def test_unsafe_rollback_target_is_rejected_before_any_evidence(target) -> None:
    with pytest.raises(mod.EvidenceInputError):
        mod.decide(mod.ROLLBACK, A, ok(A), target_version_id=target)


def test_unsafe_id_in_an_accepted_observation_cannot_become_evidence() -> None:
    # A hostile id asserted as "acceptable" must not satisfy the equality claim,
    # even though it appears at the position that would otherwise pass.
    verdict = mod.decide(mod.ROLLBACK, A, ok(HOSTILE), target_version_id=T)
    assert (verdict.verdict, verdict.final) == ("FAIL", True)
    assert verdict.reason == "INVALID_VERSION_ID"
    assert verdict.post_version_id is None


def test_blank_id_in_an_accepted_observation_is_refused() -> None:
    for value in ("   ", None, ""):
        verdict = mod.decide(mod.CODE_DEPLOY, A, ok(value))
        assert (verdict.verdict, verdict.reason) == ("FAIL", "UNUSABLE_ACCEPTED_OBSERVATION_ID")


def test_safe_id_validation_is_reused_not_reimplemented() -> None:
    # #2752 blocker 2: the canonical contract from #2740 is imported, not
    # re-derived, so the resolver and this decision can never drift apart.
    import inspect

    source = inspect.getsource(mod)
    assert "from cloudflare_served_version import is_safe_version_id" in source
    assert "re.compile" not in source
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {
        "__future__", "argparse", "sys", "pathlib", "typing", "cloudflare_served_version",
    }, imported


def test_a_hostile_observed_id_is_not_misread_as_divergence() -> None:
    # Ordering matters: the unsafe id differs from pre, but it is refused rather
    # than counted as a code-deploy change.
    verdict = mod.decide(mod.CODE_DEPLOY, A, ok(A, HOSTILE))
    assert verdict.verdict == "FAIL"
    assert verdict.diverged_at is None


# --- blocker 3: no raw or unsafe id is ever echoed -----------------------------

def test_hostile_ids_never_reach_stdout_or_stderr() -> None:
    # Deterministic, bounded output is the point of the reason codes: a hostile
    # version id must not be reflected through a reason, a message, or a value.
    cases = [
        (mod.ROLLBACK, A, ok(HOSTILE), {"target_version_id": T}),
        (mod.CODE_DEPLOY, A, ok(A, HOSTILE), {}),
        (mod.SECRET_PUT, A, ok(HOSTILE), {}),
    ]
    for cls, pre, observations, kwargs in cases:
        verdict = mod.decide(cls, pre, observations, **kwargs)
        rendered = repr(verdict.as_kv())
        assert HOSTILE not in rendered, cls
        assert verdict.reason in mod.REASON_CODES, cls


def test_hostile_pre_and_target_never_reach_error_text() -> None:
    for bad in (HOSTILE, "a:b", "x\nINJECTED"):
        with pytest.raises(mod.EvidenceInputError) as exc:
            mod.decide(mod.ROLLBACK, A, ok(A), target_version_id=bad)
        assert bad not in str(exc.value)
    with pytest.raises(mod.EvidenceInputError) as exc:
        mod.decide(mod.CODE_DEPLOY, HOSTILE, ok(A))
    assert HOSTILE not in str(exc.value)


def test_post_version_id_is_only_ever_a_safe_id() -> None:
    verdict = mod.decide(mod.CODE_DEPLOY, A, ok(A, B))
    assert mod.is_safe_version_id(verdict.post_version_id)
    refused = mod.decide(mod.ROLLBACK, A, ok(HOSTILE), target_version_id=T)
    assert refused.post_version_id is None


def test_reason_is_a_code_and_carries_no_payload_material() -> None:
    verdicts = [
        mod.decide(mod.CODE_DEPLOY, A, ok(A, B)),
        mod.decide(mod.CODE_DEPLOY, A, ok(A)),
        mod.decide(mod.SECRET_PUT, A, ok(*[A] * 15)),
        mod.decide(mod.SECRET_PUT, A, ok(A, B)),
        mod.decide(mod.ROLLBACK, A, ok(T), target_version_id=T),
        mod.decide(mod.ROLLBACK, A, ok(B), target_version_id=T),
        mod.decide(mod.CODE_DEPLOY, A, reject(2)),
        mod.decide(mod.CODE_DEPLOY, A, ok(A) + reject(1) + ok(HOSTILE)),
    ]
    for verdict in verdicts:
        assert verdict.reason in mod.REASON_CODES, verdict.reason
        assert verdict.reason not in ("", A, B, T)


def test_cli_does_not_echo_a_hostile_observed_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        code, out = evaluate(
            Path(tmp), [f"ok {HOSTILE}"], [mod.CODE_DEPLOY], window_open=False
        )
    assert code == 1
    assert HOSTILE not in out
    assert "MUTATION_EVIDENCE_REASON=INVALID_VERSION_ID" in out


# --- blocker 4: rejected observations are counted, and never floor evidence ----

def test_rejected_observations_are_reported_as_a_bounded_field() -> None:
    verdict = mod.decide(mod.CODE_DEPLOY, A, ok(A) + reject(3) + ok(B))
    assert verdict.observations == 5
    assert verdict.rejected_observations == 3
    assert verdict.same_observations == 1
    assert verdict.as_kv()["MUTATION_EVIDENCE_REJECTED_OBSERVATIONS"] == "3"


def test_all_rejected_input_counts_every_read() -> None:
    verdict = mod.decide(mod.ROLLBACK, A, reject(4), target_version_id=T, window_open=True)
    assert (verdict.verdict, verdict.final) == ("FAIL", False)
    assert verdict.reason == "NO_ACCEPTABLE_OBSERVATION"
    assert verdict.observations == 4
    assert verdict.rejected_observations == 4
    assert verdict.same_observations == 0


def test_rejected_reads_do_not_count_toward_the_secret_put_floor() -> None:
    # 8 real same-version observations plus 20 rejects is NOT a stable state:
    # a flaky poll must not be able to manufacture a NO.
    below = mod.decide(mod.SECRET_PUT, A, ok(*[A] * 8) + reject(20))
    assert (below.verdict, below.reason) == ("FAIL", "BELOW_STABLE_OBSERVATION_FLOOR")
    assert below.same_observations == 8
    assert below.rejected_observations == 20
    at_floor = mod.decide(mod.SECRET_PUT, A, ok(*[A] * 15) + reject(1))
    assert at_floor.verdict == mod.NO
    assert at_floor.same_observations == 15


# --- CODE_DEPLOY ---------------------------------------------------------------

def test_code_deploy_passes_only_when_the_served_version_changed() -> None:
    verdict = mod.decide(mod.CODE_DEPLOY, A, ok(A, B))
    assert (verdict.verdict, verdict.final) == ("YES", True)
    assert verdict.post_version_id == B
    assert verdict.diverged_at == 2
    assert verdict.reason == "CODE_DEPLOY_DIVERGED"


def test_code_deploy_window_still_open_is_not_yet_a_failure() -> None:
    verdict = mod.decide(mod.CODE_DEPLOY, A, ok(A), window_open=True)
    assert (verdict.verdict, verdict.final) == ("FAIL", False)
    assert verdict.reason == "CODE_DEPLOY_DID_NOT_DIVERGE"


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
    assert (verdict.verdict, verdict.reason) == ("YES", "SECRET_PUT_DIVERGED")
    assert verdict.diverged_at == 2


def test_secret_put_no_change_is_admissible_only_past_the_floor() -> None:
    below_open = mod.decide(mod.SECRET_PUT, A, ok(*[A] * 14), window_open=True)
    assert (below_open.verdict, below_open.final) == ("FAIL", False)
    below_closed = mod.decide(mod.SECRET_PUT, A, ok(*[A] * 14))
    assert (below_closed.verdict, below_closed.final) == ("FAIL", True)
    at_floor = mod.decide(mod.SECRET_PUT, A, ok(*[A] * 15))
    assert (at_floor.verdict, at_floor.final) == ("NO", True)
    assert at_floor.reason == "SECRET_PUT_NO_DIVERGENCE_STABLE"


def test_secret_put_no_is_evidence_only_and_never_a_mutation_failure() -> None:
    # #2453: NO must not be readable as "the PUT failed". The verdict itself is
    # the carrier now, so the closed reason code must not imply failure either.
    verdict = mod.decide(mod.SECRET_PUT, A, ok(*[A] * 20))
    assert verdict.verdict == mod.NO
    assert "FAIL" not in verdict.verdict
    assert verdict.final is True
    assert verdict.reason == "SECRET_PUT_NO_DIVERGENCE_STABLE"


def test_divergence_wins_over_the_floor() -> None:
    verdict = mod.decide(mod.SECRET_PUT, A, ok(*([A] * 5 + [B])))
    assert (verdict.verdict, verdict.diverged_at) == ("YES", 6)


# --- ROLLBACK ------------------------------------------------------------------

def test_rollback_passes_on_equality_with_the_named_target() -> None:
    verdict = mod.decide(mod.ROLLBACK, A, ok(A, T), target_version_id=T)
    assert (verdict.verdict, verdict.final) == ("YES", True)
    assert verdict.reason == "ROLLBACK_TARGET_OBSERVED"
    assert verdict.post_version_id == T


def test_rollback_ignores_that_the_version_changed_at_all() -> None:
    # Moving is not the rollback obligation; arriving is.
    verdict = mod.decide(mod.ROLLBACK, A, ok(A, B), target_version_id=T)
    assert (verdict.verdict, verdict.reason) == ("FAIL", "ROLLBACK_TARGET_NOT_OBSERVED")
    assert verdict.final is True


def test_rollback_window_open_and_closed_differ() -> None:
    open_verdict = mod.decide(mod.ROLLBACK, A, ok(A), target_version_id=T, window_open=True)
    closed_verdict = mod.decide(mod.ROLLBACK, A, ok(A), target_version_id=T)
    assert (open_verdict.final, closed_verdict.final) == (False, True)
    assert open_verdict.reason == closed_verdict.reason


# --- rejected reads ------------------------------------------------------------

def test_rejected_reads_never_finalize_in_either_direction() -> None:
    only_rejects = mod.decide(mod.ROLLBACK, A, reject(2), target_version_id=T, window_open=True)
    assert (only_rejects.verdict, only_rejects.final) == ("FAIL", False)
    assert only_rejects.post_version_id is None
    exhausted = mod.decide(mod.ROLLBACK, A, reject(2), target_version_id=T)
    assert (exhausted.verdict, exhausted.final) == ("FAIL", True)


def test_rejected_read_between_agreement_and_target_still_converges() -> None:
    verdict = mod.decide(mod.ROLLBACK, A, ok(A) + reject(1) + ok(T), target_version_id=T)
    assert verdict.verdict == mod.YES


# --- determinism ---------------------------------------------------------------

def test_same_input_produces_identical_evidence() -> None:
    for cls, kwargs in (
        (mod.CODE_DEPLOY, {}),
        (mod.SECRET_PUT, {}),
        (mod.ROLLBACK, {"target_version_id": T}),
    ):
        first = mod.decide(cls, A, ok(A, A, B), **kwargs).as_kv()
        second = mod.decide(cls, A, ok(A, A, B), **kwargs).as_kv()
        assert first == second
    # and across every open/closed pairing
    for window in (True, False):
        assert (mod.decide(mod.SECRET_PUT, A, ok(*[A] * 15), window_open=window).as_kv()
                == mod.decide(mod.SECRET_PUT, A, ok(*[A] * 15), window_open=window).as_kv())


def test_malformed_questions_are_rejected_not_silently_passed() -> None:
    for args in (
        (mod.ROLLBACK, A, ok(A)),                    # rollback without a target
        (mod.CODE_DEPLOY, "", ok(A)),               # empty pre-version
        (mod.CODE_DEPLOY, None, ok(A)),
        ("NOT_A_CLASS", A, ok(A)),                  # unknown class
    ):
        with pytest.raises(mod.EvidenceInputError):
            mod.decide(*args)


def test_malformed_observation_shape_is_an_input_error() -> None:
    with pytest.raises(mod.EvidenceInputError):
        mod.decide(mod.CODE_DEPLOY, A, ["not-a-pair"])  # type: ignore[list-item]


# --- purity: this module decides, it never observes ----------------------------

def test_primitive_performs_no_io_and_no_envelope_parsing() -> None:
    # Asserted on the syntax tree rather than by substring: a naive text scan
    # also matches the module's own prose, which proves nothing either way.
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    for forbidden in ("open", "exec", "eval", "compile", "system", "popen", "__import__"):
        assert forbidden not in called

    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    for forbidden in ("urlopen", "request", "post", "Popen", "Connection"):
        assert forbidden not in attributes

    # The caller-provided observation file is the only thing it touches, and the
    # canonical resolver it borrows a predicate from is the only sibling import.
    assert SCRIPT.read_text(encoding="utf-8").count("read_text") == 1


def test_primitive_never_names_a_cloudflare_envelope_field() -> None:
    # Quoted field literals, not prose: envelope shape stays owned by
    # cloudflare_served_version.py (#2740).
    source = SCRIPT.read_text(encoding="utf-8")
    for field in ('"result"', '"deployments"', '"versions"', '"percentage"', '"version_id"'):
        assert field not in source, f"primitive must not read {field}"


def test_cli_reports_the_decision_and_bounded_exit_vocabulary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        code, out = evaluate(path, [f"ok {B}"], [mod.CODE_DEPLOY], window_open=True)
        assert code == 0
        assert "MUTATION_CLASS_VERDICT=YES" in out
        assert "MUTATION_EVIDENCE_REASON=CODE_DEPLOY_DIVERGED" in out
        assert "HTTP_CALLS=0" in out
        assert "CLOUDFLARE_ENVELOPE_PARSING=0" in out
        assert "PRODUCTION_MUTATION=0" in out

        assert evaluate(path, [f"ok {A}"], [mod.CODE_DEPLOY], True)[0] == 3  # keep polling
        assert evaluate(path, [f"ok {A}"], [mod.CODE_DEPLOY], False)[0] == 1  # closed failure
        code, out = evaluate(path, [f"ok {A}"] * 15, [mod.SECRET_PUT], True)
        assert code == 0 and "MUTATION_CLASS_VERDICT=NO" in out
        # rollback cannot be evaluated without a target
        assert evaluate(path, ["reject -"], [mod.ROLLBACK], True)[0] == 1
        # an over-window observation file is refused closed by the CLI too
        assert evaluate(path, [f"ok {A}"] * 31, [mod.CODE_DEPLOY], False)[0] == 1


def test_cli_output_is_bounded_key_value_evidence_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        code, out = evaluate(Path(tmp), [f"ok {B}"], [mod.CODE_DEPLOY], False)
    assert code == 0
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines
    for line in lines:
        assert "=" in line and " " not in line.split("=", 1)[0], line
    assert "MUTATION_EVIDENCE_REASON=CODE_DEPLOY_DIVERGED" in lines
    assert "MUTATION_EVIDENCE_REJECTED_OBSERVATIONS=0" in lines
