"""B3: the chat request no longer accepts a `country` key.

The key was validated at the trust boundary and then never read — the reader
(`declared_country`) had zero call sites — while the council client kept
sending it, so a country chosen in that UI was silently dropped on the chat
path. Both sides are removed here.

Country for project files is a different, live feature: `project_file_routes`
uses `COUNTRIES` for its filter and its storage metadata. That stays.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import request_contract
from app.request_contract import BrowserRequestError, _validate_payload_parts

ROOT = Path(__file__).resolve().parents[3]
COUNCIL = ROOT / "apps" / "padiem-council-apps" / "static" / "council-app.js"


def payload(**extra):
    base = {"messages": [{"role": "user", "content": "안녕하세요"}]}
    base.update(extra)
    return base


def test_the_chat_country_reader_is_gone() -> None:
    assert not hasattr(request_contract, "declared_country")
    assert not hasattr(request_contract, "DEFAULT_COUNTRY")


def test_the_chat_request_refuses_a_country_key() -> None:
    with pytest.raises(BrowserRequestError) as exc:
        _validate_payload_parts(payload(country="kr"))
    assert exc.value.code == "stale_chat_client"


def test_the_council_client_no_longer_sends_the_key() -> None:
    source = COUNCIL.read_text(encoding="utf-8")
    assert "payload.country" not in source
    # the country still shapes the prompt locally; only the request key is gone
    assert "countryInstruction(country)" in source


def test_project_files_keep_their_country_support() -> None:
    assert request_contract.COUNTRIES == frozenset({"kr", "us", "uk", "fr"})
