"""#6460 step 2 — the one-shot typed-text store behind the queue door.

Values never touch the queue database: this store keeps them in the claiming
process, hands each one out exactly once, and forgets it. These tests use no
network and no PC.
"""

from __future__ import annotations

import asyncio

import pytest

from desktop_text_store import (
    DesktopTextStore, DesktopTextStoreError, MAX_TEXT_CHARS, text_marker,
)


def _store(**kwargs):
    return DesktopTextStore(**kwargs)


def test_deposit_then_take_exactly_once():
    store = _store()
    asyncio.run(store.deposit_desktop_text(ref="a" * 32, text="안녕하세요 🙂"))
    assert asyncio.run(store.take_desktop_text(ref="a" * 32)) == "안녕하세요 🙂"
    assert asyncio.run(store.take_desktop_text(ref="a" * 32)) is None


def test_an_expired_value_is_gone(monkeypatch):
    store = _store(ttl_seconds=1)
    asyncio.run(store.deposit_desktop_text(ref="b" * 32, text="x"))
    later = 10**9
    monkeypatch.setattr("desktop_text_store.time.monotonic", lambda: later)
    assert asyncio.run(store.take_desktop_text(ref="b" * 32)) is None


@pytest.mark.parametrize("ref", ["", "A" * 32, "a" * 31, "a" * 33, "z" * 32, None, 7])
def test_a_malformed_reference_is_refused(ref):
    store = _store()
    with pytest.raises(DesktopTextStoreError):
        asyncio.run(store.deposit_desktop_text(ref=ref, text="x"))
    assert asyncio.run(store.take_desktop_text(ref=ref)) is None


@pytest.mark.parametrize("text", ["", None, b"bytes", "a" * (MAX_TEXT_CHARS + 1),
                                  "nul\x00here", "cr\rhere"])
def test_an_unusable_value_is_refused(text):
    store = _store()
    with pytest.raises(DesktopTextStoreError):
        asyncio.run(store.deposit_desktop_text(ref="c" * 32, text=text))


def test_the_marker_says_enough_for_an_audit_and_nothing_more():
    marker = text_marker("비밀 문장")
    length, digest = marker.split(":")
    assert length == str(len("비밀 문장")) and len(digest) == 8
    assert "비밀" not in marker


def test_the_queue_door_answers_the_two_names_from_the_store():
    import service

    resolvers = service.store_resolvers()
    assert "deposit_desktop_text" in resolvers
    assert "take_desktop_text" in resolvers
    state = type("State", (), {"desktop_text_store": _store()})()
    assert resolvers["deposit_desktop_text"](state) is state.desktop_text_store
    assert resolvers["take_desktop_text"](state) is state.desktop_text_store
