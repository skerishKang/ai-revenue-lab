#!/usr/bin/env python3
"""Static and behavioural contract tests for the P0 ACT-1 credential
regeneration orchestration gate.

Run: python .github/tests/test_b54_engine_caller_credential_regeneration_gate.py

ACT-1 is SOURCE ONLY: these tests never dispatch anything, never touch the
network, and never install or use an admin token. They prove:

1. AUTH SPLIT (CENTRAL blocking fix): BUILTIN_GITHUB_TOKEN_FOR_SECRET_WRITE=NO
   — the single `gh secret set` call is authenticated ONLY with the dedicated
   admin authority; BUILTIN_GITHUB_TOKEN_FOR_ACTIONS_ORCHESTRATION=YES — every
   Actions orchestration command (`gh workflow run` / `gh run list` /
   `gh run watch` / `gh run view`) is bound ONLY to the built-in token at step
   level; the admin token is never assumed to hold Actions permissions
   (DEDICATED_ADMIN_TOKEN_FOR_ACTIONS_ORCHESTRATION=NO);
2. DEDICATED_ADMIN_AUTH_REQUIRED — a dedicated secret admin authority exists,
   its secret name differs from the regeneration target, and the workflow
   never loads the engine credential value at all;
3. APPLY is gated on workflow_dispatch + mode APPLY + environment: production
   + the exact confirmation phrase + exact-main guards (F6 fail-closed);
4. the credential generation contract is transport-safe (base64url, 64 ASCII
   chars, no padding, no whitespace, no non-ASCII, no shell word splitting)
   and executes at most once;
5. closed budgets: ONE_GENERATION_MAX, ONE_GITHUB_SECRET_WRITE_MAX,
   ONE_OVERLAY_ROTATION_MAX, ONE_ORACLE_MAX, one smoke dispatch, no automatic
   retry of any mutation;
6. the F0..F6 failure contract markers are all present and fail closed, and
   no automatic GitHub secret rollback exists;
7. NO_SECRET_DERIVED_OUTPUT — no step can echo, length-slice, hash, or
   otherwise materialize the generated credential or the admin token;
8. reuse without duplication: the overlay rotation gate, the canonical
   served-version guard, the credential-equivalence oracle, and the smoke-only
   gate are dispatched by file name, never re-implemented inline;
9. the PR trigger runs only the static contract tests; there is no push
   trigger and no PR/push path that can reach APPLY.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b54-engine-caller-credential-regeneration-gate.yml"

ADMIN_SECRET_NAME = "B62_GITHUB_SECRET_ADMIN_TOKEN"
TARGET_SECRET_NAME = "B62_P01_ENGINE_CREDENTIAL"
APPLY_PHRASE = "REGENERATE_B54_KAGENT_ENGINE_CREDENTIAL_FROM_EXACT_MAIN"
ROTATION_PHRASE = "ROTATE_B54_KAGENT_ENGINE_OVERLAY_FROM_EXACT_MAIN"
ORACLE_PHRASE = "RUN_B54_ENGINE_CREDENTIAL_EQUIVALENCE_PROBE"
SMOKE_PHRASE = "RUN_B54_ENGINE_POSTDEPLOY_SMOKE_ONLY"
ROTATION_GATE = "b54-engine-caller-registry-overlay-rotation-gate.yml"
ORACLE_GATE = "b54-engine-credential-equivalence-diagnostic-gate.yml"
SMOKE_GATE = "b54-engine-production-smoke-only-gate.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n")


def _code(text: str) -> str:
    # executable workflow content only: header/prose comments legitimately
    # name forbidden commands (`gh secret set` via the built-in token,
    # `gh workflow run`/`gh run watch` as the reuse mechanism) and must not
    # be counted as capability usage.
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


def _job(text: str, name: str) -> str:
    start = text.index(f"\n  {name}:\n")
    rest = text[start + 1:]
    match = re.search(r"\n  [a-z][a-z0-9-]*:\n", rest[len(f"  {name}:\n"):])
    return rest[: len(f"  {name}:\n") + match.start()] if match else rest


def _trigger_block(text: str) -> str:
    return text.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]


def _permissions_block(text: str) -> str:
    return text.split("\npermissions:\n", 1)[1].split("\nconcurrency:\n", 1)[0]


# 1. authority split: built-in token orchestrates Actions, never writes secrets


def test_builtin_github_token_secret_write_rejected() -> None:
    text = _text()
    code = _code(text)
    assert "secrets.GITHUB_TOKEN" not in text
    assert "secrets:" not in _permissions_block(text)
    # the single secret write authenticates ONLY with the admin authority
    assert code.count("gh secret set") == 1
    write_line = next(line for line in code.splitlines() if "gh secret set" in line)
    assert 'GH_TOKEN="${ADMIN_TOKEN}"' in write_line
    assert "GITHUB_TOKEN" not in write_line and "github.token" not in write_line
    # the admin authority must not be a copy of the built-in token
    assert 'if [ "${ADMIN_TOKEN}" = "${GITHUB_TOKEN:-}" ]; then' in text


def test_auth_split_secret_write_vs_actions_orchestration() -> None:
    text = _text()
    code = _code(text)
    apply_job = _code(_job(text, "regenerate-and-rotate"))
    # SECRET_WRITE_TOKEN=DEDICATED_ADMIN: the admin token is bound exactly
    # once in the mutating job and only on the secret write command.
    assert apply_job.count('GH_TOKEN="${ADMIN_TOKEN}"') == 1
    # WORKFLOW_DISPATCH_TOKEN=BUILTIN_GITHUB_TOKEN: exactly the three
    # orchestration steps (rotation dispatch, oracle, smoke) bind the
    # built-in token at step level.
    assert code.count("GH_TOKEN: ${{ github.token }}") == 3
    assert apply_job.count("GH_TOKEN: ${{ github.token }}") == 3
    # gh workflow run/list/watch/view never carry the admin token: the built-in
    # token is the only credential the orchestration commands can use.
    verbs = ("gh workflow run", "gh run list", "gh run watch", "gh run view")
    for line in apply_job.splitlines():
        if any(verb in line for verb in verbs):
            assert 'GH_TOKEN="${ADMIN_TOKEN}"' not in line
        if "gh secret" in line:
            assert "${{ github.token }}" not in line
    # the built-in token holds the Actions permission the orchestration needs
    assert "actions: write" in _job(text, "regenerate-and-rotate")
    # closed split vocabulary is echoed by the APPLY pre-authorization step,
    # the APPLY closed-evidence step, and the PLAN evidence step
    for flag in (
        "SECRET_WRITE_TOKEN=DEDICATED_ADMIN",
        "WORKFLOW_DISPATCH_TOKEN=BUILTIN_GITHUB_TOKEN",
        "BUILTIN_GITHUB_TOKEN_FOR_SECRET_WRITE=NO",
        "BUILTIN_GITHUB_TOKEN_FOR_ACTIONS_ORCHESTRATION=YES",
        "DEDICATED_ADMIN_TOKEN_FOR_SECRET_WRITE=YES",
        "DEDICATED_ADMIN_TOKEN_FOR_ACTIONS_ORCHESTRATION=NO",
    ):
        assert flag in text, flag


# 2. dedicated admin authority, distinct from the regeneration target


def test_dedicated_admin_auth_required() -> None:
    text = _text()
    assert f"{ADMIN_SECRET_NAME}" in text
    assert text.count(f"ADMIN_TOKEN: ${{{{ secrets.{ADMIN_SECRET_NAME} }}}}") == 3
    # the orchestrator never loads the engine credential VALUE anywhere
    # (the header comment may name the forbidden reference, code may not)
    assert f"${{{{ secrets.{TARGET_SECRET_NAME} }}}}" not in _code(text)
    # name separation: admin authority != regeneration target
    assert ADMIN_SECRET_NAME != TARGET_SECRET_NAME
    assert f"GITHUB_SECRET_NAME: {TARGET_SECRET_NAME}" in text
    assert "F0_ADMIN_AUTH_UNAVAILABLE=STOP_BEFORE_GENERATION" in text
    # in the mutating jobs the F0 guard fails closed BEFORE any generation
    for name in ("apply-preflight", "regenerate-and-rotate"):
        job = _job(text, name)
        pos = job.index("F0_ADMIN_AUTH_UNAVAILABLE=STOP_BEFORE_GENERATION")
        assert "exit 1" in job[pos : pos + 200], name
    # the APPLY generation step runs only after the F0 authorization step
    apply_job = _job(text, "regenerate-and-rotate")
    assert apply_job.index("F0") < apply_job.index("token_urlsafe")


# 3. APPLY gating


def test_apply_requires_production_environment() -> None:
    text = _text()
    apply_job = _job(text, "regenerate-and-rotate")
    assert "environment: production" in apply_job
    dispatch_gate = "github.event_name == 'workflow_dispatch' && inputs.mode == 'APPLY'"
    assert dispatch_gate in apply_job
    preflight = _job(text, "apply-preflight")
    assert dispatch_gate in preflight


def test_apply_requires_confirmation() -> None:
    text = _text()
    assert APPLY_PHRASE in text
    apply_job = _job(text, "regenerate-and-rotate")
    assert f'test "${{CONFIRMATION}}" = "{APPLY_PHRASE}"'.replace("${{", "${") in apply_job or (
        f'CONFIRMATION: ${{{{ inputs.confirmation }}}}' in apply_job
        and f'"{APPLY_PHRASE}"' in apply_job
    )
    # the confirmation gate precedes every mutating command
    conf_pos = apply_job.index(APPLY_PHRASE)
    assert conf_pos < apply_job.index("token_urlsafe")
    assert conf_pos < apply_job.index("gh secret set")


def test_exact_main_required() -> None:
    text = _text()
    assert "EXACT_MAIN_GUARD=PASS" in text
    for name in ("plan-preflight", "apply-preflight", "regenerate-and-rotate"):
        job = _job(text, name)
        assert "git rev-parse origin/main" in job
        assert "F6=STOP_MAIN_DRIFT" in job
    # dispatch checkouts pin the target_sha input, never a floating ref
    assert "ref: ${{ env.TARGET_SHA }}" in text


def test_no_apply_on_pr() -> None:
    text = _text()
    trigger = _trigger_block(text)
    assert "pull_request:" in trigger
    assert "push:" not in trigger
    # the PR trigger only ever runs the static source-contract job
    pr_paths = trigger.split("pull_request:", 1)[1].split("workflow_dispatch:", 1)[0]
    assert "b54-engine-caller-credential-regeneration-gate.yml" in pr_paths
    assert "test_b54_engine_caller_credential_regeneration_gate.py" in pr_paths
    source_job = _job(text, "source-contract")
    assert "APPLY_EXECUTED=NO" in source_job
    # APPLY jobs can never run under pull_request
    for name in ("apply-preflight", "regenerate-and-rotate"):
        assert "github.event_name == 'workflow_dispatch'" in _job(text, name)


def test_no_apply_on_push() -> None:
    text = _text()
    trigger = _trigger_block(text)
    assert re.search(r"^\s+push:", trigger, re.MULTILINE) is None
    assert "push:" not in trigger
    assert "pull_request_target" not in text


def test_mode_is_fail_closed_choice() -> None:
    text = _text()
    trigger = _trigger_block(text)
    assert "default: PLAN" in trigger
    options = re.search(r"options:\n\s+- PLAN\n\s+- APPLY\n", trigger)
    assert options is not None
    assert "APPLY" not in trigger.split("options:", 1)[0]


# 4. credential generation contract


def test_credential_generation_format() -> None:
    code = _code(_text())
    assert code.count("token_urlsafe") == 1
    assert "secrets.token_urlsafe(48)" in code
    assert 'end=""' in code  # no trailing newline / CRLF
    assert '[[ ! "${NEW_CREDENTIAL}" =~ ^[A-Za-z0-9_-]{64}$ ]]' in code
    # behavioural check of the exact runner capability used by the workflow
    value = subprocess.run(
        [sys.executable, "-c", 'import secrets; print(secrets.token_urlsafe(48), end="")'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert re.fullmatch(r"[A-Za-z0-9_-]{64}", value)
    assert value.isascii()
    assert value == value.strip()
    assert " " not in value and "\t" not in value and "\r" not in value and "\n" not in value
    assert "+" not in value and "/" not in value and "=" not in value  # base64url, no padding


def test_one_generation_max() -> None:
    code = _code(_text())
    assert code.count("token_urlsafe") == 1
    assert code.count("ONE_GENERATION_MAX=YES") == 1


# 5. closed mutation budgets and no automatic retry


def test_one_github_secret_write_max() -> None:
    code = _code(_text())
    assert code.count("gh secret set") == 1
    assert code.count("ONE_GITHUB_SECRET_WRITE_MAX=YES") == 1
    assert "gh secret delete" not in code


def test_one_overlay_rotation_max() -> None:
    code = _code(_text())
    assert code.count("gh workflow run") == 3
    assert code.count("-f mode=apply_overlay_credential_rotation") == 1
    assert code.count(ROTATION_PHRASE) == 1
    assert code.count('gh workflow run "${ROTATION_GATE_FILE}"') == 1
    assert code.count("ONE_OVERLAY_ROTATION_MAX=YES") == 1


def test_one_oracle_max() -> None:
    code = _code(_text())
    assert code.count("-f mode=credential_equivalence_probe") == 1
    assert code.count(ORACLE_PHRASE) == 1
    assert code.count("ONE_ORACLE_MAX=YES") == 1
    # exactly two requests inside the oracle are already locked by its own gate
    assert code.count('gh workflow run "${ORACLE_GATE_FILE}"') == 1
    assert code.count('gh workflow run "${SMOKE_GATE_FILE}"') == 1
    assert code.count(SMOKE_PHRASE) == 1


def test_no_automatic_retry() -> None:
    code = _code(_text())
    assert "--retry" not in code
    assert re.search(r"\buntil\b", code) is None
    assert code.count("gh run watch") == 3  # one watch per dispatched gate
    assert "NO_AUTOMATIC_RETRY=YES" in code
    # no dispatch appears inside a loop body: the polling loops only read
    # run ids, they never re-dispatch a mutation
    dispatch_lines = [i for i, line in enumerate(code.splitlines()) if "gh workflow run" in line]
    loop_lines = [i for i, line in enumerate(code.splitlines()) if re.match(r"\s*for .* in ", line)]
    for d in dispatch_lines:
        assert all(abs(d - l) > 3 for l in loop_lines)


# 6. failure contract F0..F6 and rollback design


def test_f0_f1_f2_f3_f4_f5_f6_fail_closed() -> None:
    text = _text()
    markers = (
        "F0_ADMIN_AUTH_UNAVAILABLE=STOP_BEFORE_GENERATION",
        "F1=STOP_GENERATED_VALUE_DISCARDED",
        "F2=STOP_NO_REPEAT_ROTATION",
        "F3=STOP_NO_ORACLE",
        "F4=STOP_SYSTEMATIC_WRITE_OR_AUTH_PATH_DEFECT",
        "F5=CREDENTIAL_CUTOVER_SUCCESS=YES_PRODUCT_SMOKE_FAIL=YES_NO_ROLLBACK",
        "F6=STOP_MAIN_DRIFT",
    )
    for marker in markers:
        assert marker in text, marker
    # every mutating-job failure branch exits non-zero right after emitting
    # its marker (the PLAN job's F0 report is informational by design)
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if any(stripped == f"echo '{m}'" for m in markers if not m.startswith("F0")):
            window = "\n".join(lines[idx : idx + 10])
            assert "exit 1" in window, stripped
    # F1 discards the generated value on both failure paths
    assert text.count("unset NEW_CREDENTIAL") == 3  # format failure, write failure, success
    # F4 forbids repeated generation automatically
    assert text.count("token_urlsafe") == 1
    # F5 never rolls back the credential
    assert "AUTOMATIC_GITHUB_SECRET_ROLLBACK=NO" in text
    assert "PRODUCT_SMOKE_FAIL=YES" in text


# 7. no secret-derived output


def test_no_secret_derived_output() -> None:
    text = _text()
    for line in text.splitlines():
        assert "echo" not in line or "NEW_CREDENTIAL" not in line, line
        assert "echo" not in line or "ADMIN_TOKEN}" not in line, line
    # no length slicing, hashing, or byte counting of secret material
    assert "${NEW_CREDENTIAL:" not in text and "${ADMIN_TOKEN:" not in text
    assert "sha256" not in text.lower() and "md5" not in text.lower()
    assert "wc -c" not in text
    assert "openssl" not in text.lower()
    # the credential reaches gh ONLY through a quoted stdin pipe
    assert 'printf \'%s\' "${NEW_CREDENTIAL}" | GH_TOKEN="${ADMIN_TOKEN}" gh secret set' in text
    # closed evidence vocabulary only
    for marker in (
        "GITHUB_SECRET_UPDATED=YES",
        "ENGINE_OVERLAY_APPLIED=YES",
        "NEW_SERVED_VERSION_CREATED=YES",
        "RAW_ORACLE_ACCEPTED=YES",
        "SMOKE_PASS=YES",
    ):
        assert marker in text
    assert "GENERATED_SECRET_OUTPUT=0" in text
    assert "ADMIN_TOKEN_OUTPUT=0" in text
    assert "SECRET_DERIVED_OUTPUT=0" in text


# 8. reuse without duplication


def test_reuse_without_duplication() -> None:
    text = _text()
    assert ROTATION_GATE in text
    assert ORACLE_GATE in text
    assert SMOKE_GATE in text
    # the canonical served-version guard script is reused, not re-implemented
    assert text.count("b54_engine_served_version_guard.py") >= 4
    # no inline Cloudflare secret PUT and no wrangler
    lowered = text.lower()
    assert "-x put" not in lowered and "--request put" not in lowered
    assert f"workers/scripts/${{engine_worker}}/secrets".lower() not in lowered
    assert "wrangler" not in lowered
    assert "build_overlay_put_body" not in text
    # every curl call is a GET read into a temp file
    for line in text.splitlines():
        if "curl " in line:
            assert "-o " in line and "-x" not in line.lower() and "--data" not in line.lower(), line
    # the reuse mechanism (dispatch+watch) is explained for reviewers
    assert "cannot invoke another workflow's job" in text


# 9. workflow hygiene


def test_workflow_hygiene() -> None:
    text = _text()
    assert "workflow_dispatch:" in text
    assert "cancel-in-progress: false" in text
    assert "contents: write" not in text
    assert "workflow_write" not in text
    assert "deploy" not in _trigger_block(text)
    # ACT-1 locks are echoed by the source-contract job
    source_job = _job(text, "source-contract")
    for lock in (
        "NEW_SECRET_GENERATION=0",
        "GITHUB_SECRET_MUTATION=0",
        "CLOUDFLARE_SECRET_MUTATION=0",
        "GATE_DISPATCH_ISSUED=0",
        "ADMIN_TOKEN_INSTALL=NO",
        "PRODUCTION_MUTATION=0",
    ):
        assert lock in source_job


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"B54_CREDENTIAL_REGENERATION_GATE_TESTS=PASS ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
