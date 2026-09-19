"""R2 credential authority split contract (#2768, parent #2394).

Source-contract only. No secret is created, read, rotated, or installed here, no
workflow is dispatched, and no R2 or Cloudflare endpoint is contacted. These
tests read two workflow files and prove that the read-only and mutation
authorities cannot be confused at the wiring level.

The split being enforced:

```text
read-only R2 metadata/probe   -> B62_R2_READONLY_API_TOKEN
R2 object mutation            -> B62_R2_OPS_API_TOKEN
public CDN convergence read   -> no Cloudflare credential
```

Why it is asserted structurally: the defect being fixed was a single job-level
`CLOUDFLARE_API_TOKEN` that every step inherited, so the credential a step
actually held was invisible at the step that used it. Parsing the YAML is the
only way to ask "what token does this specific step receive".
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"

PROBE = WORKFLOWS / "cloudflare-r2-readonly-auth-probe.yml"
UPLOAD = WORKFLOWS / "padiem-r2-c14-media-upload.yml"

READONLY_SECRET = "B62_R2_READONLY_API_TOKEN"
OPS_SECRET = "B62_R2_OPS_API_TOKEN"
SHARED_DEPLOYMENT_SECRET = "CLOUDFLARE_API_TOKEN"  # the generic Engine/Worker token

MUTATION_STEP = "Download from Drive and upload to R2"
CONVERGENCE_STEP = "Verify public convergence"
DRY_RUN_STEP = "Upload plan (dry run)"
PREFLIGHT_STEP = "Preflight existing keys (no overwrite)"
CONTRACT_STEP = "Mutation contract"


def _load(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), path
    return doc


def _steps(doc: dict) -> dict[str, dict]:
    job = doc["jobs"]["upload"] if "upload" in doc["jobs"] else next(iter(doc["jobs"].values()))
    return {step["name"]: step for step in job["steps"] if "name" in step}


def _env(step: dict) -> dict[str, str]:
    return {str(k): str(v) for k, v in (step.get("env") or {}).items()}


def _run(step: dict) -> str:
    return str(step.get("run", ""))


def _job_env(path: Path) -> dict[str, str]:
    doc = _load(path)
    job = doc["jobs"]["upload"] if "upload" in doc["jobs"] else next(iter(doc["jobs"].values()))
    return {str(k): str(v) for k, v in (job.get("env") or {}).items()}


def _all_token_bindings(steps: dict[str, dict]) -> dict[str, str]:
    """step name -> the credential that step receives as CLOUDFLARE_API_TOKEN."""
    bound = {}
    for name, step in steps.items():
        env = _env(step)
        value = env.get("CLOUDFLARE_API_TOKEN")
        if value is not None:
            bound[name] = value
    return bound


# --- the read-only probe stays read-only --------------------------------------

def test_probe_workflow_is_bound_only_to_the_readonly_credential() -> None:
    doc = _load(PROBE)
    text = PROBE.read_text(encoding="utf-8")
    assert f"secrets.{READONLY_SECRET}" in text
    assert OPS_SECRET not in text
    # The generic shared deployment credential must not leak in either.
    assert "secrets.CLOUDFLARE_API_TOKEN" not in text
    bindings = _all_token_bindings(_steps(doc))
    for step_name, value in bindings.items():
        assert READONLY_SECRET in value, step_name


def test_probe_workflow_never_touches_the_ops_secret() -> None:
    assert OPS_SECRET not in PROBE.read_text(encoding="utf-8")


# --- the mutation path is bound to OPS only -----------------------------------

def test_mutation_step_receives_the_ops_credential() -> None:
    steps = _steps(_load(UPLOAD))
    bindings = _all_token_bindings(steps)
    assert MUTATION_STEP in bindings, "mutation step must name its credential"
    assert bindings[MUTATION_STEP] == "${{ secrets." + OPS_SECRET + " }}"


def test_mutation_step_does_not_receive_the_readonly_credential() -> None:
    steps = _steps(_load(UPLOAD))
    env = _env(steps[MUTATION_STEP])
    assert READONLY_SECRET not in env.get("CLOUDFLARE_API_TOKEN", "")
    # and not anywhere else in that step's body either
    assert READONLY_SECRET not in _run(steps[MUTATION_STEP])


def test_job_level_env_binds_no_credential_at_all() -> None:
    # This is the anti-expansion guarantee. A job-level token is inherited by
    # every step, which is exactly how a read-only credential ended up driving
    # writes; keeping it absent makes each step's authority a local, checkable
    # fact instead of an inheritance accident.
    job_env = _job_env(UPLOAD)
    assert "CLOUDFLARE_API_TOKEN" not in job_env
    assert job_env.get("CLOUDFLARE_ACCOUNT_ID"), "account id stays job-scoped"


# --- no fallback in any direction ---------------------------------------------

def _binding(secret: str) -> str:
    # Built by concatenation on purpose: inside an f-string, `${{ ... }}`
    # collapses to a single brace pair and silently stops matching the real
    # GitHub Actions expression syntax.
    return "CLOUDFLARE_API_TOKEN: ${{ secrets." + secret + " }}"


def test_no_readonly_to_ops_or_ops_to_readonly_fallback_exists() -> None:
    text = UPLOAD.read_text(encoding="utf-8")
    # A fallback would be visible as ONE binding expression offering more than
    # one credential, so the scan is per line: a whole-file regex with DOTALL
    # would simply match the two legitimate bindings against each other.
    for pattern in (
        r"secrets\.\w+\s*(?:\|\||\bor\b|\?\?|&&)\s*secrets\.",
        r"secrets\.\w+.*secrets\.\w+",
    ):
        for line in text.splitlines():
            assert not re.search(pattern, line), f"{pattern} in: {line.strip()}"
    # The upload workflow has exactly one privileged binding: R2 OPS on the
    # object mutation step. READONLY stays in the separate metadata probe.
    assert text.count("CLOUDFLARE_API_TOKEN: ${{ secrets.") == 1
    assert _binding(OPS_SECRET) in text
    assert _binding(READONLY_SECRET) not in text
    assert _binding(SHARED_DEPLOYMENT_SECRET) not in text


def test_shared_engine_worker_deployment_token_is_not_a_fallback() -> None:
    steps = _steps(_load(UPLOAD))
    bindings = _all_token_bindings(steps)
    for name, value in bindings.items():
        assert f"secrets.{SHARED_DEPLOYMENT_SECRET}" not in value, name
    assert "secrets.CLOUDFLARE_API_TOKEN" not in UPLOAD.read_text(encoding="utf-8")


def test_each_credential_is_bound_to_exactly_one_step() -> None:
    bindings = _all_token_bindings(_steps(_load(UPLOAD)))
    ops_steps = [n for n, v in bindings.items() if OPS_SECRET in v]
    readonly_steps = [n for n, v in bindings.items() if READONLY_SECRET in v]
    assert ops_steps == [MUTATION_STEP]
    assert readonly_steps == []


# --- OPS token absent fails closed before any write ---------------------------

def test_missing_ops_credential_fails_closed_before_mutation() -> None:
    body = _run(_steps(_load(UPLOAD))[MUTATION_STEP])
    guard = body.index("R2_CREDENTIAL_PRESENT=NO")
    first_write = body.index("'r2', 'object', 'put'") if "'r2', 'object', 'put'" in body else -1
    first_wrangler = body.index("wrangler@")
    assert guard < first_wrangler, "presence guard must precede any wrangler call"
    if first_write != -1:
        assert guard < first_write
    assert "exit 1" in body[: body.index("R2_CREDENTIAL_PRESENT=YES")]
    assert "set -euo pipefail" in body


def test_credential_presence_is_reported_without_exposing_a_value() -> None:
    body = _run(_steps(_load(UPLOAD))[MUTATION_STEP])
    assert "R2_CREDENTIAL_PRESENT=YES" in body
    # The guard tests length only; it must never print or echo the token.
    assert "test -n \"${CLOUDFLARE_API_TOKEN:-}\"" in body
    for forbidden in ("echo \"${CLOUDFLARE_API_TOKEN", "echo ${CLOUDFLARE_API_TOKEN",
                      "print(token)", "echo $CLOUDFLARE_API_TOKEN"):
        assert forbidden not in body, forbidden


def test_no_raw_secret_output_in_the_whole_workflow() -> None:
    doc = _load(UPLOAD)
    steps = _steps(doc)
    for name, step in steps.items():
        body = _run(step)
        for forbidden in ("echo \"${CLOUDFLARE_API_TOKEN", "echo ${CLOUDFLARE_API_TOKEN}",
                          "print(env['CLOUDFLARE_API_TOKEN'", "set -x"):
            assert forbidden not in body, f"{name}: {forbidden}"
    text = UPLOAD.read_text(encoding="utf-8")
    assert "SECRET_VALUE_OUTPUT=0" in text


# --- dry run performs no mutation ---------------------------------------------

def test_dry_run_step_holds_no_credential_and_claims_no_mutation() -> None:
    steps = _steps(_load(UPLOAD))
    dry = steps[DRY_RUN_STEP]
    assert "CLOUDFLARE_API_TOKEN" not in _env(dry)
    body = _run(dry)
    assert "R2_MUTATION=NONE" in body
    assert "wrangler" not in body
    assert dry["if"] == "${{ inputs.dry_run }}"


def test_mutation_and_convergence_steps_are_gated_off_for_dry_run() -> None:
    steps = _steps(_load(UPLOAD))
    for name in (MUTATION_STEP, CONVERGENCE_STEP):
        assert steps[name]["if"] == "${{ !inputs.dry_run }}", name


def test_read_only_steps_need_no_credential() -> None:
    steps = _steps(_load(UPLOAD))
    for name in (PREFLIGHT_STEP, CONVERGENCE_STEP, CONTRACT_STEP):
        assert "CLOUDFLARE_API_TOKEN" not in _env(steps[name]), name


# --- public convergence is credential-free -------------------------------------


def test_public_convergence_step_receives_no_cloudflare_credential() -> None:
    steps = _steps(_load(UPLOAD))
    convergence = steps[CONVERGENCE_STEP]
    assert "CLOUDFLARE_API_TOKEN" not in _env(convergence)
    assert READONLY_SECRET not in _run(convergence)
    assert OPS_SECRET not in _run(convergence)


def test_upload_workflow_contains_no_authenticated_cache_purge_or_zone_api() -> None:
    text = UPLOAD.read_text(encoding="utf-8")
    assert "purge_cache" not in text
    assert "/client/v4/zones" not in text
    assert "Authorization: Bearer" not in text


def test_readonly_secret_is_confined_to_the_separate_probe_workflow() -> None:
    assert READONLY_SECRET not in UPLOAD.read_text(encoding="utf-8")
    assert f"secrets.{READONLY_SECRET}" in PROBE.read_text(encoding="utf-8")


def test_public_convergence_keeps_bounded_read_only_verification() -> None:
    body = _run(_steps(_load(UPLOAD))[CONVERGENCE_STEP])
    assert "CONVERGE_ROUND" in body
    assert "PUBLIC_CONVERGENCE=ALL_200" in body
    assert "PUBLIC_RANGE=206" in body
    assert "-I" in body
    assert "-r" in body
    assert "-X" not in body
