"""#5573 PR-9: one click, no code - the install file binds the PC to the account.

The Owner's decision is that a logged-in customer clicks once, runs what they
downloaded, and the PC is theirs: nothing to read off the screen, nothing to
type on the PC. So the file the click hands out carries the account's derived
tag (never the code it came from), names the deployment's own agent download,
and tells the PC to report its fixed drives next to that tag - which is how the
link arrives already covering the whole drives instead of starting empty.

These tests run against real sqlite with migration 072 applied, because the
properties that matter are database properties: one click mints one code, the
tag claims it, and the grant the PC named for itself is what the lane reads.
"""
from __future__ import annotations
from pathlib import Path
import re
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))

import test_5573_pc_device_pairing as pairing            # noqa: E402
import test_5015_pc_read_dispatch as lane                # noqa: E402

from app.pc_device_pairing_routes import (                # noqa: E402
    PC_PAIRING_INSTALL_FILE_PATH,
    PC_PAIRING_INSTALL_FILENAME,
    render_install_script,
)
from app.pc_device_pairing_store import (                # noqa: E402
    PAIRING_CODE_ALPHABET,
    PAIRING_CODE_CHARS,
    PcPairingError,
    drives_from_agent_name,
)

from datetime import timedelta                            # noqa: E402

NODE = "node/meshdomain/mesh-beta-01"
AGENT_URL = "https://mesh.example.padiem.net/meshagents?id=4&meshid=c9yfFkUpi38"
RUN = pairing.run

#: The exact shape of an issued code. Its presence in a downloaded file would
#: mean the proof left the server, so this is searched for - and must never be
#: found - instead of comparing against one known value.
CODE_SHAPE = re.compile(
    r"\b[" + re.escape(PAIRING_CODE_ALPHABET) + "]{" + str(PAIRING_CODE_CHARS) + r"}\b"
)


def _configured_app(store_value):
    app = pairing.app_with(store_value)
    app.state.pc_pairing_install_url = AGENT_URL
    return app


def _download(app):
    async def once():
        async with pairing.client(app) as session:
            return await session.post(PC_PAIRING_INSTALL_FILE_PATH, json={})
    return RUN(once())


# -- 1. the click hands out a file, and the code stays on the server ---------

def test_the_click_downloads_the_tag_and_never_the_code() -> None:
    store = pairing.store()
    response = _download(_configured_app(store))

    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{PC_PAIRING_INSTALL_FILENAME}"'
    )
    assert response.headers["content-type"].startswith("text/plain")
    # Windows PowerShell 5.1 reads a byte-order-less file in the machine's own
    # code page, which is how Korean prose turns into garbage on the PC.
    assert response.content.startswith(b"\xef\xbb\xbf")
    text = response.text
    assert CODE_SHAPE.search(text) is None, text
    # One click is one code, minted server-side and never returned.
    assert len(RUN(store.list_codes(user_id=pairing.OWNER, now=pairing._now()))) == 1
    assert AGENT_URL in text
    # The tag is in the file as the name the agent will report, and the PC's own
    # drives ride next to it - that is the whole one-click contract.
    assert "$PairingTag = 'pd-" in text, text
    assert "--agentName" in text, text
    assert "Get-PSDrive" in text, text


def test_an_unconfigured_deployment_has_no_file_to_hand_out() -> None:
    """Nothing is guessed: no reviewed download link means no install file.

    The refusal is the 준비 중 sentence the card already knows how to say, and it
    names no host - the request never carries one.
    """
    store = pairing.store()
    app = pairing.app_with(store)                 # no pc_pairing_install_url set
    response = _download(app)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "pc_pairing_install_url_missing"
    assert store.db.conn.execute("SELECT COUNT(*) FROM pc_pairing_codes").fetchone()[0] == 0

    configured = _configured_app(store)

    async def no_session():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=configured), base_url=pairing.ORIGIN,
        ) as anonymous:
            return await anonymous.post(PC_PAIRING_INSTALL_FILE_PATH, json={})

    assert RUN(no_session()).status_code == 401


def test_a_value_that_cannot_be_written_safely_is_refused_not_improvised() -> None:
    """The file is generated text a PC executes, so its two values are walls.

    A line break is refused outright - it would end the quoted line and start
    whatever came next. A quote is not a breakout, it is the character
    PowerShell doubles inside a single-quoted literal, and the value that reaches
    the PC is the value that was configured.
    """
    assert render_install_script(
        install_tag="pd-1234abcd", agent_url="https://m.example/x.exe\nWrite-Host owned",
    ) is None
    assert render_install_script(
        install_tag="pd-1234abcd", agent_url="https://m.example/x.exe a",
    ) is None
    assert render_install_script(
        install_tag="pd 1234 abcd", agent_url=AGENT_URL,
    ) is None
    assert render_install_script(
        install_tag="'; Set-Location C:\\", agent_url=AGENT_URL,
    ) is None

    quoted = render_install_script(
        install_tag="pd-1234abcd", agent_url="https://m.example/o'brie.exe",
    )
    assert quoted is not None
    assert "$AgentInstallerUrl = 'https://m.example/o''brie.exe'" in quoted


# -- 2. the drives the file reports are the drives the link grants -----------

def test_the_observed_name_seeds_the_whole_drives_the_pc_named() -> None:
    store = pairing.store()
    issued = RUN(store.issue_code(
        user_id=lane.OWNER, issued_at=pairing._now() - timedelta(minutes=1),
    ))
    tag = issued["install_tag"]

    link = RUN(store.complete_claim_from_observation(
        agent_name=f"{tag} [C D E]", mesh_node_id=NODE, now=pairing._now(),
    ))

    assert link["state"] == "active"
    assert [root["path"] for root in link["roots"]] == ["C:", "D:", "E:"]
    assert [root["label"] for root in link["roots"]] == ["C:", "D:", "E:"]
    # A second beat for the same tag is not a second claim, and it must not be a
    # way to widen what the first one granted.
    with pytest.raises(PcPairingError):
        RUN(store.complete_claim_from_observation(
            agent_name=f"{tag} [C D E F]", mesh_node_id=NODE, now=pairing._now(),
        ))


def test_a_name_that_says_nothing_about_drives_grants_nothing() -> None:
    store = pairing.store()
    issued = RUN(store.issue_code(user_id=lane.OWNER, issued_at=pairing._now()))
    tag = issued["install_tag"]

    link = RUN(store.complete_claim_from_observation(
        agent_name=tag, mesh_node_id=NODE, now=pairing._now(),
    ))
    assert link["roots"] == []

    # Free text is read narrowly on purpose: a folder smuggled into the bracket
    # group, a second group, or a name that only looks like a list are all no
    # report at all, never a guess about what the PC may be read from.
    for unreadable in (
        f"{tag} [C:/Users/me/견적]",
        f"{tag} [C] [D]",
        f"{tag} [Beta]",
        f"{tag} C D",
    ):
        assert drives_from_agent_name(unreadable) == [], unreadable
    assert drives_from_agent_name(f"{tag} [c d]") == ["C:", "D:"]
