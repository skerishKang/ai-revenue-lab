"""#3652 contract tests for the frozen-source pin / checkout-byte attribute guard.

Seven proofs are pinned here:

1. the real repository passes, and the four current pins are the targets actually collected;
2. the resolver reproduces the repository-relative form of every anchor algebra the Engine canaries
   use, including the clip at the repository root;
3. a collected pin with no matching checkout rule is an offender, proven on a synthetic tree so the
   control stays enforced on every pull request instead of being a one-off manual run;
4. deleting an existing attribute line is detected through Git's own effective answer, exercised in
   a throwaway repository so the check cannot be satisfied by string comparison alone;
5. `text eol=lf` and the `-text`/`binary` family are accepted while `unspecified`, `eol=crlf` and
   `eol=native` are not;
6. an untracked target, a tracked blob containing CR and a malformed digest each fail;
7. an unprovable key expression raises instead of silently shrinking the collected set.

Nothing here edits a pin, a product source or the canaries' raw-byte semantics.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "frozen_source_checkout_byte_guard.py"
_spec = importlib.util.spec_from_file_location("frozen_source_checkout_byte_guard", SCRIPT)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = guard
_spec.loader.exec_module(guard)

ENGINE_TESTS = ROOT / "apps" / "padiem-ai-engine" / "tests"
VALID = "0" * 64
CANARY_TARGETS = sorted(
    [
        "packages/padiem-ai-core/padiem_ai_core/document_normalization.py",
        "packages/padiem-ai-core/padiem_ai_core/document_semantics.py",
        "packages/padiem-ai-core/tests/test_document_semantics.py",
        "packages/padiem-ai-core/tests/test_document_normalization.py",
    ]
)


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #


def _pin(relative_path: str, digest: str = VALID) -> guard.PinnedSource:
    return guard.PinnedSource(
        module="apps/padiem-ai-engine/tests/test_synth.py",
        key=f'CORE_PACKAGE / "{Path(relative_path).name}"',
        relative_path=relative_path,
        digest=digest,
    )


def _policy(**overrides) -> guard.CheckoutPolicy:
    base = {"tracked": True, "text": "set", "eol": "lf", "cr_in_blob": False}
    return guard.CheckoutPolicy(**{**base, **overrides})


def _static(policy: guard.CheckoutPolicy):
    return lambda _path: policy


def _synth_module(tmp_path: Path, body: str) -> Path:
    module = tmp_path / "apps" / "padiem-ai-engine" / "tests" / "test_synth.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(textwrap.dedent(body), encoding="utf-8")
    return module


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "guard",
            "GIT_AUTHOR_EMAIL": "guard@example.invalid",
            "GIT_COMMITTER_NAME": "guard",
            "GIT_COMMITTER_EMAIL": "guard@example.invalid",
        },
    )


# --------------------------------------------------------------------------- #
# 1. the repository as it stands
# --------------------------------------------------------------------------- #


def test_real_repository_has_no_offenders() -> None:
    pins = guard.collect_pins(ENGINE_TESTS, ROOT)
    assert guard.find_offenders(pins, lambda path: guard.git_policy(path, ROOT)) == []


def test_real_repository_collects_exactly_the_canary_targets() -> None:
    """The guard must find them itself; a hardcoded list would let a new pin go unnoticed."""

    assert sorted(pin.relative_path for pin in guard.collect_pins(ENGINE_TESTS, ROOT)) == (
        CANARY_TARGETS
    )


def test_cli_reports_clean_on_the_real_repository() -> None:
    assert guard.main(["--root", str(ROOT)]) == 0


# --------------------------------------------------------------------------- #
# 2. resolver
# --------------------------------------------------------------------------- #


def test_resolver_reproduces_anchor_and_key_algebra(tmp_path: Path) -> None:
    module = _synth_module(
        tmp_path,
        """
        from pathlib import Path

        APP_ROOT = Path(__file__).resolve().parents[1]
        REPO_ROOT = Path(__file__).resolve().parents[3]
        CORE_PACKAGE = REPO_ROOT / "packages" / "padiem-ai-core" / "padiem_ai_core"

        PINNED_SHA256 = {
            CORE_PACKAGE / "a.py": "0" * 64,
            REPO_ROOT / "apps" / "padiem-ai-engine" / "app" / "b.py": "0" * 64,
            APP_ROOT / "tests" / "c.py": "0" * 64,
            "packages/explicit/d.py": "0" * 64,
        }
        """,
    )

    assert {pin.relative_path for pin in guard.collect_module_pins(module, tmp_path)} == {
        "packages/padiem-ai-core/padiem_ai_core/a.py",
        "apps/padiem-ai-engine/app/b.py",
        "apps/padiem-ai-engine/tests/c.py",
        "packages/explicit/d.py",
    }


def test_parents_index_clips_at_the_repository_root() -> None:
    cases = {
        3: (),
        9: (),
        1: ("apps", "padiem-ai-engine"),
        0: ("apps", "padiem-ai-engine", "tests"),
    }
    parts = ("apps", "padiem-ai-engine", "tests", "t.py")
    for levels, expected in cases.items():
        assert guard._ascend(parts, levels) == expected, levels


def test_resolver_fails_loud_on_an_unprovable_key(tmp_path: Path) -> None:
    module = _synth_module(
        tmp_path,
        """
        from somewhere import CORE_PACKAGE

        PINNED_SHA256 = {CORE_PACKAGE / "a.py": "0" * 64}
        """,
    )
    with pytest.raises(guard.UnresolvablePinExpression):
        guard.collect_module_pins(module, tmp_path)


def test_resolver_refuses_an_ambiguous_bare_literal(tmp_path: Path) -> None:
    module = _synth_module(
        tmp_path,
        """
        PINNED_SHA256 = {"a.py": "0" * 64}
        """,
    )
    with pytest.raises(guard.UnresolvablePinExpression):
        guard.collect_module_pins(module, tmp_path)


def test_a_call_form_key_raises_rather_than_under_reporting(tmp_path: Path) -> None:
    module = _synth_module(
        tmp_path,
        """
        PINNED_SHA256 = {build_key(): "0" * 64}
        """,
    )
    with pytest.raises(guard.UnresolvablePinExpression):
        guard.collect_module_pins(module, tmp_path)


# --------------------------------------------------------------------------- #
# 5. policy acceptance matrix
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "policy",
    [_policy(text="set", eol="lf"), _policy(text="unset", eol="unspecified")],
    ids=["text_eol_lf", "binary_family"],
)
def test_autocrlf_proof_policies_are_accepted(policy: guard.CheckoutPolicy) -> None:
    assert guard.is_autocrlf_proof(policy)
    assert guard.find_offenders([_pin("packages/x/y.py")], _static(policy)) == []


@pytest.mark.parametrize(
    "policy",
    [
        _policy(text="unspecified", eol="unspecified"),
        _policy(text="set", eol="crlf"),
        _policy(text="set", eol="native"),
        _policy(text="set", eol="unspecified"),
    ],
    ids=["no_rule", "eol_crlf", "eol_native", "text_only"],
)
def test_conversion_capable_policies_are_offenders(policy: guard.CheckoutPolicy) -> None:
    assert not guard.is_autocrlf_proof(policy)
    offenders = guard.find_offenders([_pin("packages/x/y.py")], _static(policy))
    assert len(offenders) == 1 and "not autocrlf-proof" in offenders[0]


# --------------------------------------------------------------------------- #
# 3 and 4. the promised negative controls
# --------------------------------------------------------------------------- #


def test_new_pin_without_a_matching_rule_fails(tmp_path: Path) -> None:
    """Collection plus evaluation, end to end, without touching the real repository."""

    module = _synth_module(
        tmp_path,
        f"""
        from pathlib import Path

        REPO_ROOT = Path(__file__).resolve().parents[3]
        CORE_PACKAGE = REPO_ROOT / "packages" / "padiem-ai-core" / "padiem_ai_core"

        PINNED_SHA256 = {{
            CORE_PACKAGE / "covered.py": "{VALID}",
            CORE_PACKAGE / "uncovered.py": "{VALID}",
        }}
        """,
    )

    pins = guard.collect_module_pins(module, tmp_path)
    assert len(pins) == 2

    covered = "packages/padiem-ai-core/padiem_ai_core/covered.py"
    uncovered = "packages/padiem-ai-core/padiem_ai_core/uncovered.py"
    offenders = guard.find_offenders(
        pins,
        lambda path: _policy() if path == covered else _policy(text="unspecified", eol="unspecified"),
    )

    # Compare on the full path: "covered.py" is a substring of "uncovered.py".
    assert any(line.startswith(uncovered) for line in offenders)
    assert not any(line.startswith(covered) for line in offenders)


def test_deleting_an_existing_attribute_line_is_detected_by_git(tmp_path: Path) -> None:
    """Real Git resolution, so an inherited rule or a rename cannot slip past a string check."""

    relative = "packages/core/module.py"
    file = tmp_path / relative
    file.parent.mkdir(parents=True)
    file.write_text("VALUE = 1\n", encoding="utf-8")
    attributes = tmp_path / ".gitattributes"

    _git(tmp_path, "init", "-q")
    attributes.write_text(f"{relative} text eol=lf\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "with rule")

    with_rule = guard.git_policy(relative, tmp_path)
    assert (with_rule.text, with_rule.eol) == ("set", "lf")
    assert guard.find_offenders([_pin(relative)], lambda p: guard.git_policy(p, tmp_path)) == []

    # Drop the rule the way a careless edit would, and commit that state.
    attributes.write_text("", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "--amend", "-m", "rule removed")

    without_rule = guard.git_policy(relative, tmp_path)
    assert not guard.is_autocrlf_proof(without_rule)
    offenders = guard.find_offenders([_pin(relative)], lambda p: guard.git_policy(p, tmp_path))
    assert len(offenders) == 1 and "not autocrlf-proof" in offenders[0]


def test_deleting_the_rule_is_also_caught_through_the_cli(tmp_path: Path) -> None:
    """The workflow step runs the script, so the exit code must flip too."""

    relative = "packages/core/module.py"
    file = tmp_path / relative
    file.parent.mkdir(parents=True)
    file.write_text("VALUE = 1\n", encoding="utf-8")
    engine_tests = tmp_path / "apps/padiem-ai-engine/tests"
    engine_tests.mkdir(parents=True)
    (engine_tests / "test_synth.py").write_text(
        textwrap.dedent(
            f"""
            from pathlib import Path

            REPO_ROOT = Path(__file__).resolve().parents[3]
            CORE = REPO_ROOT / "packages" / "core"

            PINNED_SHA256 = {{CORE / "module.py": "{VALID}"}}
            """
        ),
        encoding="utf-8",
    )

    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitattributes").write_text("", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "no rule")

    assert guard.main(["--root", str(tmp_path)]) == 1

    (tmp_path / ".gitattributes").write_text(f"{relative} text eol=lf\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "rule added")

    assert guard.main(["--root", str(tmp_path)]) == 0


def test_cli_labels_only_the_offending_path(tmp_path: Path, capsys) -> None:
    """`covered.py` is a substring of `uncovered.py`; the report must not smear the verdict.

    Regression control for the label pass in `main()`, which is why it compares on `startswith`.
    """

    core = tmp_path / "packages" / "core"
    core.mkdir(parents=True)
    (core / "covered.py").write_text("VALUE = 1\n", encoding="utf-8")
    (core / "uncovered.py").write_text("VALUE = 1\n", encoding="utf-8")

    engine_tests = tmp_path / "apps" / "padiem-ai-engine" / "tests"
    engine_tests.mkdir(parents=True)
    (engine_tests / "test_synth.py").write_text(
        textwrap.dedent(
            f"""
            from pathlib import Path

            REPO_ROOT = Path(__file__).resolve().parents[3]
            CORE = REPO_ROOT / "packages" / "core"

            PINNED_SHA256 = {{
                CORE / "covered.py": "{VALID}",
                CORE / "uncovered.py": "{VALID}",
            }}
            """
        ),
        encoding="utf-8",
    )

    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitattributes").write_text(
        "packages/core/covered.py text eol=lf\n", encoding="utf-8"
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "one rule")

    assert guard.main(["--root", str(tmp_path)]) == 1
    report = capsys.readouterr().out
    assert "OK        packages/core/covered.py" in report
    assert "OFFENDER  packages/core/uncovered.py" in report
    assert "OFFENDER  packages/core/covered.py" not in report


# --------------------------------------------------------------------------- #
# 6. remaining failure modes
# --------------------------------------------------------------------------- #


def test_untracked_target_is_an_offender() -> None:
    offenders = guard.find_offenders([_pin("packages/x/y.py")], _static(_policy(tracked=False)))
    assert offenders and "not tracked" in offenders[0]


def test_tracked_blob_containing_cr_is_an_offender() -> None:
    """The blind spot #3648 rejected LF-normalizing for: no checkout rule fixes a CRLF blob."""

    offenders = guard.find_offenders([_pin("packages/x/y.py")], _static(_policy(cr_in_blob=True)))
    assert offenders and "contains CR" in offenders[0]


def test_malformed_pin_digest_is_an_offender() -> None:
    offenders = guard.find_offenders(
        [_pin("packages/x/y.py", digest="not-a-digest")], _static(_policy())
    )
    assert offenders and "not 64-hex" in offenders[0]


def test_a_computed_digest_is_not_treated_as_a_pin(tmp_path: Path) -> None:
    """A value the guard cannot read literally must not count as a verified pin.

    Found while building the synthetic fixtures: `"0" * 64` parses as a BinOp, so collection records
    an empty digest and the offender path takes it. Pinned so that behaviour stays deliberate.
    """

    module = _synth_module(
        tmp_path,
        """
        PINNED_SHA256 = {"packages/x/y.py": "0" * 64}
        """,
    )

    pins = guard.collect_module_pins(module, tmp_path)
    assert [pin.digest for pin in pins] == [""]
    offenders = guard.find_offenders(pins, _static(_policy()))
    assert offenders and "not 64-hex" in offenders[0]
