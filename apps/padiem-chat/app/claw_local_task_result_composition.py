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

    def __init__(self, *, history: Any, result_port: BrokerAuthorityLocalRunnerResultPort) -> None:
        self._history = history
        self._result_port = result_port

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
        bound = await self._history.get_local_task_correlation(owner_id, run_id)
        stored_command_id = bound.get("command_id") if bound else None
        if not isinstance(stored_command_id, str) or not stored_command_id:
            # No origin is bound yet. Bind it from the run's canonical command
            # identity — the enqueue record — and never from the terminal fact
            # that is about to be verified.
            identity = await self._result_port.command_identity(
                run_id=run_id, owner_id=owner_id, workspace_id=workspace_id
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
            expected_workspace_id=workspace_id,
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
    env: Any, history_store: Any
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
        )
    except Exception:
        return None, LOCAL_RUNNER_RESULT_DIAG_CONSTRUCTION_FAILED
    return source, None


def build_local_task_result_source(env: Any, history_store: Any) -> LocalRunnerResultSource | None:
    source, _ = build_local_task_result_source_with_diagnostic(env, history_store)
    return source
