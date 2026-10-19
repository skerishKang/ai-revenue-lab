"""#3933: the composed Engine tool-binding resolver keeps READ and WRITE separate.

The production composition in ``worker_identity.py`` wraps the base resolver
twice: the #3580 READ binding first, then the #3933 independent WRITE binding.
This test reproduces that exact wrap order with synthetic (never Production)
scope resolvers and proves the two Hark WEB-FIRST app ids resolve to two
DISTINCT, INDEPENDENT Engine tool bindings.

Why this matters for the caller registry: the Engine authorizes the requested
``app_id`` against the caller registry BEFORE the tool service runs, then
resolves the binding BY that same app id. Registering ``padiem-web-xlsx-write-p01``
in the caller registry is what lets a WRITE request reach this resolver; this
test pins that the resolver then answers with the WRITE binding only — never the
READ binding, and never the other way round.

Synthetic fixtures only: no Production D1, no browser session, no real secret.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from app.web_xlsx_p01_tool_binding import (
    APP_ID as READ_APP,
    CANONICAL_TOOL as READ_CANONICAL,
    RUNTIME_TOOL as READ_RUNTIME,
    with_web_xlsx_p01_tool_binding,
)
from app.web_xlsx_quote_write_tool_binding import (
    APP_ID as WRITE_APP,
    CANONICAL_TOOL as WRITE_CANONICAL,
    RUNTIME_TOOL as WRITE_RUNTIME,
    with_web_quote_write_tool_binding,
)

FOREIGN_APP = "b54-padiem-claw"


def _composed(*, write_enabled: bool):
    """Reproduce worker_identity.py's exact wrap order over an empty base."""
    base = lambda _app_id: None  # noqa: E731 - synthetic empty base authority
    base.subject_for_app = lambda _app_id: "synthetic-subject"  # type: ignore[attr-defined]
    read_resolver = with_web_xlsx_p01_tool_binding(
        base, enabled=True, selection_resolver=lambda _ref: None,
    )
    return with_web_quote_write_tool_binding(
        read_resolver,
        enabled=write_enabled,
        scope_resolver=(lambda _ref: None) if write_enabled else None,
    )


def test_read_and_write_apps_resolve_to_distinct_independent_bindings() -> None:
    resolve = _composed(write_enabled=True)

    read_binding = resolve(READ_APP)
    write_binding = resolve(WRITE_APP)

    assert read_binding is not None
    assert write_binding is not None
    assert read_binding is not write_binding
    assert read_binding.app_id == READ_APP
    assert write_binding.app_id == WRITE_APP

    # Each app resolves to exactly its OWN canonical tool, never the other's.
    assert read_binding.registry.canonical_tool_ids == (READ_CANONICAL,)
    assert write_binding.registry.canonical_tool_ids == (WRITE_CANONICAL,)
    assert READ_CANONICAL not in write_binding.registry.canonical_tool_ids
    assert WRITE_CANONICAL not in read_binding.registry.canonical_tool_ids

    # The runtime tool ids are distinct too, so a continuation minted for one
    # app can never be resumed as the other.
    assert READ_RUNTIME != WRITE_RUNTIME

    # The WRITE side is a WRITE side effect requiring explicit user
    # confirmation; the READ side is a no-side-effect confirmation.
    write_spec = write_binding.registry.get(WRITE_CANONICAL).runtime_spec
    read_spec = read_binding.registry.get(READ_CANONICAL).runtime_spec
    assert write_spec.side_effect.value == "write"
    assert read_spec.side_effect.value == "none"
    assert write_spec.approval_policy.value == "user_confirmation"
    assert read_spec.approval_policy.value == "user_confirmation"
    assert write_spec.auth_scope != read_spec.auth_scope


def test_unregistered_app_still_fails_closed_after_write_registration() -> None:
    resolve = _composed(write_enabled=True)
    for foreign in (
        FOREIGN_APP,
        f"{WRITE_APP}-write",
        f"{WRITE_APP}2",
        f"{READ_APP}-write",
        "padiem-web-xlsx-write-p01-read",
        "",
    ):
        assert resolve(foreign) is None, foreign


def test_write_binding_is_absent_unless_explicitly_composed() -> None:
    # Default OFF: the same wrap order without the WRITE composition resolves
    # the WRITE app to nothing, while READ is unaffected.
    resolve = _composed(write_enabled=False)
    assert resolve(WRITE_APP) is None
    assert resolve(READ_APP) is not None
    assert resolve(READ_APP).registry.canonical_tool_ids == (READ_CANONICAL,)


def test_subject_for_app_is_preserved_through_both_wrappers() -> None:
    resolve = _composed(write_enabled=True)
    subject = getattr(resolve, "subject_for_app", None)
    assert callable(subject)
    assert subject(FOREIGN_APP) == "synthetic-subject"


if __name__ == "__main__":
    for _name, _value in sorted(globals().items()):
        if _name.startswith("test_") and callable(_value):
            _value()
    print("WEB_QUOTE_WRITE_APP_COMPOSITION=PASS")
