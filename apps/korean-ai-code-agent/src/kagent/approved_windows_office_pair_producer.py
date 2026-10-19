"""#3580: P01-selected XLSX → supervised Excel PDF → original-preserving pair.

Trusted Windows resident composition only, never browser upload/model-named
file selection. A separately approved selected-root READ is mandatory even
after a command's successful Broker ACK; no grant is minted here.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from typing import Callable, Protocol

from .contracts import ContractError
from .local_agent_control_plane_admission import ControlPlaneAdmittedExecutionReceipt
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope
from .local_xlsx_artifact_handoff import (
    LocalXlsxArtifactHandoff, capture_local_xlsx_for_handoff,
)
from .local_xlsx_pdf_output import (
    LocalXlsxPdfOutput, TrustedLocalOfficePdfRenderer,
    render_local_xlsx_pdf_output,
)
from .windows_local_filesystem import (
    LocalFileOperation, LocalFileRequest, WindowsSelectedRootFileRuntime,
)
from .windows_local_executor import WindowsExecutionTermination


class TrustedApprovedOfficeFileRequestPort(Protocol):
    """Exact authorized P01 file-read request, originating in the trusted host.

    An ordinary command returns None. Implementations MUST NOT read a model
    response or walk a Windows directory to guess which XLSX belongs to a run.
    The separately configured WindowsSelectedRootFileRuntime grant re-checks
    the request against the actual selected root and local permission.
    """

    def request_for_completed_command(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> LocalFileRequest | None: ...


class ApprovedWindowsOfficePairProducer:
    def __init__(
        self, *, files: WindowsSelectedRootFileRuntime,
        requests: TrustedApprovedOfficeFileRequestPort,
        renderer: TrustedLocalOfficePdfRenderer,
        clock: Callable[[], datetime],
    ) -> None:
        if (not isinstance(files, WindowsSelectedRootFileRuntime)
                or not callable(getattr(requests, "request_for_completed_command", None))
                or not callable(getattr(renderer, "render_xlsx_pdf", None))
                or not callable(clock)):
            raise ContractError("trusted P01 file runtime, Office plan and renderer required")
        self._files = files
        self._requests = requests
        self._renderer = renderer
        self._clock = clock

    def completed_pair(
        self, *, binding: DeviceBinding, command: DeviceCommandEnvelope,
        receipt: ControlPlaneAdmittedExecutionReceipt,
    ) -> tuple[LocalXlsxArtifactHandoff, LocalXlsxPdfOutput] | None:
        if (not isinstance(binding, DeviceBinding)
                or not isinstance(command, DeviceCommandEnvelope)
                or not isinstance(receipt, ControlPlaneAdmittedExecutionReceipt)):
            raise ContractError("canonical acknowledged command required for Office")
        fact = receipt.execution
        if (fact.command_id != command.command_id
                or fact.binding_ref != binding.binding_ref
                or fact.run_id != command.run_id
                or fact.tool_request_ref != command.tool_request_ref
                or fact.revision_ref != command.revision_ref
                or fact.sequence != command.sequence
                or fact.termination is not WindowsExecutionTermination.EXITED
                or fact.exit_code != 0):
            raise ContractError("Office producer requires exact successful Broker command")
        request = self._requests.request_for_completed_command(
            binding=binding, command=command, receipt=receipt,
        )
        if request is None:
            return None
        if (not isinstance(request, LocalFileRequest)
                or request.operation is not LocalFileOperation.READ
                or request.run_id != command.run_id
                or request.device_id != binding.device_id
                or not request.path_relative.lower().endswith(".xlsx")):
            raise ContractError("Office producer received foreign/non-read file request")
        now = self._clock()
        if (not isinstance(now, datetime) or now.tzinfo is None
                or now.utcoffset() is None
                or now < receipt.acknowledged_at - timedelta(minutes=5)):
            raise ContractError("current trusted post-ACK local file clock required")
        # The selected-root runtime checks the current P01 file grant, device,
        # selected root, symlink escape, allowed operation, size and bytes.
        # Its result is canonical and immutable, not a raw arbitrary path.
        ref = sha256(f"{command.command_id}:{request.action_id}".encode()).hexdigest()[:28]
        source = capture_local_xlsx_for_handoff(
            runtime=self._files, request=request,
            now=now, workspace_ref=binding.workspace_ref,
            artifact_id=f"resident_office_source_{ref}",
        )
        # The renderer is a separately supervised Windows child (or an
        # explicitly injected trusted test renderer), never arbitrary execution.
        result = render_local_xlsx_pdf_output(
            source=source, renderer=self._renderer,
            workspace_ref=binding.workspace_ref, run_ref=command.run_id,
            artifact_id=f"resident_office_pdf_{ref}",
            lineage_id=f"resident_office_lineage_{ref}",
            now=now,
        )
        return source, result


PRODUCTION_P01_SELECTED_ROOT_OFFICE_PROVIDER_CONFIGURED = False


def compose_approved_windows_office_pairs(
    *, device, file_requests: TrustedApprovedOfficeFileRequestPort,
    file_authorization_port, clock: Callable[[], datetime],
    renderer: TrustedLocalOfficePdfRenderer | None = None,
) -> ApprovedWindowsOfficePairProducer:
    """Explicit trusted Resident composition; no ambient Office switch.

    Accepts only a genuine Windows device and independently configured file
    authorization. Neither P01 process approval nor browser login grants READ.
    """
    from .local_agent import LocalAgentDeviceProfile, LocalAgentPlatform
    from .supervised_windows_excel_pdf import SupervisedWindowsExcelPdfRenderer

    if (not isinstance(device, LocalAgentDeviceProfile)
            or device.platform is not LocalAgentPlatform.WINDOWS
            or not callable(getattr(file_requests, "request_for_completed_command", None))
            or not callable(getattr(file_authorization_port, "authorize", None))):
        raise ContractError("current P01 selected-root READ authorization required")
    return ApprovedWindowsOfficePairProducer(
        files=WindowsSelectedRootFileRuntime(
            device=device, authorization_port=file_authorization_port,
        ),
        requests=file_requests,
        renderer=renderer if renderer is not None else SupervisedWindowsExcelPdfRenderer(),
        clock=clock,
    )
