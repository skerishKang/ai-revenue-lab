"""#3139 — the deployable source of the Local Runner return leg.

Two pieces compose the projection into the running product:

* `BrokerAuthorityLocalRunnerResultPort` — the concrete
  `TrustedLocalRunnerResultPort`, speaking the canonical broker's narrow
  read-only `terminal_command_result` RPC over the trusted private Service
  Binding. No public route exists for it, and it reads; it never writes.
* `build_local_task_result_source(env, history_store)` — the fail-closed
  composition the Worker root uses, mirroring `build_claw_local_access_source`:
  a missing or incompatible binding yields an unconfigured source, never a
  guessed one.
"""

from __future__ import annotations

from typing import Any

from .claw_local_access_composition import LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME
from .worker_config import binding_value
from .history import HistoryError
from .claw_local_task_result_projection import (
    LocalRunnerTerminalObservation,
    LocalTaskResultError,
)

LOCAL_RUNNER_RESULT_DIAG_BOUNDING_ABSENT = "local_runner_result_binding_absent"
LOCAL_RUNNER_RESULT_DIAG_PORT_INCOMPATIBLE = "local_runner_result_port_incompatible"
LOCAL_RUNNER_RESULT_DIAG_CONSTRUCTION_FAILED = "local_runner_result_construction_failed"

__all__ = [
    "BrokerAuthorityLocalRunnerResultPort",
    "UnconfiguredLocalRunnerResultSource",
    "build_local_task_result_source",
    "build_local_task_result_source_with_diagnostic",
]


class BrokerAuthorityLocalRunnerResultPort:
    """Typed port adapter over the canonical broker terminal-result RPC.

    Exactly like `BrokerAuthorityDeviceTruthPort`, this is the only translation
    between the broker Worker's private Service Binding surface and the typed
    port protocol. It forwards the server-derived owner identity and the run
    whose result is being returned, and hands the envelope back untouched.
    """

    configured = True

    def __init__(self, binding: Any) -> None:
        self._binding = binding

    async def command_identity(self, *, run_id: str, owner_id: str, workspace_id: str | None = None):
        """The run's canonical command identity, independent of any outcome."""

        facts = await self._read(run_id=run_id, owner_id=owner_id, workspace_id=workspace_id)
        if facts is None:
            return None
        return facts.get("command_identity")

    async def command_result(self, *, command_id: str, run_id: str, owner_id: str, workspace_id: str | None = None):
        """The bounded terminal fact, read only after the origin is bound.

        ``command_id`` is supplied from the *stored* correlation, so this read
        verifies the command the run was bound to rather than choosing one.
        """

        facts = await self._read(run_id=run_id, owner_id=owner_id, workspace_id=workspace_id)
        if facts is None:
            return None
        terminal = facts.get("command_result")
        if not isinstance(terminal, dict):
            return None
        observation = LocalRunnerTerminalObservation(
            command_id=terminal.get("command_id"),
            run_id=terminal.get("run_id"),
            tool_request_ref=terminal.get("tool_request_ref"),
            request_id=terminal.get("request_id"),
            revision_ref=terminal.get("revision_ref"),
            evidence_ref=terminal.get("evidence_ref"),
            request_fingerprint=terminal.get("request_fingerprint"),
            sequence=terminal.get("sequence"),
            state=terminal.get("state"),
            termination=terminal.get("termination"),
            exit_code=terminal.get("exit_code"),
            acknowledged_at=terminal.get("acknowledged_at"),
        )
        if observation.command_id != command_id:
            raise LocalTaskResultError(
                "local_task_result_command_mismatch",
                "the terminal fact does not belong to the command this run is bound to",
            )
        return observation

    async def _read(self, *, run_id: str, owner_id: str, workspace_id: str | None):
        payload: dict[str, Any] = {"account_ref": owner_id, "run_id": run_id}
        if workspace_id is not None:
            payload["workspace_ref"] = workspace_id
        result = self._binding.terminal_command_result(payload)
        if result is not None and hasattr(result, "__await__"):
            result = await result
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise LocalTaskResultError(
                "local_task_result_broker_unavailable",
                "the canonical broker refused the terminal-result read",
            )
        if result.get("available") is not True:
            return None
        return result


class UnconfiguredLocalRunnerResultSource:
    """The fail-closed default: no projection exists until a binding composes one."""

    configured = False

    async def project_local_runner_result(
        self,
        *,
        owner_id: str,
        run_id: str,
        command_id: str | None = None,
    ) -> dict[str, Any] | None:
        del owner_id, run_id, command_id
        return None


class LocalRunnerResultSource:
    """The server-owned consumer: run row in, bounded conversation result out.

    The destination conversation is resolved from the origin run row inside the
    projection; nothing here accepts one, so a browser or a device cannot choose
    where a result lands.
    """

    configured = True

    def __init__(self, *, history: Any, result_port: BrokerAuthorityLocalRunnerResultPort,
                 office_completion=None) -> None:
        self._history = history
        self._result_port = result_port
        # An explicit approved Drive pipeline is a host-only optional port.
        # The normal broker result projection never triggers a file upload.
        self._office_completion = office_completion
        self._office_reader = None
        if callable(getattr(getattr(result_port, "_binding", None),
                            "read_office_artifact_part", None)):
            from .claw_local_office_binary_reader import BrokerOfficeBinaryReader
            self._office_reader = BrokerOfficeBinaryReader(
                private_binding=result_port._binding
            )

    async def read_staged_office_output(
        self, *, owner_id: str, run_ref: str, kind: str,
    ):
        """Trusted host-only, owner/run-verified private binary read.

        Never exposed through the public local-result route. The broker and D1
        must independently agree on an exact, completed, successful command.
        """
        from .claw_local_office_binary_reader import OfficeBinaryReadRefused
        from .claw_local_task_result_projection import LocalRunnerTerminalObservation
        from .history import validate_conversation_id
        if self._office_reader is None:
            raise OfficeBinaryReadRefused("private Office bytes unavailable")
        row = await self._history.get_claw_run(owner_id, run_ref)
        if not isinstance(row, dict) or row.get("run_id") != run_ref:
            raise OfficeBinaryReadRefused("owner-bound Office run unavailable")
        cid = validate_conversation_id(row.get("conversation_id"))
        workspace = row.get("workspace_id")
        if (cid is None or not isinstance(workspace, str) or not workspace
                or row.get("status") != "completed"
                or await self._history.verify_owner_conversation_artifacts(
                    owner_id, cid
                ) is not True):
            raise OfficeBinaryReadRefused("completed owner conversation unavailable")
        bound = await self._history.get_local_task_correlation(owner_id, run_ref)
        fields = (
            "command_id", "tool_request_ref", "request_id",
            "revision_ref", "evidence_ref", "request_fingerprint",
        )
        if not isinstance(bound, dict) or any(k not in bound for k in fields):
            raise OfficeBinaryReadRefused("canonical command correlation unavailable")
        try:
            fact = await self._result_port.command_result(
                command_id=bound["command_id"], run_id=run_ref,
                owner_id=owner_id, workspace_id=workspace,
            )
        except Exception:
            raise OfficeBinaryReadRefused("canonical broker result unavailable") from None
        if (not isinstance(fact, LocalRunnerTerminalObservation)
                or fact.state != "acknowledged" or fact.termination != "exited"
                or fact.exit_code != 0 or fact.run_id != run_ref
                or any(getattr(fact, k) != bound[k] for k in fields)):
            raise OfficeBinaryReadRefused("successful exact broker command unverified")
        return await self._office_reader.read(
            owner_id=owner_id, workspace_ref=workspace,
            run_ref=run_ref, command_id=bound["command_id"], kind=kind,
        )

    async def complete_approved_office_run(
        self, *, owner_id, run_ref, outputs, xlsx_intent, pdf_intent, now,
    ):
        """Trusted host callback, NEVER invoked by the public terminal GET/POST."""
        from .claw_local_office_origin_bridge import LocalOfficeOriginBridge
        from .claw_durable_drive_output_pipeline import DurableArtifactCompletionError
        if self._office_completion is None:
            raise DurableArtifactCompletionError("approved Office/Drive host unavailable")
        bridge = LocalOfficeOriginBridge(
            history=self._history, terminal_port=self._result_port,
            completion=self._office_completion,
        )
        return await bridge.complete_approved_office_run(
            owner_id=owner_id, run_ref=run_ref, outputs=outputs,
            xlsx_intent=xlsx_intent, pdf_intent=pdf_intent, now=now,
        )

    async def project_local_runner_result(
        self,
        *,
        owner_id: str,
        run_id: str,
        command_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any] | None:
        from .claw_local_task_result_projection import project_local_runner_terminal_result

        row = await self._history.get_claw_run(owner_id, run_id)
        if row is None:
            # Existence of another owner's run is never disclosed.
            return None
        # The run row's own workspace is the authoritative scope. A caller may
        # only confirm it: widening the broker read to the whole account would
        # let a same run id in another workspace influence this run.
        run_workspace_id = row.get("workspace_id")
        if not isinstance(run_workspace_id, str) or not run_workspace_id:
            # No canonical workspace for this run: refuse rather than fall back
            # to account-wide scoping.
            raise LocalTaskResultError(
                "local_task_result_workspace_missing",
                "the originating run has no canonical workspace scope",
            )
        if workspace_id is not None and workspace_id != run_workspace_id:
            raise LocalTaskResultError(
                "local_task_result_workspace_mismatch",
                "the supplied workspace does not match the originating run",
            )
        effective_workspace_id = run_workspace_id

        bound = await self._history.get_local_task_correlation(owner_id, run_id)
        stored_command_id = bound.get("command_id") if bound else None
        if not isinstance(stored_command_id, str) or not stored_command_id:
            # No origin is bound yet. Bind it from the run's canonical command
            # identity — the enqueue record — and never from the terminal fact
            # that is about to be verified.
            identity = await self._result_port.command_identity(
                run_id=run_id, owner_id=owner_id, workspace_id=effective_workspace_id
            )
            if not isinstance(identity, dict):
                return None
            try:
                await self._history.record_local_task_correlation(
                    user_id=owner_id,
                    run_id=run_id,
                    command_id=identity.get("command_id"),
                    tool_request_ref=identity.get("tool_request_ref"),
                    request_id=identity.get("request_id"),
                    revision_ref=identity.get("revision_ref"),
                    request_fingerprint=identity.get("request_fingerprint"),
                    evidence_ref=identity.get("evidence_ref"),
                )
            except HistoryError:
                # Another writer bound this run first; the stored binding is the
                # one every later projection must satisfy.
                bound = await self._history.get_local_task_correlation(owner_id, run_id)
                stored_command_id = bound.get("command_id") if bound else None
            else:
                stored_command_id = identity.get("command_id")
        if not isinstance(stored_command_id, str) or not stored_command_id:
            return None
        decision = await project_local_runner_terminal_result(
            history=self._history,
            result_port=self._result_port,
            user_id=owner_id,
            run_id=run_id,
            command_id=stored_command_id,
            expected_workspace_id=effective_workspace_id,
        )
        return {
            "runId": run_id,
            "commandId": stored_command_id,
            "appended": decision.append,
            "status": decision.status,
            "reason": decision.reason,
            "executed": decision.status == "completed",
            "raw_argv": False,
            "raw_stdout": False,
            "raw_stderr": False,
            "raw_device_credential": False,
            "p01_approval_payload": False,
        }


def build_local_task_result_source_with_diagnostic(
    env: Any, history_store: Any, *, office_completion=None
) -> tuple[LocalRunnerResultSource | None, str | None]:
    """Compose the concrete source from the trusted binding, or fail closed."""

    if history_store is None:
        return None, LOCAL_RUNNER_RESULT_DIAG_BOUNDING_ABSENT
    boundary = binding_value(env, LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME)
    if boundary is None:
        return None, LOCAL_RUNNER_RESULT_DIAG_BOUNDING_ABSENT
    try:
        port = getattr(boundary, "terminal_command_result")
    except Exception:
        return None, LOCAL_RUNNER_RESULT_DIAG_PORT_INCOMPATIBLE
    if not callable(port):
        return None, LOCAL_RUNNER_RESULT_DIAG_PORT_INCOMPATIBLE
    try:
        source = LocalRunnerResultSource(
            history=history_store,
            result_port=BrokerAuthorityLocalRunnerResultPort(boundary),
            office_completion=office_completion,
        )
    except Exception:
        return None, LOCAL_RUNNER_RESULT_DIAG_CONSTRUCTION_FAILED
    return source, None


def build_local_task_result_source(env: Any, history_store: Any, *, office_completion=None) -> LocalRunnerResultSource | None:
    source, _ = build_local_task_result_source_with_diagnostic(
        env, history_store, office_completion=office_completion,
    )
    return source
