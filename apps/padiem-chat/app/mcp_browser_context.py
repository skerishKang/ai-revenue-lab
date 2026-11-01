"""Last verified browser page in the existing private history object bucket.

This is disposable continuity, never permission: every call still authenticates
the PAT and rechecks the account's selected device through the normal PC lane.
MCP arguments cannot choose this key or provide a remembered URL.
"""
from collections.abc import Mapping
import hashlib
import inspect
import json
import re

from padiem_ai_core.web_runtime import normalize_public_url
from .history import PRODUCT_SCOPE_CHAT
from .workspace_storage import _read_r2_object_bytes

_CONVERSATION = re.compile(r"chat_[0-9a-f]{32}\Z")


def _identity(principal):
    values = [principal.get(name) for name in ("owner_id", "token_id", "device_id")]
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("Verified browser owner is required")
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def _key(principal):
    return "mcp-browser-context/v1/" + _identity(principal) + ".json"


async def load_browser_context(history, principal):
    bucket = getattr(history, "full_context_bucket", None)
    if bucket is None:
        return None
    result = bucket.get(_key(principal))
    if inspect.isawaitable(result):
        result = await result
    if result is None:
        return None
    data = json.loads((await _read_r2_object_bytes(result)).decode("utf-8"))
    if (not isinstance(data, Mapping) or set(data) != {"version", "binding", "url", "conversation_id"}
            or data["version"] != 1 or data["binding"] != _identity(principal)
            or not isinstance(data["conversation_id"], str)
            or not _CONVERSATION.fullmatch(data["conversation_id"])):
        return None
    url = normalize_public_url(data["url"])
    # Deleting the owning conversation also abandons this browser context.
    conversation = await history.get_conversation(
        principal["owner_id"], data["conversation_id"], product_scope=PRODUCT_SCOPE_CHAT)
    if conversation is None:
        return None
    return {"url": url, "conversation_id": data["conversation_id"]}


async def save_browser_context(history, principal, *, url, conversation_id):
    bucket = getattr(history, "full_context_bucket", None)
    if bucket is None or not callable(getattr(bucket, "put", None)):
        return False
    if not isinstance(conversation_id, str) or not _CONVERSATION.fullmatch(conversation_id):
        return False
    data = {"version": 1, "binding": _identity(principal),
            "url": normalize_public_url(url), "conversation_id": conversation_id}
    result = bucket.put(_key(principal), json.dumps(data, separators=(",", ":")).encode(),
                        httpMetadata={"contentType": "application/json"})
    if inspect.isawaitable(result):
        await result
    return True
