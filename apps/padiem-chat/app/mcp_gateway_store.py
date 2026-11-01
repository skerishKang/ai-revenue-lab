"""Personal MCP credentials and exact owner-confirmation receipts in Chat's DB.

Credentials authenticate an existing account/device pair; they grant no folder,
command, Connector or Engine entitlement. Existing PC authorities still decide
each execution. The approval receipt records one first-party user decision,
not an Engine continuation or a reusable permission.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import secrets
from typing import Any
from uuid import uuid4

from padiem_ai_core.pc_device_identity import is_pc_device_id
from padiem_ai_core.agent_approval import MAX_APPROVAL_WINDOW, tool_invocation_digest
from padiem_ai_core.tool_runtime import ToolInvocation

from .history import _row_to_dict, _rows_from_result


MCP_APPROVAL_TTL_SECONDS = int(MAX_APPROVAL_WINDOW.total_seconds())
_OWNER = re.compile(r"usr_[0-9a-f]{32}\Z")
_TOKEN = re.compile(r"mcp_[0-9a-f]{32}\Z")
_APPROVAL = re.compile(r"mcpa_[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN_COLUMNS = "id,name,device_id,created_at,last_used_at,revoked_at"


class McpGatewayStoreError(ValueError):
    pass


def _stamp(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _owner(value):
    if not isinstance(value, str) or not _OWNER.fullmatch(value):
        raise McpGatewayStoreError("Invalid account")
    return value


def mcp_request_digest(tool_name: str, arguments: dict[str, Any]) -> str:
    """Exact tool material only; owner/token/device bind immutable DB columns."""
    if not isinstance(tool_name, str) or not tool_name or not isinstance(arguments, dict):
        raise McpGatewayStoreError("Invalid tool request")
    return tool_invocation_digest(ToolInvocation(tool_id=tool_name, arguments=arguments))


def _public_approval(row):
    return {key: row[key] for key in ("id", "token_id", "token_name", "device_id", "tool_name",
            "request_digest", "created_at", "expires_at", "status")} | {"arguments": json.loads(row["arguments_json"])}


class D1McpGatewayStore:
    def __init__(self, db: Any, *, secret_factory=None):
        if not callable(getattr(db, "prepare", None)):
            raise ValueError("MCP database binding is missing")
        self._db = db
        # Injectable only at application construction, never from an HTTP body.
        self._secret_factory = secret_factory or (lambda: secrets.token_urlsafe(32))

    async def _first(self, sql, *values):
        return _row_to_dict(await self._db.prepare(sql).bind(*values).first())

    async def _all(self, sql, *values):
        return _rows_from_result(await self._db.prepare(sql).bind(*values).run())

    async def _run(self, sql, *values):
        return await self._db.prepare(sql).bind(*values).run()

    async def issue_token(self, *, user_id: str, device_id: str, name: str, now=None) -> dict:
        owner = _owner(user_id)
        if (not is_pc_device_id(device_id) or not isinstance(name, str) or not name.strip()
                or any(ord(c) < 32 for c in name)):
            raise McpGatewayStoreError("Invalid token label or device")
        token_id = "mcp_" + uuid4().hex
        token = token_id + "." + self._secret_factory()
        moment = _stamp(now)
        await self._run("INSERT INTO padiem_mcp_tokens (id,user_id,device_id,name,token_sha256,created_at) VALUES (?,?,?,?,?,?)",
                        token_id, owner, device_id, name.strip(), hashlib.sha256(token.encode()).hexdigest(), moment)
        # The only return containing the credential. Neither list nor audit uses it.
        return {"id": token_id, "name": name.strip(), "device_id": device_id, "created_at": moment,
                "last_used_at": None, "revoked_at": None, "token": token}

    async def list_tokens(self, *, user_id: str) -> list[dict]:
        return await self._all(f"SELECT {_TOKEN_COLUMNS} FROM padiem_mcp_tokens WHERE user_id=? ORDER BY created_at DESC,id", _owner(user_id))

    async def authenticate(self, token: str, *, now=None) -> dict | None:
        if not isinstance(token, str) or len(token) > 256 or "." not in token:
            return None
        token_id, _ = token.split(".", 1)
        if not _TOKEN.fullmatch(token_id):
            return None
        row = await self._first("SELECT id,user_id,device_id,name,token_sha256 FROM padiem_mcp_tokens WHERE id=? AND revoked_at IS NULL", token_id)
        if not row or not hmac.compare_digest(row["token_sha256"], hashlib.sha256(token.encode()).hexdigest()):
            return None
        active = await self._first("UPDATE padiem_mcp_tokens SET last_used_at=? WHERE id=? AND revoked_at IS NULL RETURNING id", _stamp(now), token_id)
        if active is None:
            return None
        return {"token_id": row["id"], "user_id": row["user_id"], "device_id": row["device_id"], "name": row["name"]}

    async def revoke_token(self, *, user_id: str, token_id: str, now=None) -> bool:
        owner = _owner(user_id)
        if not isinstance(token_id, str) or not _TOKEN.fullmatch(token_id):
            return False
        row = await self._first("SELECT id FROM padiem_mcp_tokens WHERE id=? AND user_id=?", token_id, owner)
        if not row:
            return False
        await self._run("UPDATE padiem_mcp_tokens SET revoked_at=COALESCE(revoked_at,?) WHERE id=? AND user_id=?", _stamp(now), token_id, owner)
        return True

    async def create_approval(self, *, identity: dict, tool_name: str, arguments: dict, now=None) -> dict:
        owner = _owner(identity["user_id"])
        moment = now or datetime.now(timezone.utc)
        digest = mcp_request_digest(tool_name, arguments)
        token = await self._first("SELECT id,name FROM padiem_mcp_tokens WHERE id=? AND user_id=? AND device_id=? AND revoked_at IS NULL",
                                  identity["token_id"], owner, identity["device_id"])
        if not token:
            raise McpGatewayStoreError("Credential is unavailable")
        approval_id = "mcpa_" + uuid4().hex
        await self._run("INSERT INTO padiem_mcp_approvals (id,user_id,token_id,device_id,tool_name,arguments_json,request_digest,status,created_at,expires_at) "
                        "VALUES (?,?,?,?,?,?,?,'pending',?,?)", approval_id, owner, token["id"], identity["device_id"], tool_name,
                        json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False), digest,
                        _stamp(moment), _stamp(moment + MAX_APPROVAL_WINDOW))
        return await self.get_approval(user_id=owner, approval_id=approval_id)

    async def get_approval(self, *, user_id: str, approval_id: str) -> dict | None:
        if not isinstance(approval_id, str) or not _APPROVAL.fullmatch(approval_id):
            return None
        row = await self._first("SELECT a.*,t.name AS token_name FROM padiem_mcp_approvals a JOIN padiem_mcp_tokens t ON t.id=a.token_id WHERE a.id=? AND a.user_id=?",
                                approval_id, _owner(user_id))
        return _public_approval(row) if row else None

    async def list_approvals(self, *, user_id: str, now=None) -> list[dict]:
        rows = await self._all("SELECT a.*,t.name AS token_name FROM padiem_mcp_approvals a JOIN padiem_mcp_tokens t ON t.id=a.token_id "
                               "WHERE a.user_id=? AND a.status IN ('pending','approved') AND a.expires_at>? AND t.revoked_at IS NULL ORDER BY a.created_at,a.id",
                               _owner(user_id), _stamp(now))
        return [_public_approval(row) for row in rows]

    async def decide_approval(self, *, user_id: str, approval_id: str, request_digest: str, decision: str, now=None) -> dict | None:
        owner = _owner(user_id)
        if not isinstance(decision, str) or decision not in {"approve", "deny"} or not isinstance(request_digest, str) or not _DIGEST.fullmatch(request_digest):
            raise McpGatewayStoreError("Invalid decision")
        if not isinstance(approval_id, str) or not _APPROVAL.fullmatch(approval_id):
            return None
        # RETURNING makes this owner decision atomic under concurrent requests.
        row = await self._first("UPDATE padiem_mcp_approvals SET status=?,decided_at=? WHERE id=? AND user_id=? "
                                "AND request_digest=? AND status='pending' AND expires_at>? AND EXISTS "
                                "(SELECT 1 FROM padiem_mcp_tokens t WHERE t.id=padiem_mcp_approvals.token_id AND t.revoked_at IS NULL) RETURNING id",
                                "approved" if decision == "approve" else "denied", _stamp(now), approval_id, owner, request_digest, _stamp(now))
        return await self.get_approval(user_id=owner, approval_id=approval_id) if row else None

    async def consume_approval(self, *, identity: dict, approval_id: str, tool_name: str, arguments: dict, now=None) -> dict | None:
        """One exact retry; a lost response cannot replay the approved action."""
        if not isinstance(approval_id, str) or not _APPROVAL.fullmatch(approval_id):
            return None
        digest = mcp_request_digest(tool_name, arguments)
        row = await self._first("UPDATE padiem_mcp_approvals SET status='consumed',consumed_at=? WHERE id=? AND user_id=? "
                                "AND token_id=? AND device_id=? AND tool_name=? AND request_digest=? AND status='approved' AND expires_at>? "
                                "AND EXISTS (SELECT 1 FROM padiem_mcp_tokens t WHERE t.id=padiem_mcp_approvals.token_id AND t.revoked_at IS NULL) RETURNING id,request_digest",
                                _stamp(now), approval_id, _owner(identity["user_id"]), identity["token_id"], identity["device_id"], tool_name, digest, _stamp(now))
        return {"approval_id": row["id"], "request_digest": row["request_digest"]} if row else None

    async def consume_matching_approval(self, *, identity: dict, tool_name: str, arguments: dict, now=None) -> dict | None:
        """Ordinary MCP clients can retry the exact call without private metadata.

        Lookup alone does not authorize execution. The same owner/token/device
        and exact material are rechecked by the atomic one-use claim below.
        Missing, expired and already-consumed receipts all return no approval.
        """
        digest = mcp_request_digest(tool_name, arguments)
        row = await self._first(
            "SELECT id FROM padiem_mcp_approvals WHERE user_id=? AND token_id=? "
            "AND device_id=? AND tool_name=? AND request_digest=? AND status='approved' "
            "AND expires_at>? ORDER BY created_at,id LIMIT 1",
            _owner(identity["user_id"]), identity["token_id"], identity["device_id"],
            tool_name, digest, _stamp(now),
        )
        if row is None:
            return None
        return await self.consume_approval(identity=identity, approval_id=row["id"],
                                           tool_name=tool_name, arguments=arguments, now=now)

    async def audit(self, *, identity: dict, tool_name: str, arguments: dict, status: str, approval_id: str | None = None, now=None) -> str:
        """Record metadata, never credential material or file contents/results."""
        if not isinstance(status, str) or not re.fullmatch(r"[a-z_]{1,64}", status):
            raise McpGatewayStoreError("Invalid audit status")
        event_id = "mcpe_" + uuid4().hex
        await self._run("INSERT INTO padiem_mcp_audit (id,user_id,token_id,device_id,tool_name,request_digest,status,approval_id,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        event_id, _owner(identity["user_id"]), identity["token_id"], identity["device_id"], tool_name,
                        mcp_request_digest(tool_name, arguments), status, approval_id, _stamp(now))
        return event_id
