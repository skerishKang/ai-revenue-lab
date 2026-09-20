"""Static contract tests for the B54 Calendar Production readiness preflight.

These tests never call Cloudflare, Google, Calendar, or D1. They pin the
safety invariants of the readiness preflight so a future edit cannot silently:

* widen the read into a mutation (D1 or otherwise);
* emit a secret value, a raw calendar id, or a raw grant ref;
* claim that ``calendar.readonly`` was granted just because the shared Google
  OAuth refresh-token secret is present;
* make a Calendar provider call or perform any Google OAuth mutation.

Scope truth is the central invariant of this workflow: a served refresh-token
secret proves only that a secret exists. Scope grant can only be proven by a
provider call, which this preflight deliberately never makes, so the reported
status is pinned to ``UNVERIFIED_WITHOUT_PROVIDER``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = Path(".github/workflows/b54-calendar-production-readiness-preflight.yml")

APP_ID = "b54-padiem-claw-calendar"
AGENT_ID = "agent:padiem:claw_calendar_reader@1"
CONNECTOR_ID = "connector:google:calendar@1"
CORE_READ_SCOPE = "calendar.readonly"
PROVIDER_READ_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"

CONFIRMATION_PHRASE = "RUN_B54_CALENDAR_PRODUCTION_READINESS_PREFLIGHT"

REQUIRED_INVARIANTS = (
    "CALENDAR_OAUTH_SCOPE_STATUS=UNVERIFIED_WITHOUT_PROVIDER",
    "SECRET_PRESENT != CALENDAR_SCOPE_GRANTED",
    "RAW_CALENDAR_ID_OUTPUT=0",
    "RAW_BINDING_REF_OUTPUT=0",
    "RAW_ACTOR_REF_OUTPUT=0",
    "SECRET_VALUE_OUTPUT=0",
    "ROW_VALUE_OUTPUT=AGGREGATES_ONLY",
    "D1_QUERY_MODE=READ_ONLY",
    "D1_MUTATION=0",
    "CALENDAR_PROVIDER_CALLS=0",
    "CALENDAR_CREATE=0",
    "CALENDAR_UPDATE=0",
    "CALENDAR_DELETE=0",
    "CALENDAR_RESPOND=0",
    "CALENDAR_WRITE=0",
    "GOOGLE_OAUTH_MUTATION=0",
    "CALENDAR_GRANT_SEED=0",
    "PRODUCTION_MUTATION=0",
    "PRODUCTION_READONLY_AUTO_ON_MAIN_PUSH=NO",
    "PRODUCTION_READONLY_DISPATCH_ONLY=YES",
)

TEST_FILE_TRIGGER_PATH = ".github/tests/test_b54_calendar_production_readiness_preflight.py"

FORBIDDEN_MUTATION_SQL = (
    "INSERT INTO",
    "UPDATE ",
    "DELETE FROM",
    "REPLACE INTO",
    "DROP TABLE",
    "ALTER TABLE",
    "CREATE TABLE",
    "CREATE INDEX",
)


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def workflow_document() -> dict:
    return yaml.safe_load(workflow_text())


def live_job() -> dict:
    jobs = workflow_document()["jobs"]
    assert "production-readonly" in jobs
    return jobs["production-readonly"]


def live_job_text() -> str:
    marker = "  production-readonly:"
    _, _, tail = workflow_text().partition(marker)
    assert tail, "production-readonly job not found"
    return tail


def source_contract_text() -> str:
    marker = "Validate Calendar readiness preflight contract"
    _, _, tail = workflow_text().partition(marker)
    assert tail, "source-contract step not found"
    return tail.split("  production-readonly:", 1)[0]


def grant_read_text() -> str:
    marker = "Read canonical Calendar grant aggregate"
    _, _, tail = workflow_text().partition(marker)
    assert tail, "grant aggregate step not found"
    return tail


def test_workflow_is_valid_yaml() -> None:
    document = workflow_document()
    assert document["name"] == "B54 Calendar Production Readiness Preflight"
    assert document["permissions"] == {"contents": "read"}
    assert set(document["jobs"]) == {"source-contract", "production-readonly"}


def test_exact_main_guard_present() -> None:
    """A. exact-main guard: the live job re-checks origin/main before reading."""
    text = live_job_text()
    assert "git rev-parse HEAD" in text
    assert "git rev-parse origin/main" in text
    assert "READONLY_EXACT_MAIN_SHA=PASS" in text


def test_served_engine_version_resolved() -> None:
    """B. the actually served Engine version is resolved, never assumed."""
    text = live_job_text()
    assert "b54_engine_served_version_guard.py resolve-active" in text
    assert "ACTIVE_ENGINE_VERSION" in text
    assert "ENGINE_ACTIVE_VERSION_IDENTIFIED=PASS" in text


def test_reads_binding_name_and_type_only() -> None:
    """C. binding NAME/TYPE only; no secret value is ever read or emitted."""
    text = live_job_text()
    # Binding names are injected from the workflow env block (Telegram pattern),
    # so the live job references them by env placeholder, never by inline value.
    for placeholder in (
        "${GOOGLE_OAUTH_CLIENT_ID_BINDING}",
        "${GOOGLE_OAUTH_CLIENT_SECRET_BINDING}",
        "${GOOGLE_OAUTH_REFRESH_TOKEN_BINDING}",
        "${CALENDAR_ALLOWLIST_BINDING}",
    ):
        assert placeholder in text
    assert "ENGINE_CONNECTOR_GRANTS" in text
    # Type is classified, never the value.
    assert 'return f"PRESENT:{kind}"' in text
    assert "SECRET_VALUE_OUTPUT=0" in text
    assert "add-mask::" in text


def test_d1_is_select_only() -> None:
    """D. canonical Calendar D1 grant read is SELECT-only."""
    text = grant_read_text()
    assert text.count("SELECT") >= 1
    upper = text.upper()
    for token in FORBIDDEN_MUTATION_SQL:
        assert token.upper() not in upper, f"mutation SQL present: {token}"


def test_canonical_calendar_identity_pinned() -> None:
    env = workflow_document()["env"]
    assert env["CALENDAR_APP_ID"] == APP_ID
    assert env["CALENDAR_AGENT_ID"] == AGENT_ID
    assert env["CALENDAR_CONNECTOR_ID"] == CONNECTOR_ID
    assert env["GOOGLE_OAUTH_CLIENT_ID_BINDING"] == "ENGINE_GOOGLE_OAUTH_CLIENT_ID"
    assert env["GOOGLE_OAUTH_CLIENT_SECRET_BINDING"] == "ENGINE_GOOGLE_OAUTH_CLIENT_SECRET"
    assert env["GOOGLE_OAUTH_REFRESH_TOKEN_BINDING"] == "ENGINE_GOOGLE_OAUTH_REFRESH_TOKEN"
    assert env["CALENDAR_ALLOWLIST_BINDING"] == "ENGINE_CALENDAR_ALLOWED_CALENDARS"


def test_grant_query_filters_canonical_identity() -> None:
    text = grant_read_text()
    assert "WHERE app_id = ? AND connector_id = ?" in text
    assert "FROM padiem_engine_connector_grants" in text
    assert "canonical_agent_id = ?" in text


def test_grant_state_vocabulary_pinned() -> None:
    text = grant_read_text()
    assert "CALENDAR_GRANT_STATE=ABSENT_ZERO" in text
    assert "CALENDAR_GRANT_STATE=EXACT_ACTIVE_READ" in text
    assert "CALENDAR_GRANT_STATE=NONCANONICAL" in text
    assert "stop before mutation" in text


def test_calendar_id_never_emitted() -> None:
    """7. the allowlist value itself must never be printed."""
    text = live_job_text()
    assert "RAW_CALENDAR_ID_OUTPUT=0" in text
    # The allowlist is classified as PRESENT/ABSENT only.
    assert "CALENDAR_ALLOWLIST_SERVED_BINDING=" in text
    assert "${CALENDAR_ALLOWLIST_BINDING}" in text
    # No echo/env export of the allowlist value.
    assert "CALENDAR_ALLOWED_CALENDARS=${" not in text


def test_empty_allowlist_needs_configuration() -> None:
    text = live_job_text()
    assert "CALENDAR_RUNTIME_AUTHORITY=NEEDS_ALLOWLIST_CONFIGURATION" in text
    assert "CALENDAR_RUNTIME_AUTHORITY=PRESENT_NAME_TYPE_ONLY" in text


def test_oauth_scope_never_inferred_from_secret_presence() -> None:
    """6. the central invariant: secret presence does not prove scope grant."""
    text = live_job_text()
    assert "SECRET_PRESENT != CALENDAR_SCOPE_GRANTED" in text
    assert "CALENDAR_OAUTH_SCOPE_STATUS=UNVERIFIED_WITHOUT_PROVIDER" in text
    # No provider token exchange / introspection anywhere in the live job.
    assert "oauth2.googleapis.com/token" not in text
    assert "www.googleapis.com/calendar" not in text


def test_no_provider_calls_anywhere() -> None:
    text = workflow_text()
    assert "CALENDAR_PROVIDER_CALLS=0" in text
    assert "PROVIDER_CREDENTIAL_OUTPUT=0" in text
    # The only external host is the Cloudflare API for served-version reads.
    assert "googleapis.com" not in text.split("jobs:", 1)[1].replace(PROVIDER_READ_SCOPE, "")


def test_write_locks_pinned() -> None:
    text = workflow_text()
    for marker in (
        "CALENDAR_CREATE=0",
        "CALENDAR_UPDATE=0",
        "CALENDAR_DELETE=0",
        "CALENDAR_RESPOND=0",
        "CALENDAR_WRITE=0",
        "GOOGLE_OAUTH_MUTATION=0",
    ):
        assert marker in text


def test_pull_request_has_no_production_environment_access() -> None:
    """4. pull_request runs source-contract validation only."""
    job = live_job()
    condition = job["if"]
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "pull_request" not in condition
    assert job["environment"] == "production"
    # Confirmation phrase gates any dispatch.
    assert CONFIRMATION_PHRASE in workflow_text()


def test_production_readonly_requires_explicit_dispatch_only() -> None:
    """The production environment job must NEVER auto-run on main push.

    Activation order: SOURCE MERGE -> CENTRAL post-merge verify -> explicit
    CENTRAL authority -> workflow_dispatch -> Production readonly preflight.
    A merge-triggered automatic Production read would skip the CENTRAL
    post-merge live-read approval step, so push must never qualify.
    """
    job = live_job()
    condition = job["if"]
    assert "push" not in condition, "production-readonly must not be reachable by push"
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert CONFIRMATION_PHRASE in condition
    assert job["environment"] == "production"
    assert "PRODUCTION_READONLY_AUTO_ON_MAIN_PUSH=NO" in workflow_text()
    assert "PRODUCTION_READONLY_DISPATCH_ONLY=YES" in workflow_text()


def test_top_level_push_trigger_is_source_contract_only() -> None:
    """The top-level push trigger may remain for source-contract checks only."""
    triggers = workflow_document()[True] if True in workflow_document() else workflow_document()["on"]
    assert "push" in triggers
    assert triggers["push"]["branches"] == ["main"]
    # Only the workflow file itself is wired to push; the production job is
    # still unreachable from push by its own condition.
    assert ".github/workflows/b54-calendar-production-readiness-preflight.yml" in triggers["push"]["paths"]
    assert "push" not in live_job()["if"]


def test_test_file_is_pr_trigger_coupled() -> None:
    """4. the new authority contract test must trigger this workflow."""
    triggers = workflow_document()[True] if True in workflow_document() else workflow_document()["on"]
    paths = triggers["pull_request"]["paths"]
    assert TEST_FILE_TRIGGER_PATH in paths
    assert ".github/workflows/b54-calendar-production-readiness-preflight.yml" in paths


def test_source_contract_validates_shared_source() -> None:
    text = source_contract_text()
    for marker in (
        'CALENDAR_CONNECTOR_ID = "connector:google:calendar@1"',
        'CALENDAR_READONLY_AUTH_SCOPE = "calendar.readonly"',
        "CALENDAR_WRITE_TOOLS_PRESENT = False",
        "async def load_calendar_grants",
        'CALENDAR_REFERENCE_APP_ID = "b54-padiem-claw-calendar"',
        'CALENDAR_AGENT_ID = "agent:padiem:claw_calendar_reader@1"',
        "def _calendar_port_for_env",
    ):
        assert marker in text


def test_source_contract_forbids_mutation_sql() -> None:
    text = source_contract_text()
    for token in FORBIDDEN_MUTATION_SQL:
        # The guard builds tokens by concatenation so the literal never appears.
        assert token not in text


def test_required_invariants_all_present() -> None:
    text = workflow_text()
    for marker in REQUIRED_INVARIANTS:
        assert marker in text, f"missing invariant: {marker}"


def test_grant_seed_not_modified_by_this_slice() -> None:
    """10. grant seeding is out of scope; this slice never seeds."""
    text = workflow_text()
    assert "CALENDAR_GRANT_SEED=0" in text
    assert "connector_grant_seed.py" not in text


@pytest.mark.parametrize("token", FORBIDDEN_MUTATION_SQL)
def test_no_mutation_sql_in_live_job(token: str) -> None:
    assert token.upper() not in live_job_text().upper()
