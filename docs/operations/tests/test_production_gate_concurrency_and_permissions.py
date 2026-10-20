"""Load-bearing contract for the #5248 production-gate concurrency and permission scope.

Two production-facing GitHub Actions contracts are pinned here:

1. ``.github/workflows/b54-engine-production-deploy-gate.yml`` must serialise
   every run that can change the served version of the single ``padiem-ai-engine``
   Worker, and it must keep its queue lossless.
2. ``.github/workflows/b62-password-auth-fast-production-activation.yml`` must
   carry the ``actions: write`` scope ONLY on the job that actually dispatches a
   downstream workflow; the read-only source-contract job must not hold it.

The new failure this file detects: a future edit drops the Engine mutex, turns
it into a single-slot queue that can evict a queued emergency rollback, or
re-grants workflow-wide write scope to a read-only job. No existing test in the
repository asserts either invariant, and both regressions are silent in CI:
the workflows keep parsing and keep running, they only lose the protection that
issue #5248 was raised for.

The mutation tests at the end restore each defect on a parsed copy of the
document and prove the contract actually fails, so a passing run cannot come
from a vacuous assertion.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github" / "workflows"

B54_ENGINE_DEPLOY_GATE = WORKFLOWS / "b54-engine-production-deploy-gate.yml"
B62_PASSWORD_AUTH_ACTIVATION = WORKFLOWS / "b62-password-auth-fast-production-activation.yml"

# The mutex group is a constant on purpose. A per-event or per-ref group would
# let a deploy and a rollback of the same Worker land in different groups.
B54_ENGINE_CONCURRENCY_GROUP = "b54-engine-production-deploy-gate"

B62_ACTIVATION_CONCURRENCY_GROUP = "b62-password-auth-fast-production-activation"
B62_ACTIVATION_PATH = ".github/workflows/b62-password-auth-fast-production-activation.yml"


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), path
    return document


def _events(document: dict[str, Any]) -> dict[str, Any]:
    # PyYAML 1.1 parses the unquoted GitHub Actions key `on` as boolean True.
    events = document.get("on", document.get(True))
    assert isinstance(events, dict), "workflow must declare event triggers"
    return events


def _step_names(job: dict[str, Any]) -> list[str]:
    return [str(step.get("name", "")) for step in job.get("steps", [])]


def _step_run(job: dict[str, Any], name: str) -> str:
    for step in job.get("steps", []):
        if step.get("name") == name:
            return str(step.get("run", ""))
    raise AssertionError(f"step not found: {name}")


# --------------------------------------------------------------------------- #
# B54 Engine production deploy gate
# --------------------------------------------------------------------------- #


def _assert_b54_engine_mutex(document: dict[str, Any]) -> None:
    """The Engine Worker must never be changed by two overlapping runs."""
    concurrency = document.get("concurrency")
    assert isinstance(concurrency, dict), (
        "the Engine deploy gate must declare a workflow-level concurrency group; "
        "without it a deploy and a rollback can mutate the same Worker at once"
    )
    assert set(concurrency) == {"group", "cancel-in-progress", "queue"}, sorted(concurrency)
    assert concurrency["group"] == B54_ENGINE_CONCURRENCY_GROUP
    # A running deploy must never be cancelled by a later rollback dispatch.
    assert concurrency["cancel-in-progress"] is False
    # The GitHub default (`queue: single`) keeps only ONE pending run per group
    # and lets a NEW pending run REPLACE it, which can evict a queued emergency
    # rollback before it ever starts. `queue: max` keeps up to 100 pending runs.
    assert concurrency["queue"] == "max"
    # A constant group keeps deploy, rollback and smoke in one mutex.
    assert "${{" not in str(concurrency["group"]), (
        "the Engine mutex group must be constant so a deploy and a rollback of "
        "the same Worker cannot land in different groups"
    )


def _assert_b54_engine_existing_guards_preserved(document: dict[str, Any]) -> None:
    """The mutex is additive: every existing refusal rule must survive it."""
    events = _events(document)
    assert set(events) == {"workflow_dispatch"}, (
        "the Engine deploy gate stays dispatch-only; a CI push must not enter the mutex"
    )
    inputs = events["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"target_sha", "confirmation", "rollback_version_id"}
    assert inputs["target_sha"]["required"] is True
    assert inputs["confirmation"]["required"] is True
    assert inputs["rollback_version_id"]["required"] is False

    jobs = document["jobs"]
    assert set(jobs) == {"deploy-production-engine", "smoke-idempotency", "rollback-production-engine"}
    deploy = jobs["deploy-production-engine"]
    rollback = jobs["rollback-production-engine"]
    smoke = jobs["smoke-idempotency"]

    # Confirmation phrases and the Production environment.
    assert deploy["if"] == "github.event.inputs.confirmation == 'DEPLOY_B54_ENGINE_FROM_EXACT_MAIN'"
    assert smoke["if"] == "github.event.inputs.confirmation == 'DEPLOY_B54_ENGINE_FROM_EXACT_MAIN'"
    assert rollback["if"] == "github.event.inputs.confirmation == 'ROLLBACK_B54_ENGINE_TO_PREVIOUS_VERSION'"
    assert deploy["environment"] == "production"
    assert rollback["environment"] == "production"
    assert smoke["environment"] == "production"
    assert smoke["needs"] == "deploy-production-engine"

    # Exact-main verification: the deploy and the rollback still refuse a
    # non-exact SHA before any mutation.
    premutation = _step_run(deploy, "Premutation exact-main and account assertions")
    assert 'test "$(git rev-parse HEAD)" = "${{ github.event.inputs.target_sha }}"' in premutation
    assert 'test "$(git rev-parse origin/main)" = "${{ github.event.inputs.target_sha }}"' in premutation

    # Durable pre-mutation rollback anchor.
    anchor_steps = _step_names(deploy)
    assert "Pre-deploy canonical served-version rollback anchor" in anchor_steps
    assert "Publish the pre-mutation rollback anchor artifact (hard deploy precondition)" in anchor_steps
    anchor = _step_run(deploy, "Pre-deploy canonical served-version rollback anchor")
    assert "PRE_DEPLOY_SERVED_VERSION_ID=${pre_version}" in anchor
    assert "ROLLBACK_ANCHOR_AVAILABLE=YES" in anchor
    assert "DEPLOY_EXECUTED=NO" in anchor
    assert anchor_steps.index("Pre-deploy canonical served-version rollback anchor") < anchor_steps.index(
        "Deploy engine to production"
    )

    # Post-deploy served-version verification.
    post = _step_run(deploy, "Post-deploy served-version secret guard")
    assert "b54_engine_served_version_guard.py" in post
    assert "b62_binding_state_guard.py" in post
    assert "B54_ENGINE_PRODUCTION_DEPLOY=PASS" in post
    assert anchor_steps.index("Post-deploy served-version secret guard") < anchor_steps.index("Post-deploy smoke")

    # Rollback still names its own target and still proves the served version
    # equals that target.
    rollback_run = _step_run(rollback, "Rollback engine worker to previous version")
    assert "ROLLBACK_TARGET" in rollback_run
    assert "validate-version-id" in rollback_run
    assert "wrangler@4 rollback" in rollback_run
    assert "POST_ROLLBACK_SERVED_EQUALS_TARGET=PASS" in rollback_run
    assert "B54_ENGINE_PRODUCTION_ROLLBACK=PASS" in rollback_run


def test_b54_engine_deploy_gate_serialises_the_single_engine_worker() -> None:
    _assert_b54_engine_mutex(_load(B54_ENGINE_DEPLOY_GATE))


def test_b54_engine_deploy_gate_keeps_every_existing_refusal_rule() -> None:
    _assert_b54_engine_existing_guards_preserved(_load(B54_ENGINE_DEPLOY_GATE))


# --------------------------------------------------------------------------- #
# B62 password-auth fast production activation
# --------------------------------------------------------------------------- #


def _assert_b62_permission_scope(document: dict[str, Any]) -> None:
    """Write scope lives on the dispatching job only."""
    permissions = document.get("permissions")
    assert isinstance(permissions, dict), "the workflow must declare a top-level permission scope"
    assert permissions == {"contents": "read"}, (
        "the workflow-level scope must stay read-only; `actions: write` belongs "
        "on the job that dispatches a downstream workflow"
    )

    jobs = document["jobs"]
    activate = jobs["activate-production"]
    assert activate["permissions"] == {"contents": "read", "actions": "write"}, (
        "the dispatching job must keep the `actions: write` scope that "
        "`gh workflow run` requires, plus read-only contents for the checkout"
    )

    source_contract = jobs["source-contract"]
    source_permissions = source_contract.get("permissions")
    assert source_permissions is None or "actions" not in source_permissions, (
        "the read-only source-contract job must not hold write scope"
    )


def _assert_b62_activation_flow_preserved(document: dict[str, Any]) -> None:
    """The permission change must not alter the activation contract."""
    events = _events(document)
    assert set(events) == {"pull_request", "push"}
    assert events["pull_request"]["paths"] == [B62_ACTIVATION_PATH]
    assert events["push"]["branches"] == ["main"]
    assert events["push"]["paths"] == [B62_ACTIVATION_PATH]

    concurrency = document.get("concurrency")
    assert isinstance(concurrency, dict)
    assert concurrency == {
        "group": B62_ACTIVATION_CONCURRENCY_GROUP,
        "cancel-in-progress": False,
    }, "the existing activation concurrency group must be preserved"

    jobs = document["jobs"]
    assert set(jobs) == {"source-contract", "activate-production"}
    activate = jobs["activate-production"]
    assert activate["needs"] == "source-contract"
    assert activate["if"] == "${{ github.event_name == 'push' }}"
    assert activate["environment"] == "production"

    steps = "\n".join(str(step.get("run", "")) for step in activate.get("steps", []))
    assert "gh workflow run" in steps, "the downstream dispatch must still happen"
    assert "b62-auth-d1-migration-012-gate.yml" in steps
    assert "b62-production-code-deploy-gate.yml" in steps
    assert "APPLY_B62_AUTH_D1_MIGRATION_012_FROM_EXACT_MAIN" in steps
    assert "DEPLOY_B62_PRODUCTION_CODE_FROM_EXACT_MAIN" in steps


def test_b62_password_auth_activation_scopes_actions_write_to_the_dispatch_job() -> None:
    _assert_b62_permission_scope(_load(B62_PASSWORD_AUTH_ACTIVATION))


def test_b62_password_auth_activation_keeps_its_triggers_and_dispatch_flow() -> None:
    _assert_b62_activation_flow_preserved(_load(B62_PASSWORD_AUTH_ACTIVATION))


# --------------------------------------------------------------------------- #
# Mutation / differential proof: restoring the defect must fail the contract.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("defect", "apply_defect"),
    [
        pytest.param(
            "mutex-removed",
            lambda d: d.pop("concurrency"),
            id="mutex-removed",
        ),
        pytest.param(
            "queue-defaults-to-single",
            lambda d: d["concurrency"].pop("queue"),
            id="queue-defaults-to-single",
        ),
        pytest.param(
            "queue-replaced-by-single",
            lambda d: d["concurrency"].__setitem__("queue", "single"),
            id="queue-replaced-by-single",
        ),
        pytest.param(
            "running-deploy-cancellable",
            lambda d: d["concurrency"].__setitem__("cancel-in-progress", True),
            id="running-deploy-cancellable",
        ),
        pytest.param(
            "group-split-per-event",
            lambda d: d["concurrency"].__setitem__(
                "group", "${{ github.event.inputs.confirmation }}"
            ),
            id="group-split-per-event",
        ),
    ],
)
def test_b54_engine_mutex_contract_rejects_each_removed_defect(
    defect: str, apply_defect: Any
) -> None:
    document = deepcopy(_load(B54_ENGINE_DEPLOY_GATE))
    apply_defect(document)
    with pytest.raises(AssertionError):
        _assert_b54_engine_mutex(document)


@pytest.mark.parametrize(
    ("defect", "apply_defect"),
    [
        pytest.param(
            "workflow-wide-actions-write",
            lambda d: d["permissions"].__setitem__("actions", "write"),
            id="workflow-wide-actions-write",
        ),
        pytest.param(
            "dispatch-job-loses-actions-write",
            lambda d: d["jobs"]["activate-production"]["permissions"].pop("actions"),
            id="dispatch-job-loses-actions-write",
        ),
        pytest.param(
            "source-contract-holds-actions-write",
            lambda d: d["jobs"]["source-contract"].__setitem__(
                "permissions", {"contents": "read", "actions": "write"}
            ),
            id="source-contract-holds-actions-write",
        ),
    ],
)
def test_b62_permission_scope_contract_rejects_each_removed_defect(
    defect: str, apply_defect: Any
) -> None:
    document = deepcopy(_load(B62_PASSWORD_AUTH_ACTIVATION))
    apply_defect(document)
    with pytest.raises(AssertionError):
        _assert_b62_permission_scope(document)
