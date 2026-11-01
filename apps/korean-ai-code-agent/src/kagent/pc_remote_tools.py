"""Closed PC output/job wrappers; every operation keeps its existing file scope."""
from __future__ import annotations

from collections.abc import Mapping
import re

from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect, ToolSpec

PREFIX = "claw.pc."
REMOTE_NAMES = ("read_output", "search_output", "start_job", "job_status", "job_output", "batch", "recall_context")
REMOTE_TOOL_IDS = frozenset(PREFIX + name for name in REMOTE_NAMES)
REMOTE_CANONICAL_IDS = {PREFIX + name: "tool:padiem:claw-pc-" + name.replace("_", "-") + "@1" for name in REMOTE_NAMES}
OP_TO_TOOL = {name: PREFIX + tool for name, tool in {
    "list": "list_files", "read": "read_file", "write": "write_file",
    "move": "move_file", "delete": "delete_file",
}.items()}
_HANDLE = re.compile(r"^[0-9a-f]{64}$")


def operation_actions(arguments, *, batch=False):
    """Return normalized existing tool calls, rejecting wrappers/shell/extra fields."""
    from .pc_query_adapter import PC_FILE_TOOL_ARGUMENT_KEYS, pc_file_arguments_acceptable
    operations = arguments.get("operations") if batch else [arguments.get("operation")]
    if not isinstance(operations, (list, tuple)) or not operations:
        raise ValueError("PC operations must be a non-empty list")
    result = []
    for operation in operations:
        if not isinstance(operation, Mapping) or not isinstance(operation.get("op"), str):
            raise ValueError("Invalid PC operation")
        tool_id = OP_TO_TOOL.get(operation["op"])
        args = {key: value for key, value in operation.items() if key != "op"}
        if tool_id is None or set(args) != PC_FILE_TOOL_ARGUMENT_KEYS[tool_id] or not pc_file_arguments_acceptable(tool_id, args):
            raise ValueError("Invalid PC operation")
        result.append((tool_id, dict(args)))
    return tuple(result)


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def validate_remote_arguments(tool_id, arguments):
    if tool_id not in REMOTE_TOOL_IDS or not isinstance(arguments, Mapping):
        raise ValueError("Invalid PC remote tool")
    data = _plain(arguments)
    name = tool_id.removeprefix(PREFIX)
    if name in {"read_output", "search_output"}:
        expected = {"handle", "offset", "length"} if name == "read_output" else {"handle", "query"}
        if set(data) != expected or not isinstance(data["handle"], str) or not _HANDLE.fullmatch(data["handle"]):
            raise ValueError("Invalid output handle request")
    elif name in {"job_status", "job_output"}:
        expected = {"job_id"} if name == "job_status" else {"job_id", "offset", "length"}
        if set(data) != expected or not isinstance(data["job_id"], str) or not data["job_id"] or len(data["job_id"]) > 256:
            raise ValueError("Invalid background job request")
    elif name == "start_job":
        if set(data) != {"operation"}:
            raise ValueError("Invalid background operation")
        operation_actions(data)
    elif name == "batch":
        if set(data) != {"operations", "stop_on_error"} or type(data["stop_on_error"]) is not bool:
            raise ValueError("Invalid batch request")
        operation_actions(data, batch=True)
    elif name == "recall_context":
        if not {"handle"} <= set(data) or set(data) - {"handle", "source_id", "offset", "length"}:
            raise ValueError("Invalid context recall")
        if not isinstance(data["handle"], str) or not data["handle"]:
            raise ValueError("Invalid context handle")
        if "source_id" in data and (not isinstance(data["source_id"], str) or not data["source_id"]):
            raise ValueError("Invalid context source")
    for key in ("offset", "length"):
        if key in data and (type(data[key]) is not int or data[key] < 0):
            raise ValueError("Output byte range must be non-negative integers")
    if data.get("length", 0) > 65536:
        raise ValueError("Output range exceeds the transport page size")
    if "query" in data and (not isinstance(data["query"], str) or not data["query"]):
        raise ValueError("Output search requires text")
    return data


def remote_tool_allowed(tool_id, arguments, allowed_base_tools):
    """A wrapper may narrow existing authority, never introduce a file action."""
    if not allowed_base_tools:
        return False
    if tool_id in {PREFIX + "start_job", PREFIX + "batch"}:
        return all(tool in allowed_base_tools for tool, _ in operation_actions(
            arguments, batch=tool_id == PREFIX + "batch"))
    return tool_id in REMOTE_TOOL_IDS


def remote_requested_scope(tool_id, arguments):
    if tool_id not in {PREFIX + "start_job", PREFIX + "batch"}:
        return None
    try:
        actions = operation_actions(arguments, batch=tool_id == PREFIX + "batch")
    except (TypeError, ValueError, AttributeError):
        return None
    operations = {tool for tool, _ in actions}
    if operations <= {OP_TO_TOOL["list"]}:
        return "files_list"
    if operations <= {OP_TO_TOOL["list"], OP_TO_TOOL["read"]}:
        return "files"
    if operations <= {OP_TO_TOOL["write"], OP_TO_TOOL["move"], OP_TO_TOOL["delete"]}:
        return "files_write"
    return None


def remote_tool_specs():
    text = {"type": "string", "minLength": 1}
    number = {"type": "integer", "minimum": 0}
    operation = {"type": "object", "properties": {
        "op": {"type": "string", "enum": list(OP_TO_TOOL)}, "path": text,
        "content": {"type": "string"}, "destination": text,
    }, "required": ["op", "path"], "additionalProperties": False}
    shapes = {
        "read_output": ({"handle": text, "offset": number, "length": {**number, "maximum": 65536}}, ["handle", "offset", "length"]),
        "search_output": ({"handle": text, "query": text}, ["handle", "query"]),
        "start_job": ({"operation": operation}, ["operation"]),
        "job_status": ({"job_id": text}, ["job_id"]),
        "job_output": ({"job_id": text, "offset": number, "length": {**number, "maximum": 65536}}, ["job_id", "offset", "length"]),
        "batch": ({"operations": {"type": "array", "minItems": 1, "items": operation},
                   "stop_on_error": {"type": "boolean"}}, ["operations", "stop_on_error"]),
        "recall_context": ({"handle": text, "source_id": text, "offset": number, "length": {**number, "maximum": 65536}}, ["handle"]),
    }
    descriptions = {
        "read_output": "Read a byte range from this owner's stored PC output.",
        "search_output": "Search this owner's stored PC output without loading the whole result.",
        "start_job": "Start one existing authorized file operation in the background; use its job receipt.",
        "job_status": "Check the existing owner/device/run-bound background dispatch.",
        "job_output": "Read a byte range of the verified background result.",
        "batch": "Run existing file operations after every action passes evidence and delegation checks.",
        "recall_context": "Read original role-preserved conversation evidence by archived handle and source.",
    }
    specs = []
    for name in REMOTE_NAMES:
        tool_id = PREFIX + name
        properties, required = shapes[name]
        mutating = name in {"start_job", "batch"}
        specs.append(ToolSpec(id=tool_id, title=name.replace("_", " ").title(),
            description=descriptions[name], owner="core",
            side_effect=ToolSideEffect.WRITE if mutating else ToolSideEffect.READ,
            approval_policy=ApprovalPolicy.EXTERNAL_AUTHORIZATION if mutating else ApprovalPolicy.NOT_REQUIRED,
            auth_scope=(tool_id,), input_schema={"type": "object", "properties": properties,
                "required": required, "additionalProperties": False},
            output_contract={"type": "object"}, timeout_seconds=None))
    return tuple(specs)
