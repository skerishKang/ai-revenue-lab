from __future__ import annotations

from _support.conversation_export_contract import (
    COLLECT_TOKENS,
    DOWNLOAD_TOKENS,
    EXPORTABLE_TOKENS,
    LIFECYCLE_TOKENS,
    STATE_TOKENS,
    facts,
)


def test_export_uses_lifecycle_not_composer_disabled() -> None:
    result = facts()
    assert set(LIFECYCLE_TOKENS[:3]).issubset(result["lifecycle_present"])
    # Old approach must not be present.
    assert result["legacy_present"] == ()


def test_export_skips_typing_error_and_incomplete_via_lifecycle() -> None:
    result = facts()
    assert set(EXPORTABLE_TOKENS).issubset(result["exportable_present"])
    # hasIncompleteAssistant and hasSettledAssistant must exist.
    assert set(LIFECYCLE_TOKENS[4:6]).issubset(result["lifecycle_present"])
    assert set(LIFECYCLE_TOKENS[6:8]).issubset(result["lifecycle_present"])


def test_export_collects_only_settled_with_pending_user() -> None:
    result = facts()
    assert set(COLLECT_TOKENS).issubset(result["collect_present"])


def test_export_state_is_fail_closed_on_incomplete() -> None:
    result = facts()
    assert set(STATE_TOKENS).issubset(result["state_present"])


def test_export_download_is_fail_closed_and_requires_completed() -> None:
    result = facts()
    assert set(DOWNLOAD_TOKENS).issubset(result["download_present"])


def test_export_excludes_typed_error_via_skip_selector() -> None:
    result = facts()
    assert set(LIFECYCLE_TOKENS[8:12]).issubset(result["lifecycle_present"])
