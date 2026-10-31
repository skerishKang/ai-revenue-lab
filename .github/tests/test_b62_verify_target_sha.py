"""Contract tests for the one `target_sha` rule every B62 deploy gate applies.

  ONE_RULE_ONE_SCRIPT        = YES
  GUARD_RUNS_BEFORE_CHECKOUT = YES
  UPPERCASE_IS_NORMALIZED    = YES
  SHORT_OR_NON_HEX_OR_EMPTY  = FAIL
  NO_JOB_READS_THE_RAW_INPUT = YES
  EVERY_GATE_EMBEDS_THE_COPY = YES

Everything here is offline: the rule runs as a subprocess against the same two
files GitHub Actions hands it (`GITHUB_OUTPUT`, `GITHUB_ENV`), and the workflow
YAML is only read and parsed. No gate is dispatched and no Cloudflare resource
is touched.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

# .github/tests/<this file> -> repository root is two levels up.
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_verify_target_sha.py"
WORKFLOWS = ROOT / ".github/workflows"

spec = importlib.util.spec_from_file_location("b62_verify_target_sha", SCRIPT)
rule = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rule)

GUARD_ID = "b62_target_sha"
GUARD_STEP_NAME = "Verify target_sha shape before any checkout"
HEREDOC = "B62_TARGET_SHA_GUARD"
VALID = "0123456789abcdefabcd" + "0123456789abcdefabcd"

# The two gates the directive names; the sweep has to cover them.
NAMED_GATES = ("b62-d1-migrate-gate.yml", "b62-production-code-deploy-gate.yml")


class _StrictLoader(yaml.SafeLoader):
    """A mapping key written twice is a silent last-one-wins in PyYAML."""


def _reject_duplicate_keys(loader, node, deep=False):
    built = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in built:
            raise AssertionError(
                f"duplicate key {key!r} at line {key_node.start_mark.line + 1}"
            )
        built[key] = loader.construct_object(value_node, deep=deep)
    return built


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _reject_duplicate_keys
)


def load_strict(path: Path):
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)


def dispatch_inputs(path: Path) -> dict:
    top = load_strict(path) or {}
    on = top.get("on", top.get(True))
    dispatch = on.get("workflow_dispatch") if isinstance(on, dict) else None
    if not isinstance(dispatch, dict):
        return {}
    return dispatch.get("inputs") or {}


def target_sha_gates() -> list[Path]:
    return [
        path
        for path in sorted(WORKFLOWS.glob("b62-*.yml"))
        if "target_sha" in dispatch_inputs(path)
    ]


GATES = target_sha_gates()
GATE_IDS = [path.name for path in GATES]


def embedded_body(step: dict) -> str:
    run = step.get("run") or ""
    opener = f"python3 - <<'{HEREDOC}'\n"
    assert opener in run, "the guard must embed the rule through a quoted heredoc"
    return run.split(opener, 1)[1].rsplit(HEREDOC, 1)[0].strip("\n")


# --- the rule -----------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (VALID, VALID),
        (VALID.upper(), VALID),
        (f"  {VALID}\n", VALID),
        ("0" * 9, None),
        ("0" * 39, None),
        ("0" * 41, None),
        ("z" * 40, None),
        ("g" + VALID[1:], None),
        ("0123 56789abcdefabcd0123456789abcdefabcd", None),
        ("", None),
        (None, None),
    ],
)
def test_only_a_full_hex_sha_names_a_commit(value, expected):
    assert rule.canonical_target_sha(value) == expected


@pytest.mark.parametrize("digits, value", [(9, "0" * 9), (39, "0" * 39), (41, "0" * 41), (0, "")])
def test_failure_message_counts_what_was_actually_typed(digits, value):
    assert rule.failure_message(value) == (
        f"target_sha는 40자리 전체 SHA여야 합니다(입력: {digits}자리). "
        "git rev-parse origin/main 값을 넣으세요"
    )


def test_failure_message_reports_a_non_hex_shape_as_its_own_length():
    assert "(입력: 40자리)" in rule.failure_message("z" * 40)


def test_the_embedded_copy_compiles():
    compile(rule.guard_text(), "<guard>", "exec")


# --- the rule as a gate step runs it ------------------------------------------


def _run_guard(tmp: Path, value: str) -> tuple[subprocess.CompletedProcess, str, str]:
    output = tmp / "github_output"
    envfile = tmp / "github_env"
    output.write_text("", encoding="utf-8")
    envfile.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.update(
        {
            "B62_TARGET_SHA_RAW": value,
            "GITHUB_OUTPUT": str(output),
            "GITHUB_ENV": str(envfile),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", rule.guard_text()],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result, output.read_text(encoding="utf-8"), envfile.read_text(encoding="utf-8")


def test_guard_publishes_the_normalized_value(tmp_path):
    result, outputs, envfile = _run_guard(tmp_path, VALID.upper())
    assert result.returncode == 0, result.stderr
    assert "B62_TARGET_SHA_INPUT_SHAPE=PASS" in result.stdout
    assert outputs == f"target_sha={VALID}\n"
    assert envfile == f"TARGET_SHA={VALID}\n"


@pytest.mark.parametrize("value", ["0" * 9, "0" * 39, "0" * 41, "z" * 40, ""])
def test_guard_fails_closed_before_publishing_anything(tmp_path, value):
    result, outputs, envfile = _run_guard(tmp_path, value)
    assert result.returncode == 1
    assert outputs == "" and envfile == ""
    assert "::error::target_sha는 40자리 전체 SHA여야 합니다" in result.stdout
    assert "git rev-parse origin/main 값을 넣으세요" in result.stdout


# --- the gates carry that copy, in the right order ----------------------------


def test_the_named_gates_are_inside_the_sweep():
    assert set(NAMED_GATES) <= set(GATE_IDS), GATE_IDS


def test_the_sweep_covers_every_b62_gate_taking_target_sha():
    declared = {
        path.name
        for path in WORKFLOWS.glob("b62-*.yml")
        if re.search(r"^      target_sha:\s*$", path.read_text(encoding="utf-8"), re.M)
    }
    assert declared == set(GATE_IDS), sorted(declared.symmetric_difference(GATE_IDS))


@pytest.mark.parametrize("path", GATES, ids=GATE_IDS)
def test_guard_is_the_first_step_and_precedes_every_checkout(path: Path):
    jobs = (load_strict(path) or {}).get("jobs") or {}
    first_name, first_job = next(iter(jobs.items()))
    steps = first_job.get("steps") or []
    assert steps, f"{path.name}: {first_name} has no steps"
    guard = steps[0]
    assert guard.get("id") == GUARD_ID, f"{path.name}: the first step is not the guard"
    assert guard.get("if") == "${{ github.event_name == 'workflow_dispatch' }}"
    assert (guard.get("env") or {}).get("B62_TARGET_SHA_RAW") == "${{ inputs.target_sha }}"
    checkouts = [
        index
        for index, step in enumerate(steps)
        if "actions/checkout" in str(step.get("uses", ""))
    ]
    assert not checkouts or min(checkouts) >= 1, f"{path.name}: a checkout runs before the guard"
    assert (first_job.get("outputs") or {}).get("target_sha") == (
        "${{ steps." + GUARD_ID + ".outputs.target_sha }}"
    )
    assert embedded_body(guard) == rule.guard_text(), f"{path.name}: the copy drifted"
    assert path.read_text(encoding="utf-8").count(f"- name: {GUARD_STEP_NAME}") == 1


@pytest.mark.parametrize("path", GATES, ids=GATE_IDS)
def test_no_job_reads_the_raw_input(path: Path):
    text = path.read_text(encoding="utf-8")
    jobs = (load_strict(path) or {}).get("jobs") or {}
    first_name = next(iter(jobs))
    for line in text.split("\n"):
        if "inputs.target_sha" in line:
            assert "B62_TARGET_SHA_RAW: ${{ inputs.target_sha }}" in line, (
                f"{path.name}: {line.strip()}"
            )
    assert not re.search(r"^  TARGET_SHA: ", text, re.M), f"{path.name}: default still set"
    for name, job in jobs.items():
        if name == first_name or not isinstance(job, dict):
            continue
        needs = job.get("needs")
        needs = [needs] if isinstance(needs, str) else list(needs or [])
        blob = yaml.safe_dump(job)
        if "${TARGET_SHA}" in blob or "${{ env.TARGET_SHA }}" in blob:
            assert (job.get("env") or {}).get("TARGET_SHA") == (
                "${{ needs." + first_name + ".outputs.target_sha }}"
            ), f"{path.name}: {name} does not read the normalized value"
            assert first_name in needs, f"{path.name}: {name} is missing needs {first_name}"
        if f"needs.{first_name}.outputs.target_sha" in blob:
            assert first_name in needs, f"{path.name}: {name} is missing needs {first_name}"
