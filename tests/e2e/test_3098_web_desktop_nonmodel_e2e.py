"""#3098 LOCAL3 — the model-free Web ↔ Control Plane ↔ Desktop E2E gate matrix.

Every case composes the REAL product modules: the padiem-chat Claw app and its
history store, the canonical control-plane broker/pairing authority, and the
kagent Local Agent runtime host. The successor model is deliberately absent —
``MODEL_SELECTION=NO`` — so the loop must hold with ``MODEL_CALLS=0`` and
``LIVE_PROVIDER_CALL=0``.

Gate matrix covered here:

    HAPPY_PATH                    PASS  (receipt + real-Windows runtime modes)
    OFFLINE_DEVICE                FAIL_CLOSED
    REVOKED_DEVICE                FAIL_CLOSED
    WRONG_ACCOUNT                 FAIL_CLOSED
    WRONG_WORKSPACE               FAIL_CLOSED
    EXPIRED_TICKET                FAIL_CLOSED (+ truthful expired projection)
    REPLAYED_COMMAND              FAIL_CLOSED
    CAPABILITY_ESCALATION         FAIL_CLOSED
    MODEL_CALLS                   0     (socket-guarded loop)
    RAW_SECRET_PROJECTION         0
    CANCEL / TIMEOUT              PASS  (real Windows runtime, bounded tree kill)
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from datetime import timedelta

import pytest

from web_desktop_harness import (
    CREDENTIAL,
    DEVICE_ID,
    OTHER_SUBJECT,
    OTHER_WORKSPACE,
    OWNER_SUBJECT,
    ROOT_REF,
    SAMPLE_SHA256,
    SAMPLE_TEXT,
    SECRET_MARKER_ENV,
    SECRET_MARKER_VALUE,
    WORKSPACE,
    WebDesktopE2E,
)

from kagent.contracts import ContractError
from kagent.local_agent import LocalCommandRequest
from kagent.local_agent_permissions import (
    LocalCapability,
    LocalPermissionRequest,
    default_device_permission_profile,
)
from kagent.local_agent_runtime_host import ResidentHostState
from kagent.windows_local_executor import (
    DeterministicFakeWindowsExecutionAuthorizationPort,
    WindowsSubprocessLocalAgentRuntime,
    command_request_fingerprint,
)
from padiem_control_plane.contracts import ControlPlaneContractError

BROKER_REFUSALS = (ContractError, ControlPlaneContractError)
from kagent.windows_local_filesystem import (
    DeterministicWindowsFileAuthorityEvidencePort,
    LocalFileOperation,
    LocalFileRequest,
    P01LocalPermissionWindowsFileAuthorizationPort,
    WindowsFileAuthorityEvidence,
    WindowsSelectedRootFileRuntime,
    file_request_fingerprint,
    windows_file_tool_invocation,
)
from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
    tool_invocation_digest,
)


def _refusal_text(excinfo) -> str:
    """The canonical error code: .code on the control-plane error, else the message."""

    exc = excinfo.value
    code = getattr(exc, "code", "")
    return code if isinstance(code, str) and code else str(exc)


RAW_PROJECTION_FLAGS = ("raw_argv", "raw_stdout", "raw_stderr", "raw_device_credential", "p01_approval_payload")


@pytest.fixture()
def make_e2e(tmp_path):
    made: list[WebDesktopE2E] = []

    def _make(*, runtime_mode: str = "receipt") -> WebDesktopE2E:
        harness = WebDesktopE2E(tmp_path, runtime_mode=runtime_mode)
        made.append(harness)
        return harness

    yield _make
    for harness in made:
        harness.close()


@pytest.fixture()
def no_network(monkeypatch):
    """MODEL_CALLS=0 / LIVE_PROVIDER_CALL=0: no non-loopback egress at all.

    asyncio's event loop legitimately opens a loopback self-pipe, so the guard
    blocks every non-loopback connection and every name resolution rather than
    socket creation itself. Nothing on the composed path talks even to loopback.
    """

    import socket

    def _blocked(*args, **kwargs):
        raise AssertionError("network egress attempted: the loop must stay model- and provider-free")

    real_connect = socket.socket.connect

    def _guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) and address else None
        if isinstance(host, str) and host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address)
        raise AssertionError(f"non-loopback connection attempted: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)


def _pair_and_stage(
    harness: WebDesktopE2E,
    *,
    accounts: dict[str, str],
    run_id: str,
    command_id: str,
    workspace_id: str = WORKSPACE,
):
    """Web origin + pairing + one bounded work ticket, through the real edges."""

    conversation_id = harness.create_conversation_with_run(
        owner=accounts[OWNER_SUBJECT], run_id=run_id, workspace_id=workspace_id
    )
    challenge = harness.web_issue_pairing_challenge(
        account_ref=accounts[OWNER_SUBJECT], workspace_ref=WORKSPACE
    )
    binding = harness.pair_device(
        challenge_id=challenge["challenge"]["challenge_id"],
        pairing_code=challenge["pairing_code"],
    )
    request = harness.build_sample_read_request(run_id=run_id)
    harness.enqueue_ticket(command_id=command_id, request=request, binding_ref=binding.binding_ref)
    return conversation_id, binding, request


def _run_web_desktop_loop(harness: WebDesktopE2E, *, binding, bootstrap_session: str, host_session: str):
    channel, _session, online = harness.connect(binding, session_id=bootstrap_session)
    host = harness.host(channel, binding=online, session_id=host_session)
    host.start()
    assert host.state == ResidentHostState.ONLINE
    host.run_once()
    return host


# ---------------------------------------------------------------- happy path


@pytest.mark.parametrize("runtime_mode", ["receipt", "windows"])
def test_happy_path_returns_the_bounded_result_to_the_same_conversation(
    make_e2e, no_network, monkeypatch, runtime_mode
):
    if runtime_mode == "windows" and os.name != "nt":
        pytest.skip("real Windows desktop execution leg requires Windows")
    harness = make_e2e(runtime_mode=runtime_mode)
    accounts = harness.accounts()
    monkeypatch.setenv(SECRET_MARKER_ENV, SECRET_MARKER_VALUE)

    conversation_id, binding, request = _pair_and_stage(
        harness,
        accounts=accounts,
        run_id="run.3098.happy.1",
        command_id="command.3098.happy.1",
    )
    if runtime_mode == "windows":
        harness.prepare_windows_runtime(request)

    # Before the device comes online the same conversation sees an unusable device.
    paired_view = harness.web_get_local_access(
        owner_id=accounts[OWNER_SUBJECT], conversation_id=conversation_id
    )
    assert paired_view.status_code == 200, paired_view.text
    paired_projection = paired_view.json()["projection"]
    assert paired_projection["device"]["canonicalState"] == "paired_offline"
    assert paired_projection["device"]["usable"] is False

    _run_web_desktop_loop(
        harness,
        binding=binding,
        bootstrap_session="session.3098.happy.bootstrap",
        host_session="session.3098.happy.host",
    )

    # Canonical bounded order: poll → material → admission → acknowledge.
    for route in ("poll", "material", "admission", "acknowledge"):
        assert route in harness.audit, f"{route} never crossed the broker edge"
    assert harness.audit.index("admission") < harness.audit.index("acknowledge")

    # The canonical terminal fact: one acknowledged execution, no raw material.
    terminal = harness.terminal_result(run_id="run.3098.happy.1", account_ref=accounts[OWNER_SUBJECT])
    assert terminal["ok"] is True
    assert terminal["available"] is True
    assert terminal["command_identity"]["command_id"] == "command.3098.happy.1"
    assert terminal["command_result"]["termination"] == "exited"
    assert terminal["command_result"]["exit_code"] == 0

    # The same conversation now projects a usable, server-backed ONLINE device.
    online_view = harness.web_get_local_access(
        owner_id=accounts[OWNER_SUBJECT], conversation_id=conversation_id
    )
    assert online_view.status_code == 200, online_view.text
    device = online_view.json()["projection"]["device"]
    assert device["canonicalState"] == "online"
    assert device["state"] == "CONNECTED"
    assert device["usable"] is True
    assert device["revoked"] is False

    # The web route returns the bounded result into the originating conversation.
    response = harness.web_post_local_result(owner_id=accounts[OWNER_SUBJECT], run_id="run.3098.happy.1")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["projection"]["appended"] is True
    assert body["projection"]["status"] == "completed"
    assert body["projection"]["commandId"] == "command.3098.happy.1"
    for flag in RAW_PROJECTION_FLAGS:
        assert body["projection"][flag] is False

    messages = harness.conversation_messages(conversation_id)
    assert messages[-1]["role"] == "assistant"
    assert "command.3098.happy.1" in messages[-1]["content"]
    # raw execution output and secrets never reach the conversation
    assert "padiem-3098-receipt-output" not in messages[-1]["content"]
    assert SECRET_MARKER_VALUE not in response.text
    assert SECRET_MARKER_VALUE not in messages[-1]["content"]
    assert CREDENTIAL.decode() not in response.text

    # A second read of the same terminal fact appends nothing (exactly once).
    second = harness.web_post_local_result(owner_id=accounts[OWNER_SUBJECT], run_id="run.3098.happy.1")
    assert second.status_code == 200
    assert second.json()["projection"]["appended"] is False
    assert len(harness.conversation_messages(conversation_id)) == len(messages)


def test_the_real_windows_ticket_reads_the_exact_fixture_bytes(make_e2e, no_network, monkeypatch):
    """Windows: exit_code=0 proves the bounded read + content match + no secret leak."""

    if os.name != "nt":
        pytest.skip("real Windows desktop execution leg requires Windows")
    harness = make_e2e(runtime_mode="windows")
    accounts = harness.accounts()
    monkeypatch.setenv(SECRET_MARKER_ENV, SECRET_MARKER_VALUE)
    _conversation, binding, request = _pair_and_stage(
        harness,
        accounts=accounts,
        run_id="run.3098.winread.1",
        command_id="command.3098.winread.1",
    )
    harness.prepare_windows_runtime(request)
    _run_web_desktop_loop(
        harness,
        binding=binding,
        bootstrap_session="session.3098.winread.bootstrap",
        host_session="session.3098.winread.host",
    )
    terminal = harness.terminal_result(run_id="run.3098.winread.1", account_ref=accounts[OWNER_SUBJECT])
    # The child script asserts the exact fixture sha256 and the bounded
    # environment itself; exit 0 is only reachable if both held.
    assert terminal["command_result"]["termination"] == "exited"
    assert terminal["command_result"]["exit_code"] == 0


# ------------------------------------------------------------- fail-closed


def test_offline_device_fails_closed_without_fabricated_result(make_e2e, no_network):
    harness = make_e2e()
    accounts = harness.accounts()
    conversation_id, _binding, _request = _pair_and_stage(
        harness,
        accounts=accounts,
        run_id="run.3098.offline.1",
        command_id="command.3098.offline.1",
    )

    # paired but never connected: the web sees an unusable device
    view = harness.web_get_local_access(owner_id=accounts[OWNER_SUBJECT], conversation_id=conversation_id)
    assert view.status_code == 200
    device = view.json()["projection"]["device"]
    assert device["canonicalState"] == "paired_offline"
    assert device["usable"] is False

    # nothing executed: the ticket stays queued and unreachable
    assert harness.receipt_runtime.executed == []
    assert harness.snapshot_commands()[0].state.value == "queued"

    # no terminal fact exists, so the web route refuses rather than fabricating one
    response = harness.web_post_local_result(owner_id=accounts[OWNER_SUBJECT], run_id="run.3098.offline.1")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "local_runner_result_absent"
    assert harness.receipt_runtime.executed == []


def test_revoked_device_fails_closed_everywhere(make_e2e, no_network):
    harness = make_e2e()
    accounts = harness.accounts()
    _conversation, binding, _request = _pair_and_stage(
        harness,
        accounts=accounts,
        run_id="run.3098.revoke.1",
        command_id="command.3098.revoke.1",
    )
    harness.connect(binding, session_id="session.3098.revoke.bootstrap")

    harness.authority.revoke_binding(binding.binding_ref, now=harness.server_clock.now)

    # a new session is refused with the canonical code
    from kagent.local_agent_secure_channel import PinnedOutboundBrokerBinding

    channel = harness._channel(binding)
    with pytest.raises(BROKER_REFUSALS) as excinfo:
        channel.open_session(
            binding=binding,
            session_id="session.3098.revoke.after",
            now=harness.client_clock.now,
            ttl_seconds=900,
        )
    assert "device_binding_revoked" in _refusal_text(excinfo)

    # the web projection never promotes a revoked device
    view = harness.web_get_local_access(
        owner_id=accounts[OWNER_SUBJECT], conversation_id="conversation.3098.any"
    )
    assert view.status_code == 200
    device = view.json()["projection"]["device"]
    assert device["canonicalState"] == "revoked"
    assert device["usable"] is False
    assert device["revoked"] is True

    # and no result may be projected for the revoked device's account
    response = harness.web_post_local_result(owner_id=accounts[OWNER_SUBJECT], run_id="run.3098.revoke.1")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "local_runner_result_absent"
    assert harness.receipt_runtime.executed == []


def test_cross_account_substitution_fails_closed(make_e2e, no_network):
    harness = make_e2e()
    accounts = harness.accounts()
    owner = accounts[OWNER_SUBJECT]
    other = accounts[OTHER_SUBJECT]
    conversation_id, binding, _request = _pair_and_stage(
        harness,
        accounts=accounts,
        run_id="run.3098.acct.1",
        command_id="command.3098.acct.1",
    )
    _run_web_desktop_loop(
        harness,
        binding=binding,
        bootstrap_session="session.3098.acct.bootstrap",
        host_session="session.3098.acct.host",
    )

    # a session under another account is refused (binding scope is exact)
    with pytest.raises(BROKER_REFUSALS) as excinfo:
        harness.authority.open_session(
            session_id="session.3098.acct.foreign",
            binding_ref=binding.binding_ref,
            credential=CREDENTIAL,
            account_ref=other,
            workspace_ref=WORKSPACE,
            now=harness.server_clock.now,
        )
    assert "device_binding_scope_mismatch" in _refusal_text(excinfo)

    # the broker terminal read is owner-scoped: another account sees nothing
    foreign = harness.terminal_result(run_id="run.3098.acct.1", account_ref=other)
    assert foreign["ok"] is True
    assert foreign["available"] is False
    assert foreign["reason"] == "no_device_binding"

    # and the web route never discloses another owner's run: an identical
    # refusal for "absent" and "not yours" (404, never a 200 with foreign data)
    owner_run_under_other = harness.web_post_local_result(owner_id=other, run_id="run.3098.acct.1")
    assert owner_run_under_other.status_code == 404
    assert owner_run_under_other.json()["error"]["code"] == "local_runner_result_absent"

    # ...while the owner still gets the truthful result into the same conversation
    ok = harness.web_post_local_result(owner_id=owner, run_id="run.3098.acct.1")
    assert ok.status_code == 200
    assert ok.json()["projection"]["appended"] is True
    messages = harness.conversation_messages(conversation_id)
    assert messages[-1]["role"] == "assistant"


def test_cross_workspace_substitution_fails_closed(make_e2e, no_network):
    harness = make_e2e()
    accounts = harness.accounts()
    owner = accounts[OWNER_SUBJECT]
    _conversation, binding, _request = _pair_and_stage(
        harness,
        accounts=accounts,
        run_id="run.3098.ws.1",
        command_id="command.3098.ws.1",
    )
    harness.connect(binding, session_id="session.3098.ws.bootstrap")

    # a session claiming another workspace is refused
    with pytest.raises(BROKER_REFUSALS) as excinfo:
        harness.authority.open_session(
            session_id="session.3098.ws.foreign",
            binding_ref=binding.binding_ref,
            credential=CREDENTIAL,
            account_ref=owner,
            workspace_ref=OTHER_WORKSPACE,
            now=harness.server_clock.now,
        )
    assert "device_binding_scope_mismatch" in _refusal_text(excinfo)

    # the web result read cannot widen the run's own workspace either
    response = harness.web_post_local_result(
        owner_id=owner, run_id="run.3098.ws.1", workspace_id=OTHER_WORKSPACE
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "local_runner_result_workspace_mismatch"


def test_expired_ticket_fails_closed_and_reconciles_truthfully(make_e2e, no_network):
    harness = make_e2e()
    accounts = harness.accounts()
    owner = accounts[OWNER_SUBJECT]
    challenge = harness.web_issue_pairing_challenge(account_ref=owner, workspace_ref=WORKSPACE)
    binding = harness.pair_device(
        challenge_id=challenge["challenge"]["challenge_id"],
        pairing_code=challenge["pairing_code"],
    )

    # --- a QUEUED ticket that expires is never polled, admitted or executed ---
    queued_conversation = harness.create_conversation_with_run(
        owner=owner, run_id="run.3098.expire.queued.1"
    )
    request = harness.build_sample_read_request(run_id="run.3098.expire.queued.1")
    harness.enqueue_ticket(
        command_id="command.3098.expire.queued.1",
        request=request,
        binding_ref=binding.binding_ref,
        ttl_seconds=1,
    )
    harness.server_clock.advance(120)
    harness.client_clock.advance(120)
    channel, _session, online = harness.connect(
        binding, session_id="session.3098.expire.queued.bootstrap", freeze_clock=True
    )
    host = harness.host(channel, binding=online, session_id="session.3098.expire.queued.host")
    host.start()
    host.run_once()
    assert harness.receipt_runtime.executed == []  # the short ticket never ran

    response = harness.web_post_local_result(owner_id=owner, run_id="run.3098.expire.queued.1")
    assert response.status_code == 404  # no fabricated result for the expired ticket

    # --- an ADMITTED ticket that passes its deadline reconciles, never replays ---
    # One run carries exactly one command (the canonical correlation rule), so
    # the admitted-expiry phase uses its own run and conversation.
    admitted_conversation = harness.create_conversation_with_run(
        owner=owner, run_id="run.3098.expire.admitted.1"
    )
    admitted_request = harness.build_sample_read_request(
        run_id="run.3098.expire.admitted.1", request_id="request.3098.expire.admitted.1"
    )
    fingerprint = command_request_fingerprint(admitted_request)
    harness.enqueue_ticket(
        command_id="command.3098.expire.admitted.1",
        request=admitted_request,
        binding_ref=binding.binding_ref,
        ttl_seconds=300,
    )
    session = harness.authority.open_session(
        session_id="session.3098.expire.admitted.open",
        binding_ref=binding.binding_ref,
        credential=CREDENTIAL,
        account_ref=owner,
        workspace_ref=WORKSPACE,
        now=harness.server_clock.now,
    )
    admitted = harness.authority.admit_command(
        admission_ref="admission.3098.expire.1",
        evidence_ref="evidence.3098.expire.1",
        session_id=session.session_id,
        binding_ref=binding.binding_ref,
        credential=CREDENTIAL,
        command_id="command.3098.expire.admitted.1",
        request_fingerprint=fingerprint,
        request_id=admitted_request.request_id,
        now=harness.server_clock.now,
    )
    harness.server_clock.advance(600)
    harness.authority.reconcile_expired_command(
        session_id=session.session_id,
        binding_ref=binding.binding_ref,
        credential=CREDENTIAL,
        command_id="command.3098.expire.admitted.1",
        admission_ref=admitted.admission_ref,
        revision_ref=admitted.revision_ref,
        request_id=admitted_request.request_id,
        request_fingerprint=fingerprint,
        termination=None,
        exit_code=None,
        now=harness.server_clock.now,
    )
    assert harness.receipt_runtime.executed == []  # reconciliation never re-executes

    # the web projection reports the expiry truthfully: no termination, no exit code
    expired_view = harness.web_post_local_result(owner_id=owner, run_id="run.3098.expire.admitted.1")
    assert expired_view.status_code == 200, expired_view.text
    assert expired_view.json()["projection"]["appended"] is True
    assert expired_view.json()["projection"]["status"] == "expired"
    messages = harness.conversation_messages(admitted_conversation)
    assert "기한 만료" in messages[-1]["content"]
    assert "종료 코드" not in messages[-1]["content"]


def test_replayed_command_fails_closed(make_e2e, no_network):
    harness = make_e2e()
    accounts = harness.accounts()
    _conversation, binding, request = _pair_and_stage(
        harness,
        accounts=accounts,
        run_id="run.3098.replay.1",
        command_id="command.3098.replay.1",
    )
    session = harness.authority.open_session(
        session_id="session.3098.replay.open",
        binding_ref=binding.binding_ref,
        credential=CREDENTIAL,
        account_ref=accounts[OWNER_SUBJECT],
        workspace_ref=WORKSPACE,
        now=harness.server_clock.now,
    )
    fingerprint = command_request_fingerprint(request)
    first = harness.authority.admit_command(
        admission_ref="admission.3098.replay.1",
        evidence_ref="evidence.3098.replay.1",
        session_id=session.session_id,
        binding_ref=binding.binding_ref,
        credential=CREDENTIAL,
        command_id="command.3098.replay.1",
        request_fingerprint=fingerprint,
        request_id=request.request_id,
        now=harness.server_clock.now,
    )
    assert first.command_id == "command.3098.replay.1"

    # a second admission of the same command is a replay
    with pytest.raises(BROKER_REFUSALS) as excinfo:
        harness.authority.admit_command(
            admission_ref="admission.3098.replay.2",
            evidence_ref="evidence.3098.replay.2",
            session_id=session.session_id,
            binding_ref=binding.binding_ref,
            credential=CREDENTIAL,
            command_id="command.3098.replay.1",
            request_fingerprint=fingerprint,
            request_id=request.request_id,
            now=harness.server_clock.now,
        )
    assert "broker_command_replay" in _refusal_text(excinfo)

    # an exact enqueue retry is idempotent and mints nothing new
    retry = harness.authority.enqueue_command(
        command_id="command.3098.replay.1",
        binding_ref=binding.binding_ref,
        run_id=request.run_id,
        tool_request_ref=f"tool.command.3098.replay.1",
        request_fingerprint=fingerprint,
        now=harness.server_clock.now,
        ttl_seconds=300,
    )
    assert retry.command_id == "command.3098.replay.1"
    assert retry.sequence == first.sequence

    # the same command id with different material is refused, never overwritten
    with pytest.raises(BROKER_REFUSALS) as excinfo:
        harness.authority.enqueue_command(
            command_id="command.3098.replay.1",
            binding_ref=binding.binding_ref,
            run_id=request.run_id,
            tool_request_ref="tool.command.3098.replay.1",
            request_fingerprint="f" * 64,
            now=harness.server_clock.now,
            ttl_seconds=300,
        )
    assert "duplicate_broker_command" in _refusal_text(excinfo)


# ------------------------------------------------- capability escalation


def _file_evidence(harness: WebDesktopE2E, request: LocalFileRequest):
    fingerprint = file_request_fingerprint(request)
    invocation = windows_file_tool_invocation(request)
    now = harness.server_clock.now
    return WindowsFileAuthorityEvidence(
        evidence_ref=f"authority_evidence_file_{request.action_id}",
        request_fingerprint=fingerprint,
        permission_request=LocalPermissionRequest(
            action_id=f"permission_{request.action_id}",
            run_id=request.run_id,
            device_id=request.device_id,
            capability=request.capability,
            target_ref=fingerprint,
            root_ref=request.root_ref,
        ),
        approval_pause=ApprovalPause(
            pause_id=f"pause_{request.action_id}",
            run_id=request.run_id,
            agent_runtime_id="agent_3098_e2e",
            tool_id=invocation.tool_id,
            invocation_sha256=tool_invocation_digest(invocation),
            requirement=ApprovalRequirement.USER_CONFIRMATION,
            step_index=1,
            created_at=now - timedelta(seconds=30),
            expires_at=now + timedelta(minutes=10),
            approval_scope=(request.capability.value,),
        ),
        approval_decision=VerifiedApprovalDecision(
            decision_id=f"decision_{request.action_id}",
            pause_id=f"pause_{request.action_id}",
            outcome=ApprovalOutcome.APPROVED,
            authority_ref="p01_authority_3098_e2e",
            evidence_ref="p01_evidence_3098_e2e",
            decided_at=now - timedelta(seconds=10),
        ),
        local_policy_ref="local_policy_v1",
        expires_at=now + timedelta(minutes=5),
    )


def test_capability_escalation_fails_closed(tmp_path, make_e2e, no_network):
    """#1635 on the real local runtime: read is bounded, write/escape/shell refuse."""

    if os.name != "nt":
        pytest.skip("real Windows desktop execution leg requires Windows")
    harness = make_e2e()
    now = harness.server_clock.now

    # filesystem.read of the exact fixture file succeeds and is bounded
    read_request = LocalFileRequest(
        action_id="action.read.3098.1",
        run_id="run.3098.cap.1",
        device_id=DEVICE_ID,
        root_ref=ROOT_REF,
        operation=LocalFileOperation.READ,
        path_relative="sample.txt",
        requested_at=now,
    )
    read_port = P01LocalPermissionWindowsFileAuthorizationPort(
        permission_profile=default_device_permission_profile(device=harness.device),
        evidence_port=DeterministicWindowsFileAuthorityEvidencePort((_file_evidence(harness, read_request),)),
    )
    result = WindowsSelectedRootFileRuntime(
        device=harness.device, authorization_port=read_port
    ).perform(read_request, now=now)
    assert result.content.decode("utf-8") == SAMPLE_TEXT
    assert result.bytes_count == len(SAMPLE_TEXT.encode("utf-8"))

    # filesystem.write is a different capability: the read-only grant refuses it
    write_request = LocalFileRequest(
        action_id="action.write.3098.1",
        run_id="run.3098.cap.1",
        device_id=DEVICE_ID,
        root_ref=ROOT_REF,
        operation=LocalFileOperation.WRITE,
        path_relative="escalated.txt",
        requested_at=now,
        content=b"escalation",
    )
    with pytest.raises(BROKER_REFUSALS):
        read_port.authorize(request=write_request, now=now)
    assert not (harness.fixture_dir / "escalated.txt").exists()

    # path traversal is refused at the request boundary
    with pytest.raises(BROKER_REFUSALS):
        LocalFileRequest(
            action_id="action.traverse.3098.1",
            run_id="run.3098.cap.1",
            device_id=DEVICE_ID,
            root_ref=ROOT_REF,
            operation=LocalFileOperation.READ,
            path_relative="..\\escape.txt",
            requested_at=now,
        )

    # process.execute is not a generic shell: cmd.exe is not in the allowlist
    runtime = WindowsSubprocessLocalAgentRuntime(
        device=harness.device,
        executable_profiles=(harness.windows_profile(),),
        authorization_port=DeterministicFakeWindowsExecutionAuthorizationPort(
            capability_refs=(LocalCapability.PROCESS_EXECUTE.value,)
        ),
    )
    with pytest.raises(BROKER_REFUSALS) as excinfo:
        runtime.execute_with_receipt(
            LocalCommandRequest(
                request_id="request.3098.shell.1",
                run_id="run.3098.cap.1",
                device_id=DEVICE_ID,
                root_ref=ROOT_REF,
                argv=(r"C:\Windows\System32\cmd.exe", "/c", "echo escalated"),
                cwd_relative=".",
                requested_at=now,
                timeout_seconds=10,
            ),
            now=now,
        )
    refusal = _refusal_text(excinfo)
    assert any(
        marker in refusal
        for marker in (
            "not in the trusted executable profile allowlist",
            "shell and script-host executables are prohibited",
        )
    )


# ------------------------------------------------- timeout / cancellation


def test_timeout_and_cancellation_terminate_bounded(tmp_path, make_e2e, no_network):
    if os.name != "nt":
        pytest.skip("real Windows desktop execution leg requires Windows")
    harness = make_e2e()
    now = harness.server_clock.now
    sleep_script = "import time; time.sleep(20)\n"
    runtime = WindowsSubprocessLocalAgentRuntime(
        device=harness.device,
        executable_profiles=(harness.windows_profile(),),
        authorization_port=harness.windows_authorization_port(
            LocalCommandRequest(
                request_id="request.3098.timeout.1",
                run_id="run.3098.time.1",
                device_id=DEVICE_ID,
                root_ref=ROOT_REF,
                argv=(sys.executable, "-c", sleep_script),
                cwd_relative=".",
                requested_at=now,
                timeout_seconds=2,
            ),
            LocalCommandRequest(
                request_id="request.3098.cancel.1",
                run_id="run.3098.time.1",
                device_id=DEVICE_ID,
                root_ref=ROOT_REF,
                argv=(sys.executable, "-c", sleep_script),
                cwd_relative=".",
                requested_at=now,
                timeout_seconds=60,
            ),
        ),
    )

    timed_out = runtime.execute_with_receipt(
        LocalCommandRequest(
            request_id="request.3098.timeout.1",
            run_id="run.3098.time.1",
            device_id=DEVICE_ID,
            root_ref=ROOT_REF,
            argv=(sys.executable, "-c", sleep_script),
            cwd_relative=".",
            requested_at=now,
            timeout_seconds=2,
        ),
        now=now,
    )
    assert timed_out.termination.value == "timed_out"

    cancelled_request = LocalCommandRequest(
        request_id="request.3098.cancel.1",
        run_id="run.3098.time.1",
        device_id=DEVICE_ID,
        root_ref=ROOT_REF,
        argv=(sys.executable, "-c", sleep_script),
        cwd_relative=".",
        requested_at=now,
        timeout_seconds=60,
    )
    box: dict = {}

    def _execute():
        box["receipt"] = runtime.execute_with_receipt(cancelled_request, now=now)

    worker = threading.Thread(target=_execute, daemon=True)
    worker.start()
    time.sleep(1.0)
    runtime.cancel(cancelled_request.request_id)
    worker.join(timeout=30)
    assert "receipt" in box
    assert box["receipt"].termination.value == "cancelled"
    assert list(runtime.active_request_ids()) == []
