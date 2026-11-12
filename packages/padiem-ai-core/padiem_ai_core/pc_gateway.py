"""Closed, server-authored external-PC intent on the existing signed P01 wire.

This is provenance, not another device/tool grant. Browser and MCP arguments
must never be copied into this object wholesale. Existing admission and the
owner/device/path checks still authorize the actual tool invocation.
"""
from collections.abc import Mapping
import re

from .web_runtime import normalize_public_url


PC_GATEWAY_TOOLS = {
    "claw.pc.list_files": {"path"},
    "claw.pc.read_file": {"path"},
    "claw.pc.write_file": {"path", "content"},
    # #7065: change part of an existing file. Same write authority; the two
    # text arguments and the optional replace_all flag are the whole input.
    "claw.pc.edit_file": {"path", "old_text", "new_text", "replace_all"},
    "claw.pc.move_file": {"path", "destination"},
    "claw.pc.delete_file": {"path"},
    "claw.pc.browser_open": {"url"},
    "claw.pc.browser_read": set(),
    "claw.pc.browser_screenshot": set(),
    "claw.pc.browser_act": {"action", "text", "role", "name", "value"},
}
#: 2026-11-04: a read-only file tool may answer later than one MCP request
#: waits. The same tool then continues the dispatch it started, and this is the
#: only other argument shape those two tools accept: a job id and nothing else.
PC_GATEWAY_RESUME_TOOLS = frozenset({"claw.pc.list_files", "claw.pc.read_file"})
PC_GATEWAY_BROWSER_TOOLS = frozenset(name for name in PC_GATEWAY_TOOLS if name.startswith("claw.pc.browser_"))
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_PC_GATEWAY_JOB_ID = re.compile(r"dsp_[0-9a-f]{32}\Z")


def parse_pc_gateway(value):
    if value is None:
        return None
    required = {"version", "source", "token_id", "request_id", "tool_id", "arguments"}
    if (not isinstance(value, Mapping) or not required <= set(value)
            or set(value) - required - {"approval_id", "search_query", "browser_context"}
            or type(value["version"]) is not int or value["version"] != 1
            or value["source"] != "mcp"):
        raise ValueError("Invalid PC gateway provenance")
    for key in ("token_id", "request_id", "approval_id"):
        if key in value and (not isinstance(value[key], str) or not _ID.fullmatch(value[key])):
            raise ValueError("Invalid PC gateway reference")
    tool = value["tool_id"]
    args = value["arguments"]
    if (not isinstance(tool, str) or tool not in PC_GATEWAY_TOOLS
            or not isinstance(args, Mapping)
            or any(not isinstance(item, str)
                   and not (tool == "claw.pc.edit_file" and key == "replace_all"
                            and isinstance(item, bool))
                   for key, item in args.items())):
        raise ValueError("Invalid PC gateway tool arguments")
    browser = tool in PC_GATEWAY_BROWSER_TOOLS
    if tool == "claw.pc.browser_act":
        if (not set(args) <= PC_GATEWAY_TOOLS[tool] or args.get("action") not in {"click", "type"}
                or not (args.get("text", "").strip() or args.get("name", "").strip())
                or (args.get("action") == "type" and not args.get("value"))):
            raise ValueError("Invalid PC browser action")
    elif tool in PC_GATEWAY_RESUME_TOOLS and set(args) == {"job_id"}:
        if _PC_GATEWAY_JOB_ID.fullmatch(args["job_id"]) is None:
            raise ValueError("Invalid PC gateway job id")
    elif set(args) != PC_GATEWAY_TOOLS[tool] and not (
            tool == "claw.pc.edit_file"
            and set(args) == PC_GATEWAY_TOOLS[tool] - {"replace_all"}):
        raise ValueError("Invalid PC gateway tool arguments")
    if browser:
        if "approval_id" in value or "search_query" in value:
            raise ValueError("Browser confirmation must use ordinary first-party conversation")
        if tool == "claw.pc.browser_open":
            normalize_public_url(args["url"])
    elif "path" in args and (not args["path"].strip()
                             or ("destination" in args and not args["destination"].strip())):
        raise ValueError("Invalid PC gateway path")
    if "browser_context" in value:
        context = value["browser_context"]
        if not browser or not isinstance(context, Mapping) or set(context) != {"url"}:
            raise ValueError("Invalid PC browser context")
        normalize_public_url(context["url"])
    if "search_query" in value and (tool != "claw.pc.list_files"
            or not isinstance(value["search_query"], str) or not value["search_query"].strip()):
        raise ValueError("Invalid PC gateway search")
    result = {**dict(value), "arguments": dict(args)}
    if "browser_context" in result:
        result["browser_context"] = {"url": normalize_public_url(result["browser_context"]["url"])}
    return result
