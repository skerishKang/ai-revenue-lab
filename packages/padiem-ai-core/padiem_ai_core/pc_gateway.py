"""Closed, server-authored external-PC intent on the existing signed P01 wire.

This is provenance, not another device/tool grant. Browser and MCP arguments
must never be copied into this object wholesale. Existing admission and the
owner/device/path checks still authorize the actual tool invocation.
"""
from collections.abc import Mapping
import re


PC_GATEWAY_TOOLS = {
    "claw.pc.list_files": {"path"},
    "claw.pc.read_file": {"path"},
    "claw.pc.write_file": {"path", "content"},
    "claw.pc.move_file": {"path", "destination"},
    "claw.pc.delete_file": {"path"},
}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


def parse_pc_gateway(value):
    if value is None:
        return None
    required = {"version", "source", "token_id", "request_id", "tool_id", "arguments"}
    if (not isinstance(value, Mapping) or not required <= set(value)
            or set(value) - required - {"approval_id", "search_query"}
            or type(value["version"]) is not int or value["version"] != 1
            or value["source"] != "mcp"):
        raise ValueError("Invalid PC gateway provenance")
    for key in ("token_id", "request_id", "approval_id"):
        if key in value and (not isinstance(value[key], str) or not _ID.fullmatch(value[key])):
            raise ValueError("Invalid PC gateway reference")
    tool = value["tool_id"]
    args = value["arguments"]
    if (not isinstance(tool, str) or tool not in PC_GATEWAY_TOOLS
            or not isinstance(args, Mapping) or set(args) != PC_GATEWAY_TOOLS[tool]
            or any(not isinstance(item, str) for item in args.values())
            or not args["path"].strip()
            or ("destination" in args and not args["destination"].strip())):
        raise ValueError("Invalid PC gateway tool arguments")
    if "search_query" in value and (tool != "claw.pc.list_files"
            or not isinstance(value["search_query"], str) or not value["search_query"].strip()):
        raise ValueError("Invalid PC gateway search")
    return {**dict(value), "arguments": dict(args)}
