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
    "claw.pc.move_file": {"path", "destination"},
    "claw.pc.delete_file": {"path"},
    "claw.pc.browser_open": {"url"},
    "claw.pc.browser_read": set(),
    "claw.pc.browser_screenshot": set(),
    "claw.pc.browser_act": {"action", "text", "role", "name", "value"},
}
PC_GATEWAY_BROWSER_TOOLS = frozenset(name for name in PC_GATEWAY_TOOLS if name.startswith("claw.pc.browser_"))
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


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
            or any(not isinstance(item, str) for item in args.values())):
        raise ValueError("Invalid PC gateway tool arguments")
    browser = tool in PC_GATEWAY_BROWSER_TOOLS
    if tool == "claw.pc.browser_act":
        if (not set(args) <= PC_GATEWAY_TOOLS[tool] or args.get("action") not in {"click", "type"}
                or not (args.get("text", "").strip() or args.get("name", "").strip())
                or (args.get("action") == "type" and not args.get("value"))):
            raise ValueError("Invalid PC browser action")
    elif set(args) != PC_GATEWAY_TOOLS[tool]:
        raise ValueError("Invalid PC gateway tool arguments")
    if browser:
        if "approval_id" in value or "search_query" in value:
            raise ValueError("Browser confirmation must use ordinary first-party conversation")
        if tool == "claw.pc.browser_open":
            normalize_public_url(args["url"])
    elif not args["path"].strip() or ("destination" in args and not args["destination"].strip()):
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
