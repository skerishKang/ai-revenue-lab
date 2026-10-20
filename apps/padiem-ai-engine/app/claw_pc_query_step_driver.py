"""Engine-side consumption of the verified PC drive/file tool contract (#5151).

The product adapter (``kagent.pc_query_adapter``) owns the PC tool contract:
the product identities, the tool ids/scopes/specs, the signed product
callbacks, the drive-query and file-list/read executions, the step policy and
the model step prompt. The Engine keeps only what it is responsible for — the
durable run, the long-running wait and the recovery — and consumes the product
contract through its existing injection point (``tool_binding_resolver`` /
``pc_query_step_driver_factory``).

This module is the compatibility surface for the existing import paths: the
product contract, the PC file lane and the prompt are re-exported from the
product adapter, and the previous private names stay importable until the
consumers have moved. The Engine keeps one thing of its own: assembling its
own ``EngineToolBinding`` around the product contract.

The file lane and the prompt moved here from this module in #5151, after the
connector lane's #5175 change to the same lines had merged. There is one
implementation of each: the product adapter's.
"""

from __future__ import annotations

from padiem_ai_core.tool_runtime import ToolRuntime
from padiem_ai_core.tool_registry import ToolRegistrySnapshot
from padiem_ai_core.tool_resource_policy import ToolResourcePolicy

from kagent.pc_query_adapter import (
    CHAT_APP_ID,
    CHAT_ENGINE_PC_DRIVE_URL,
    CHAT_ENGINE_PC_FILES_URL,
    CHAT_PC_QUERY_AGENT_ID,
    CLAW_APP_ID,
    CLAW_ENGINE_PC_DRIVE_URL,
    CLAW_ENGINE_PC_FILES_URL,
    PCQueryStepError,
    PC_DRIVES_CANONICAL_TOOL_ID,
    PC_DRIVES_TOOL_ID,
    PC_DRIVE_COMMAND,
    PC_FILES_DOWNSTREAM_STAGE,
    PC_FILE_ERROR_PREFIX,
    PC_FILE_TOOL_IDS,
    PC_LIST_FILES_CANONICAL_TOOL_ID,
    PC_LIST_FILES_SCOPE,
    PC_LIST_FILES_TOOL_ID,
    PC_QUERY_AGENT_ID,
    PC_QUERY_CANONICAL_AGENT_ID,
    PC_QUERY_OWNER,
    PC_QUERY_SCOPE,
    PC_READ_FILE_CANONICAL_TOOL_ID,
    PC_READ_FILE_SCOPE,
    PC_READ_FILE_TOOL_ID,
    StructuredPCQueryStepDriver,
    build_live_pc_query_driver,
    build_pc_query_product_contract,
    make_pc_file_handler,
    make_query_drives_handler,
    pc_file_call_ref,
    pc_files_endpoint,
    pc_list_entries_with_paths,
    pc_list_files_tool_spec,
    pc_list_folder_prefix,
    pc_read_file_tool_spec,
    plan_step_arguments,
    register_pc_query_drives_tool,
    selected_device_id,
    signed_chat_call,
    signed_files_call,
    validate_pc_file_arguments,
)

from app.tool_projection import EngineToolBinding, TrustedToolAuthority

# --- temporary compatibility aliases (#5151) --------------------------------
# The product adapter owns these contracts now. The previous names stay
# importable so the Engine's existing call sites and the connector lane's
# tests keep working until the compatibility surface is removed.
_PC_QUERY_OWNER = PC_QUERY_OWNER
_selected_device_id = selected_device_id
_signed_chat_call = signed_chat_call
_make_query_drives_handler = make_query_drives_handler
_plan_step_arguments = plan_step_arguments
_pc_files_endpoint = pc_files_endpoint
_signed_files_call = signed_files_call
_validate_pc_file_arguments = validate_pc_file_arguments
_pc_list_folder_prefix = pc_list_folder_prefix
_pc_list_entries_with_paths = pc_list_entries_with_paths
_pc_file_call_ref = pc_file_call_ref
_make_pc_file_handler = make_pc_file_handler


def _build_pc_query_binding(*, service, request_factory, secret, runtime: ToolRuntime | None,
                            app_id: str, agent_id: str, endpoint_url: str):
    """Thin per-product binding over the shared drive-query contract.

    The product adapter owns the tool contract, the agent definition, the
    authorization, the file lane and the prompt; this function only assembles
    the Engine's own binding type and registers the product's tools.
    """
    contract = build_pc_query_product_contract(app_id=app_id, agent_id=agent_id)
    runtime = runtime or ToolRuntime()
    register_pc_query_drives_tool(
        runtime=runtime, service=service, request_factory=request_factory,
        secret=secret, endpoint_url=endpoint_url,
    )
    runtime.register(pc_list_files_tool_spec(), make_pc_file_handler(
        tool_id=PC_LIST_FILES_TOOL_ID, op="list", service=service,
        request_factory=request_factory, secret=secret))
    runtime.register(pc_read_file_tool_spec(), make_pc_file_handler(
        tool_id=PC_READ_FILE_TOOL_ID, op="read", service=service,
        request_factory=request_factory, secret=secret))
    return EngineToolBinding(app_id=app_id, tool_runtime=runtime,
        registry=ToolRegistrySnapshot.from_entries(contract.registry_entries),
        authorities={agent_id: TrustedToolAuthority(canonical_agent_id=agent_id,
            definition=contract.definition, compiled=contract.compiled,
            authorization=contract.authorization)},
        authorization_provider=None, resource_policy=ToolResourcePolicy())


def build_claw_pc_query_tool_binding(*, service, request_factory, secret, runtime: ToolRuntime | None = None):
    return _build_pc_query_binding(service=service, request_factory=request_factory,
        secret=secret, runtime=runtime, app_id=CLAW_APP_ID, agent_id=PC_QUERY_AGENT_ID,
        endpoint_url=CLAW_ENGINE_PC_DRIVE_URL)


def build_chat_pc_query_tool_binding(*, service, request_factory, secret, runtime: ToolRuntime | None = None):
    return _build_pc_query_binding(service=service, request_factory=request_factory,
        secret=secret, runtime=runtime, app_id=CHAT_APP_ID, agent_id=CHAT_PC_QUERY_AGENT_ID,
        endpoint_url=CHAT_ENGINE_PC_DRIVE_URL)


__all__ = [
    "CHAT_APP_ID",
    "CHAT_ENGINE_PC_DRIVE_URL",
    "CHAT_ENGINE_PC_FILES_URL",
    "CHAT_PC_QUERY_AGENT_ID",
    "CLAW_APP_ID",
    "CLAW_ENGINE_PC_DRIVE_URL",
    "CLAW_ENGINE_PC_FILES_URL",
    "PC_DRIVES_CANONICAL_TOOL_ID",
    "PC_DRIVES_TOOL_ID",
    "PC_FILES_DOWNSTREAM_STAGE",
    "PC_FILE_ERROR_PREFIX",
    "PC_FILE_TOOL_IDS",
    "PC_LIST_FILES_CANONICAL_TOOL_ID",
    "PC_LIST_FILES_SCOPE",
    "PC_LIST_FILES_TOOL_ID",
    "PC_QUERY_AGENT_ID",
    "PC_QUERY_CANONICAL_AGENT_ID",
    "PC_QUERY_OWNER",
    "PC_QUERY_SCOPE",
    "PC_READ_FILE_CANONICAL_TOOL_ID",
    "PC_READ_FILE_SCOPE",
    "PC_READ_FILE_TOOL_ID",
    "PCQueryStepError",
    "StructuredPCQueryStepDriver",
    "build_chat_pc_query_tool_binding",
    "build_claw_pc_query_tool_binding",
    "build_live_pc_query_driver",
    "make_pc_file_handler",
    "pc_file_call_ref",
    "pc_files_endpoint",
    "pc_list_entries_with_paths",
    "pc_list_folder_prefix",
    "signed_files_call",
    "validate_pc_file_arguments",
]
