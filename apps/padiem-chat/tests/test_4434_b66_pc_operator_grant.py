"""#4434 follow-up: B66 operator PC grant composes fail-closed from Worker env.

Load-bearing contract: production behavior is unchanged (default-off) until
the owner sets both reviewed env values; a grant can only name product
``b66``, a single ``owner:`` workspace and read-side operations. ``file.write``
or any unknown value anywhere resolves to default-off instead of a partial
grant. No admin API, D1 table or new authority is created by this path.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from padiem_control_plane.local_agent_pc_access import (
    PcAccessOperation,
    ProductPcAccessPolicy,
)

from app.b66_pc_operator_grant_composition import (
    B66_PC_OPERATOR_OPERATIONS_ENV,
    B66_PC_OPERATOR_WORKSPACE_ENV,
    build_b66_pc_operator_policy,
)

WORKSPACE = "owner:usr_" + "b" * 32


def env(workspace=None, operations=None):
    values = {}
    if workspace is not None:
        values[B66_PC_OPERATOR_WORKSPACE_ENV] = workspace
    if operations is not None:
        values[B66_PC_OPERATOR_OPERATIONS_ENV] = operations
    return values


def test_missing_env_stays_default_off():
    for candidate in ({}, env(operations="file.read"),
                      env(workspace=WORKSPACE), {"other": "x"}):
        policy = build_b66_pc_operator_policy(candidate)
        assert policy == ProductPcAccessPolicy.default_off()


def test_object_style_worker_env_is_accepted():
    policy = build_b66_pc_operator_policy(SimpleNamespace(**env(WORKSPACE, "file.read,task.result")))
    assert policy != ProductPcAccessPolicy.default_off()
    grant = policy.grant_for("b66")
    assert grant is not None
    assert grant.workspace_ref == WORKSPACE
    assert grant.operations == frozenset({PcAccessOperation.FILE_READ, PcAccessOperation.TASK_RESULT})


def test_txt_slice_operations_compose_exact_grant():
    policy = build_b66_pc_operator_policy(env(WORKSPACE, "file.read,task.result"))
    grant = policy.grant_for("b66")
    assert grant is not None and grant.product_id == "b66"
    assert grant.workspace_ref == WORKSPACE
    assert grant.operations == frozenset({PcAccessOperation.FILE_READ, PcAccessOperation.TASK_RESULT})


def test_file_write_is_never_granted():
    for operations in ("file.write", "file.read,file.write", "FILE.WRITE"):
        assert build_b66_pc_operator_policy(env(WORKSPACE, operations)) == \
            ProductPcAccessPolicy.default_off()


def test_unknown_operation_or_empty_list_fails_closed():
    for operations in ("", "   ", "file.read,rocket.launch", "file.read,,file.read, bogus"):
        assert build_b66_pc_operator_policy(env(WORKSPACE, operations)) == \
            ProductPcAccessPolicy.default_off()


def test_workspace_must_be_owner_scoped_token():
    for workspace in ("", "usr_" + "b" * 32, "owner:", "owner:bad ref!",
                      "other:usr_" + "b" * 32, "owner:usr has space"):
        assert build_b66_pc_operator_policy(env(workspace, "file.read")) == \
            ProductPcAccessPolicy.default_off()


def test_whitespace_is_trimmed_but_shape_still_enforced():
    policy = build_b66_pc_operator_policy(env("  " + WORKSPACE + "  ", "  file.read , task.result "))
    grant = policy.grant_for("b66")
    assert grant is not None and grant.workspace_ref == WORKSPACE


def test_case_insensitive_operation_tokens():
    policy = build_b66_pc_operator_policy(env(WORKSPACE, "FILE.READ,Task.Result"))
    grant = policy.grant_for("b66")
    assert grant is not None
    assert grant.operations == frozenset({PcAccessOperation.FILE_READ, PcAccessOperation.TASK_RESULT})


def test_duplicates_collapse_to_single_grant():
    policy = build_b66_pc_operator_policy(env(WORKSPACE, "file.read,file.read"))
    grant = policy.grant_for("b66")
    assert grant is not None and grant.operations == frozenset({PcAccessOperation.FILE_READ})
