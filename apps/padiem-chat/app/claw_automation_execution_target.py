"""Server-owned execution-target authority for Web Automation (#3252).

A scheduled rule's ``execution_intent`` needs three values: the caller-authored
``task`` text, a ``repository_ref``, and the exact deployed revision. Only the
first is product input. The execution target — which repository and which
immutable commit — is server authority, so this module derives both from
server-owned facts and accepts no caller value for them:

```text
caller task text (bounded, credential-rejected by the #2908 intent contract)
repository_ref   = server constant "padiem-chat"   (manual Web execute precedent)
exact_revision   = served Worker version tag git-<40hex>  (CF_VERSION_METADATA)
  |
  v
existing ClawAutomationExecutionIntent          (the single validation authority)
```

Deliberately refused here:

* a browser/caller-supplied repository, revision, SHA, branch or version tag —
  the composer signature carries no such parameter;
* a mutable ref or GitHub API lookup — the served tag is the only revision
  source, and a malformed or missing one fails closed;
* a second commit-SHA grammar — the tag regex only captures the served
  provenance; the resulting revision is validated by the existing
  ``exact_commit_revision()`` predicate inside the intent contract;
* any write: no rule mutation, no scheduler activation, no deploy, no P01 or
  provider call. This slice composes authority; a later Create slice owns the
  HTTP surface and must reject caller attempts to smuggle target fields.
"""

from __future__ import annotations

import re
from typing import Any

from kagent.claw_automation import ClawAutomationExecutionIntent
from kagent.contracts import ContractError

__all__ = [
    "AUTOMATION_REPOSITORY_REF",
    "compose_canonical_automation_execution_intent",
    "resolve_automation_execution_revision",
]

# The existing Padiem Chat manual-execute target semantic. Not a GitHub
# slug/path: the manual Web execution precedent is the authority for this value.
AUTOMATION_REPOSITORY_REF = "padiem-chat"

_VERSION_METADATA_BINDING = "CF_VERSION_METADATA"
# The deploy uploads the Worker with ``--tag "git-${TARGET_SHA}"``; only that
# exact shape is server truth. Uppercase, short SHAs, branch names and any
# prefix/suffix garbage are refused — no fallback revision exists.
_SERVED_TAG_RE = re.compile(r"^git-([0-9a-f]{40})$")


def _version_metadata_binding(env: Any) -> Any:
    """Read the CF_VERSION_METADATA binding from the server runtime env.

    A Cloudflare Worker env exposes the binding as an attribute; a plain
    mapping (test doubles, local shims) may expose it via ``get``. Anything
    else is absence, and absence fails closed.
    """

    if env is None:
        return None
    metadata = getattr(env, _VERSION_METADATA_BINDING, None)
    if metadata is None:
        getter = getattr(env, "get", None)
        if callable(getter):
            try:
                metadata = getter(_VERSION_METADATA_BINDING)
            except Exception:
                return None
    return metadata


def _metadata_tag(metadata: Any) -> Any:
    tag = getattr(metadata, "tag", None)
    if tag is None and hasattr(metadata, "get"):
        getter = getattr(metadata, "get", None)
        if callable(getter):
            try:
                tag = getter("tag")
            except Exception:
                return None
    return tag


def resolve_automation_execution_revision(env: Any) -> str:
    """Return the exact served git revision, or fail closed (#3252).

    The only input is the server runtime env itself: no request value, no
    query/body/header, no branch ref, no network lookup and no fallback
    (``main``/``HEAD``/short SHA/wall clock/version id are all non-truth).
    The binding must exist, carry a ``tag`` of exactly ``git-<40 lowercase
    hex>``, and nothing else is accepted. The returned value is the captured
    40-character SHA; the tag text itself is provenance only.
    """

    metadata = _version_metadata_binding(env)
    if metadata is None or isinstance(metadata, (str, bytes)):
        raise ContractError("served version metadata binding is missing")
    tag = _metadata_tag(metadata)
    if not isinstance(tag, str) or not tag:
        raise ContractError("served version metadata carries no tag")
    match = _SERVED_TAG_RE.fullmatch(tag)
    if match is None:
        raise ContractError("served version tag is not an exact git-<40hex> revision")
    return match.group(1)


def compose_canonical_automation_execution_intent(
    *,
    task: str,
    execution_target_authority: Any,
) -> ClawAutomationExecutionIntent:
    """Compose the immutable execution intent from server-owned facts only.

    ``task`` is the caller-authored bounded natural-language instruction and is
    the ONLY caller input: the existing #2908 intent contract remains the
    validation authority for its bound, credential-material rejection and
    control characters. ``repository_ref`` is pinned to the server constant and
    ``exact_revision`` is resolved from the served Worker version tag; the
    signature carries no parameter a caller could use to supply either. The
    returned intent validates its own exact revision under the existing
    ``exact_commit_revision()`` predicate — no second revision grammar exists.
    """

    revision = resolve_automation_execution_revision(execution_target_authority)
    return ClawAutomationExecutionIntent(
        task=task,
        repository_ref=AUTOMATION_REPOSITORY_REF,
        exact_revision=revision,
    )


SERVER_OWNED_EXECUTION_INTENT_COMPOSER = True
REPOSITORY_REF_SERVER_PINNED = True
EXACT_REVISION_FROM_SERVED_VERSION_TAG = True
CALLER_REPOSITORY_AUTHORITY = False
CALLER_REVISION_AUTHORITY = False
CALLER_VERSION_AUTHORITY = False
MUTABLE_BRANCH_REF = False
GITHUB_API_REVISION_LOOKUP = False
SECOND_REVISION_GRAMMAR = False
SECOND_EXECUTION_TARGET_STORE = False
EXECUTION_TARGET_DB = False
RAW_TASK_PUBLIC_PROJECTION = False
AUTOMATION_RULE_MUTATION = 0
EXECUTION_INTENT_STORE = 0
P01_CALL = 0
PROVIDER_CALL = 0
SCHEDULER_MUTATION = 0
PRODUCTION_MUTATION = 0
