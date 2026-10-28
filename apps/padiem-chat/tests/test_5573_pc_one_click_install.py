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
import hashlib
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
    PC_PAIRING_INSTALL_EXE_FILENAME,
    PC_PAIRING_INSTALL_EXE_PATH,
    connect_exe_trailer,
    render_install_exe,
    render_install_script,
)
from app.pc_device_pairing_store import (                # noqa: E402
    PAIRING_CODE_ALPHABET,
    PAIRING_CODE_CHARS,
    PcPairingError,
    drives_from_agent_name,
)
from app.pc_pairing_connect_exe_asset import (            # noqa: E402
    PC_PAIRING_CONNECT_EXE_BYTES,
    PC_PAIRING_CONNECT_EXE_SHA256,
    connect_exe_bytes,
)

from datetime import timedelta                            # noqa: E402

#: apps/padiem-chat/tests is three directories below the repository root.
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts" / "pc_pairing" / "connect-exe"))

import win32_reproducible                                 # noqa: E402

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


# -- 3. the same connect as a program a person double-clicks -----------------

def test_the_shipped_program_is_the_bytes_the_build_recorded() -> None:
    """One artifact, pinned by its own digest, and it is what the route serves.

    The reviewed bytes travel inside a Python module because the Worker can only
    promise to serve what ships with the code; the digest is checked on every read
    so a hand-edited payload cannot reach a PC.
    """
    data = connect_exe_bytes()
    assert len(data) == PC_PAIRING_CONNECT_EXE_BYTES
    assert hashlib.sha256(data).hexdigest() == PC_PAIRING_CONNECT_EXE_SHA256
    assert data[:2] == b"MZ"
    assert (REPO / "docs" / "operations" / "PC_CONNECT_EXE_20261028.md").read_text(
        encoding="utf-8",
    ).count(f"CONNECT_EXE_SHA256={PC_PAIRING_CONNECT_EXE_SHA256}") == 1


def test_the_program_was_built_from_the_source_in_this_commit() -> None:
    """The seed the build recorded is the seed this source still produces.

    A digest alone only proves the payload matches its own pin - an artifact built
    from older code would be perfectly self-consistent and quietly wrong. The seed
    is the digest of the three files that decide the bytes, so a source edit that
    nobody rebuilt against is a failure here rather than a shipped surprise.
    """
    from app.pc_pairing_connect_exe_asset import PC_PAIRING_CONNECT_EXE_SEED

    inputs = ("PadiemPcConnect.cs", "app.manifest", "win32_reproducible.py")
    directory = REPO / "scripts" / "pc_pairing" / "connect-exe"
    joined = "".join(
        hashlib.sha256((directory / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in inputs
    )
    assert hashlib.sha256(joined.encode("utf-8")).hexdigest() == PC_PAIRING_CONNECT_EXE_SEED


def test_the_program_calls_itself_padiem_and_nothing_else() -> None:
    """The name in the elevation prompt is the brand, or the file is wrong.

    There is no code signature, so the version resource is the only place a name
    appears at all: Windows reads it back, which is why this checks the bytes rather
    than the build recipe.
    """
    strings = win32_reproducible.read_version_info(connect_exe_bytes())
    assert strings["CompanyName"] == "PADIEM"
    assert strings["ProductName"] == "PADIEM"
    assert strings["FileDescription"].startswith("PADIEM")
    assert strings["OriginalFilename"] == "padiem-pc-connect.exe"
    assert strings["FileVersion"] == "1.0.0.0"
    for forbidden in ("시지아이", "CGI", "cgi", "Alpha3"):
        assert forbidden not in " ".join(strings.values()), forbidden


def test_the_trailer_rides_behind_the_program_and_changes_no_byte_of_it() -> None:
    data = connect_exe_bytes()
    program = render_install_exe(install_tag="pd-1234abcd", agent_url=AGENT_URL)
    assert program is not None
    assert program[:len(data)] == data
    trailer = program[len(data):]
    assert trailer.decode("ascii") == (
        "PADIEMTRAILER:PADIEM-PC-CONNECT-1\r\n"
        f"PADIEMTAG:pd-1234abcd\r\nPADIEMURL:{AGENT_URL}\r\n"
    )
    # Nothing else travels: no chat origin the browser chose, no code, no account.
    assert b"PADIEMCHAT" not in trailer


def test_a_trailer_that_cannot_be_written_safely_is_refused_not_improvised() -> None:
    for unreadable in (
        {"install_tag": "pd-1234abcd", "agent_url": "http://m.example/x.exe"},
        {"install_tag": "pd-1234abcd", "agent_url": "https://m.example/x.exe\r\nPADIEMX:1"},
        {"install_tag": "pd-1234abcd", "agent_url": "https://evil@safe.example/x.exe"},
        {"install_tag": "pd 1234", "agent_url": AGENT_URL},
        {"install_tag": None, "agent_url": AGENT_URL},
        {"install_tag": "pd-1234abcd", "agent_url": None},
    ):
        assert connect_exe_trailer(**unreadable) is None, unreadable
        assert render_install_exe(**unreadable) is None, unreadable


def test_the_click_downloads_the_program_with_the_tag_and_never_the_code() -> None:
    store = pairing.store()
    app = _configured_app(store)

    async def once():
        async with pairing.client(app) as session:
            return await session.post(PC_PAIRING_INSTALL_EXE_PATH, json={})

    response = RUN(once())
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{PC_PAIRING_INSTALL_EXE_FILENAME}"'
    )
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert response.headers["cache-control"].startswith("no-store")
    data = connect_exe_bytes()
    assert response.content[:len(data)] == data
    trailer = response.content[len(data):].decode("ascii")
    assert CODE_SHAPE.search(trailer) is None, trailer
    assert re.search(r"PADIEMTAG:pd-[0-9a-f]{8}\r\n", trailer), trailer
    assert AGENT_URL in trailer
    assert len(RUN(store.list_codes(user_id=pairing.OWNER, now=pairing._now()))) == 1


def test_a_build_without_the_reviewed_program_refuses_and_mints_nothing() -> None:
    """503, not a substitute: the bytes a PC runs as a service are the reviewed ones.

    And the refusal comes before the code is minted, so a click that cannot end in a
    download leaves nothing behind that could be redeemed later.
    """
    from app import pc_device_pairing_routes as routes

    store = pairing.store()
    app = _configured_app(store)
    original = routes.connect_exe_bytes
    routes.connect_exe_bytes = lambda: (_ for _ in ()).throw(ValueError("pc_connect_exe_digest"))
    try:
        async def once():
            async with pairing.client(app) as session:
                return await session.post(PC_PAIRING_INSTALL_EXE_PATH, json={})

        response = RUN(once())
    finally:
        routes.connect_exe_bytes = original

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "pc_pairing_connect_exe_unavailable"
    assert store.db.conn.execute("SELECT COUNT(*) FROM pc_pairing_codes").fetchone()[0] == 0


@pytest.mark.skipif(sys.platform != "win32", reason="the artifact is a Windows program")
def test_the_program_reads_the_tag_out_of_its_own_file(tmp_path: Path) -> None:
    """The trailer and the reader are one contract, proved on the real bytes.

    Checked against the shipped artifact rather than a reimplementation: the name the
    program builds is the string the server parses, so a drive letter that arrives
    with its colon would silently grant nothing.
    """
    program = render_install_exe(install_tag="pd-1234abcd", agent_url=AGENT_URL)
    assert program is not None
    target = tmp_path / PC_PAIRING_INSTALL_EXE_FILENAME
    target.write_bytes(program)

    import subprocess

    done = subprocess.run([str(target), "--check"], capture_output=True, text=True,
                          encoding="utf-8", timeout=120, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    lines = dict(line.split("=", 1) for line in done.stdout.splitlines())
    assert lines["CONNECT_EXE_CHECK"] == "PASS"
    assert lines["CONNECT_EXE_CHECK_TAG"] == "pd-1234abcd"
    assert lines["CONNECT_EXE_CHECK_URL_PRESENT"] == "1"
    assert drives_from_agent_name(lines["CONNECT_EXE_CHECK_NAME"]) == [
        root + ":" for root in lines["CONNECT_EXE_CHECK_DRIVES"].split()
    ], lines


def test_the_agent_is_installed_from_a_folder_of_the_products_own() -> None:
    """Measured, not assumed: this build registers with ``-install``, from where it ran.

    The agent's own help offers both - ``-install`` "install the service from this
    location" and ``-fullinstall`` "copy agent into program files, install and
    launch" - and on the tagged Windows agent of 2026-10-28 ``-fullinstall`` exited 0
    and registered nothing while ``-install`` produced a running, auto-start service.
    Because ``-install`` keeps the *location* in the service record, the copy is this
    program's own job: an agent installed out of a temp folder is a service that
    cannot start after that folder is cleaned up.
    """
    source = (REPO / "scripts" / "pc_pairing" / "connect-exe" / "PadiemPcConnect.cs").read_text(
        encoding="utf-8")
    assert 'installerArguments = "-install --agentName=\\""' in source, source[:0]
    assert 'installerArguments = "-fullinstall' not in source
    assert 'const string DurableFolder = "PADIEM";' in source
    assert "SpecialFolder.ProgramFiles), DurableFolder, AgentFileName" in source
    # The downloaded copy is the thing deleted, never the installed one.
    assert 'File.Delete(temp)' in source


@pytest.mark.skipif(sys.platform != "win32", reason="the artifact is a Windows program")
def test_the_programs_plan_installs_from_the_durable_folder(tmp_path: Path) -> None:
    """--dry-run on the shipped bytes: the command it would run, with nothing run."""
    import subprocess

    program = render_install_exe(install_tag="pd-1234abcd", agent_url=AGENT_URL)
    target = tmp_path / PC_PAIRING_INSTALL_EXE_FILENAME
    target.write_bytes(program)
    done = subprocess.run([str(target), "--dry-run"], capture_output=True, text=True,
                          encoding="utf-8", timeout=120, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "-install --agentName=\"pd-1234abcd [" in done.stdout, done.stdout
    assert "MeshAgent.exe" in done.stdout and "PADIEM" in done.stdout
    assert "점검 실행" in done.stdout, done.stdout
