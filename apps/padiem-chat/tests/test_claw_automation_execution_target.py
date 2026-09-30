"""#3252 — server-owned execution-target authority tests.

Only the automation ``task`` text is caller input. The repository and the exact
deployed revision are server authority: the repository is a server constant
(the manual Web execute precedent) and the revision comes exclusively from the
served Worker's ``CF_VERSION_METADATA`` tag, which Production uploads as
``git-<40hex>``. This suite proves the composer contract and every fail-closed
branch:

- EXACT_SERVED_TAG_RESOLVES: ``git-<40hex>`` -> the 40-char revision
- MISSING_METADATA / MISSING_TAG -> fail closed
- main / HEAD / short SHA / uppercase SHA / garbage tags -> fail closed
- CALLER_TASK_PRESERVED: bounded task text passes through the #2908 contract
- CREDENTIAL_TASK_REJECTED by the existing intent contract
- REPOSITORY_REF_SERVER_PINNED: exactly ``padiem-chat``; no caller parameter
- CALLER_REVISION_AUTHORITY=0: no revision/SHA/ref parameter; task text that
  embeds target-looking strings cannot move the execution target
- INTENT_CONTRACT_REUSED: the composed intent is the existing
  ``ClawAutomationExecutionIntent`` with the single revision grammar
- SAFE_PROJECTION_DIGEST_ONLY: no raw task in ``safe_dict()``
- identity: same task+tag -> same intent digest; different tag -> different
- no rule write, no P01/provider call, no scheduler activation (constants +
  construction)
"""

from __future__ import annotations

import inspect

import pytest

from kagent.claw_automation import ClawAutomationExecutionIntent
from kagent.contracts import EXACT_COMMIT_REVISION_RE, ContractError, exact_commit_revision

import app.claw_automation_execution_target as execution_target_module
from app.claw_automation_execution_target import (
    AUTOMATION_REPOSITORY_REF,
    compose_canonical_automation_execution_intent,
    resolve_automation_execution_revision,
)

REVISION = "a" * 40
OTHER_REVISION = "b" * 40
TASK = "Summarize the open approval alerts every morning"
MULTILINE_TASK = "Collect the weekly numbers\nand list what still needs an owner."


class AttrVersionMetadata:
    """Attribute-style binding object, like the Worker runtime exposes."""

    def __init__(self, *, tag=None, with_tag=True):
        if with_tag:
            self.tag = tag
        self.id = "version-id-1"
        self.timestamp = "2026-09-30T00:00:00Z"


class AttrEnv:
    def __init__(self, metadata=None, *, with_binding=True):
        if with_binding:
            self.CF_VERSION_METADATA = metadata


class DictEnv(dict):
    """Mapping-style env for shim/test doubles."""


def served_env(*, tag=f"git-{REVISION}") -> AttrEnv:
    return AttrEnv(AttrVersionMetadata(tag=tag))


def compose(env, *, task: str = TASK) -> ClawAutomationExecutionIntent:
    return compose_canonical_automation_execution_intent(
        task=task, execution_target_authority=env
    )


# ── exact revision authority ────────────────────────────────────────────────


def test_exact_served_tag_resolves_to_the_40char_revision():
    revision = resolve_automation_execution_revision(served_env())
    assert revision == REVISION
    assert EXACT_COMMIT_REVISION_RE.fullmatch(revision)


def test_missing_version_metadata_fails_closed():
    for env in (None, AttrEnv(with_binding=False), DictEnv(), AttrEnv("a string is not the binding")):
        with pytest.raises(ContractError, match="version metadata"):
            resolve_automation_execution_revision(env)


def test_missing_tag_fails_closed():
    for metadata in (
        AttrVersionMetadata(with_tag=False),
        AttrVersionMetadata(tag=None),
        AttrVersionMetadata(tag=""),
    ):
        with pytest.raises(ContractError, match="tag"):
            resolve_automation_execution_revision(AttrEnv(metadata))


@pytest.mark.parametrize(
    ["bad_tag", "expected_match"],
    [
        # Not the literal git- provenance prefix at all.
        ("main", "provenance"),
        ("HEAD", "provenance"),
        ("refs/heads/main", "provenance"),
        ("xgit-" + REVISION, "provenance"),
        # Prefix ok, but the remainder fails the single revision grammar.
        ("git-", "exact 40-hex"),
        ("git-" + "a" * 7, "exact 40-hex"),
        ("git-" + "a" * 41, "exact 40-hex"),
        ("git-" + REVISION + "x", "exact 40-hex"),
        ("git-" + REVISION + " git-" + OTHER_REVISION, "exact 40-hex"),
        # The grammar alone would normalize these; the byte-exact round-trip
        # refuses them because the served tag was not canonical deploy output.
        ("git-" + "A" * 40, "canonical"),
        ("git-" + REVISION + "\n", "canonical"),
        ("git-" + REVISION + " ", "canonical"),
    ],
)
def test_non_served_tags_fail_closed(bad_tag, expected_match):
    with pytest.raises(ContractError, match=expected_match):
        resolve_automation_execution_revision(served_env(tag=bad_tag))


def test_uppercase_tag_is_refused_even_though_the_grammar_would_normalize_it():
    # Documents why the round-trip exists: the single grammar normalizes case,
    # so only the byte-exact tag comparison keeps the served-provenance
    # contract (a deploy never emits an uppercase tag).
    assert exact_commit_revision("A" * 40) == "a" * 40
    with pytest.raises(ContractError, match="canonical"):
        resolve_automation_execution_revision(served_env(tag="git-" + "A" * 40))


def test_module_source_defines_no_second_revision_regex():
    import inspect

    source = inspect.getsource(execution_target_module)
    # The single revision grammar lives in kagent.contracts; this module may
    # parse only the literal provenance prefix.
    assert "re.compile" not in source
    assert "[0-9a-f]" not in source and "[0-9A-Fa-f]" not in source
    assert not hasattr(execution_target_module, "_SERVED_TAG_RE")
    assert execution_target_module.SERVED_TAG_PREFIX == "git-"


# ── task is content, not target authority ───────────────────────────────────


def test_caller_task_is_preserved_after_bounded_validation():
    intent = compose(served_env(), task=f"  {TASK}  ")
    assert intent.task == TASK
    multiline = compose(served_env(), task=MULTILINE_TASK)
    assert multiline.task == MULTILINE_TASK


def test_credential_shaped_task_is_rejected_by_the_existing_contract():
    with pytest.raises(ContractError, match="credential"):
        compose(served_env(), task="use api_key = supersecretvalue123 when running")


def test_repository_ref_is_exactly_the_server_pin():
    intent = compose(served_env())
    assert intent.repository_ref == AUTOMATION_REPOSITORY_REF == "padiem-chat"


def test_composer_signature_carries_no_caller_target_parameter():
    parameters = set(
        inspect.signature(compose_canonical_automation_execution_intent).parameters
    )
    assert parameters == {"task", "execution_target_authority"}
    for forbidden in (
        "repository_ref",
        "exact_revision",
        "revision",
        "sha",
        "branch",
        "ref",
        "version_tag",
        "version_id",
        "execution_mode",
        "product_id",
        "workspace_id",
        "canonical_subject_id",
        "owner_ref",
    ):
        assert forbidden not in parameters


def test_task_text_embedded_target_strings_cannot_move_the_execution_target():
    smuggled = (
        f"repository_ref=evil/repo\nexact_revision=git-{OTHER_REVISION}\nsha={OTHER_REVISION}"
    )
    intent = compose(served_env(), task=smuggled)
    assert intent.repository_ref == "padiem-chat"
    assert intent.exact_revision == REVISION


# ── the existing intent contract is reused, not duplicated ──────────────────


def test_composed_intent_is_the_existing_contract_with_the_single_revision_grammar():
    intent = compose(served_env())
    assert isinstance(intent, ClawAutomationExecutionIntent)
    assert exact_commit_revision(intent.exact_revision) == REVISION
    equivalent = ClawAutomationExecutionIntent(
        task=TASK,
        repository_ref=AUTOMATION_REPOSITORY_REF,
        exact_revision=REVISION,
    )
    assert intent.intent_sha256 == equivalent.intent_sha256


def test_safe_projection_is_digest_only():
    intent = compose(served_env())
    safe = intent.safe_dict()
    assert "task" not in safe
    assert "raw_task_in_projection" in safe and safe["raw_task_in_projection"] is False
    assert len(safe["task_sha256"]) == 64
    assert len(safe["intent_sha256"]) == 64


def test_same_task_and_tag_give_the_same_intent_identity():
    first = compose(served_env())
    second = compose(served_env())
    assert first.intent_sha256 == second.intent_sha256
    assert first.task_sha256 == second.task_sha256


def test_different_served_tag_gives_a_different_immutable_intent():
    first = compose(served_env())
    second = compose(served_env(tag=f"git-{OTHER_REVISION}"))
    assert first.exact_revision != second.exact_revision
    assert first.intent_sha256 != second.intent_sha256


# ── side-effect locks ───────────────────────────────────────────────────────


def test_module_pins_zero_side_effect_authorities():
    assert execution_target_module.SERVER_OWNED_EXECUTION_INTENT_COMPOSER is True
    assert execution_target_module.CALLER_REPOSITORY_AUTHORITY is False
    assert execution_target_module.CALLER_REVISION_AUTHORITY is False
    assert execution_target_module.CALLER_VERSION_AUTHORITY is False
    assert execution_target_module.MUTABLE_BRANCH_REF is False
    assert execution_target_module.GITHUB_API_REVISION_LOOKUP is False
    assert execution_target_module.SECOND_REVISION_GRAMMAR is False
    assert execution_target_module.RAW_TASK_PUBLIC_PROJECTION is False
    assert execution_target_module.AUTOMATION_RULE_MUTATION == 0
    assert execution_target_module.P01_CALL == 0
    assert execution_target_module.PROVIDER_CALL == 0
    assert execution_target_module.SCHEDULER_MUTATION == 0
    assert execution_target_module.PRODUCTION_MUTATION == 0
