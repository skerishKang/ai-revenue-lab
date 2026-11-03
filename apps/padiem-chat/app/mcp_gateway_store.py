"""Personal MCP credentials and exact owner-confirmation receipts in Chat's DB.

Credentials authenticate an existing account/device pair; they grant no folder,
command, Connector or Engine entitlement. Existing PC authorities still decide
each execution. The approval receipt records one first-party user decision,
not an Engine continuation or a reusable permission.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
MCP_OAUTH_ACCESS_SECONDS = 3600
MCP_OAUTH_REFRESH_SECONDS = 30 * 24 * 60 * 60
MCP_OAUTH_CODE_SECONDS = 600
_OWNER = re.compile(r"usr_[0-9a-f]{32}\Z")
_TOKEN = re.compile(r"mcp_[0-9a-f]{32}\Z")
_CLIENT = re.compile(r"mcpc_[0-9a-f]{32}\Z")
_APPROVAL = re.compile(r"mcpa_[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN_COLUMNS = "id,name,device_id,created_at,last_used_at,revoked_at,kind,expires_at"


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
        await self._run("INSERT INTO padiem_mcp_tokens (id,user_id,device_id,name,token_sha256,created_at,kind) VALUES (?,?,?,?,?,?,'pat')",
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
        moment = now or datetime.now(timezone.utc)
        stamp = _stamp(moment)
        row = await self._first("SELECT id,user_id,device_id,name,token_sha256,kind,expires_at,resource,scope "
                                "FROM padiem_mcp_tokens WHERE id=? AND revoked_at IS NULL", token_id)
        if not row or not hmac.compare_digest(row["token_sha256"], hashlib.sha256(token.encode()).hexdigest()):
            return None
        expires_at = row.get("expires_at")
        if row.get("kind") == "oauth" and (
                not isinstance(expires_at, str) or expires_at <= stamp):
            return None
        active = await self._first(
            "UPDATE padiem_mcp_tokens SET last_used_at=? WHERE id=? AND revoked_at IS NULL "
            "AND (expires_at IS NULL OR expires_at>?) RETURNING id",
            stamp, token_id, stamp)
        if active is None:
            return None
        return {"token_id": row["id"], "user_id": row["user_id"], "device_id": row["device_id"],
                "name": row["name"], "kind": row.get("kind") or "pat",
                "resource": row.get("resource"), "scope": row.get("scope")}

    async def revoke_token(self, *, user_id: str, token_id: str, now=None) -> bool:
        owner = _owner(user_id)
        if not isinstance(token_id, str) or not _TOKEN.fullmatch(token_id):
            return False
        row = await self._first("SELECT id FROM padiem_mcp_tokens WHERE id=? AND user_id=?", token_id, owner)
        if not row:
            return False
        await self._run("UPDATE padiem_mcp_tokens SET revoked_at=COALESCE(revoked_at,?) WHERE id=? AND user_id=?", _stamp(now), token_id, owner)
        return True

    # --- OAuth 2.1 clients, authorization codes and refreshable grants -----

    @staticmethod
    def _split_oauth_token(token):
        if not isinstance(token, str) or len(token) > 256 or "." not in token:
            return None
        token_id, secret = token.split(".", 1)
        if not _TOKEN.fullmatch(token_id) or not secret:
            return None
        return token_id, secret

    async def register_oauth_client(self, *, client_name: str, redirect_uris: list[str],
                                    token_endpoint_auth_method: str, now=None) -> dict:
        if (not isinstance(client_name, str) or not client_name.strip()
                or not isinstance(redirect_uris, list) or not redirect_uris
                or token_endpoint_auth_method not in {"none", "client_secret_post", "client_secret_basic"}):
            raise McpGatewayStoreError("Invalid OAuth client")
        client_id = "mcpc_" + uuid4().hex
        secret = None if token_endpoint_auth_method == "none" else "mcs_" + secrets.token_urlsafe(32)
        moment = _stamp(now or datetime.now(timezone.utc))
        await self._run(
            "INSERT INTO padiem_mcp_oauth_clients (client_id,client_secret_sha256,client_name,"
            "redirect_uris_json,token_endpoint_auth_method,created_at) VALUES (?,?,?,?,?,?)",
            client_id, None if secret is None else hashlib.sha256(secret.encode()).hexdigest(),
            client_name.strip(), json.dumps(redirect_uris, ensure_ascii=False, separators=(",", ":")),
            token_endpoint_auth_method, moment)
        return {"client_id": client_id, "client_secret": secret, "client_name": client_name.strip(),
                "redirect_uris": list(redirect_uris),
                "token_endpoint_auth_method": token_endpoint_auth_method,
                "client_id_issued_at": moment}

    async def get_oauth_client(self, client_id: str) -> dict | None:
        if not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id):
            return None
        row = await self._first(
            "SELECT client_id,client_secret_sha256,client_name,redirect_uris_json,"
            "token_endpoint_auth_method,created_at,last_used_at "
            "FROM padiem_mcp_oauth_clients WHERE client_id=?", client_id)
        if row is None:
            return None
        try:
            redirect_uris = json.loads(row["redirect_uris_json"])
        except (TypeError, ValueError):
            return None
        if not isinstance(redirect_uris, list) or not all(isinstance(value, str) for value in redirect_uris):
            return None
        return {**row, "redirect_uris": redirect_uris}

    async def touch_oauth_client(self, client_id: str, *, now=None) -> None:
        if not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id):
            return
        await self._run("UPDATE padiem_mcp_oauth_clients SET last_used_at=? WHERE client_id=?",
                        _stamp(now), client_id)

    async def create_oauth_code(self, *, client_id: str, user_id: str, device_id: str,
                                redirect_uri: str, code_challenge: str, scope: str,
                                resource: str, now=None) -> str:
        owner = _owner(user_id)
        if not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id):
            raise McpGatewayStoreError("Invalid OAuth client")
        moment = now or datetime.now(timezone.utc)
        code = "mca_" + secrets.token_urlsafe(32)
        await self._run(
            "INSERT INTO padiem_mcp_oauth_codes (code_sha256,client_id,user_id,device_id,redirect_uri,"
            "code_challenge,code_challenge_method,scope,resource,created_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            hashlib.sha256(code.encode()).hexdigest(), client_id, owner, device_id, redirect_uri,
            code_challenge, "S256", scope, resource, _stamp(moment),
            _stamp(moment + timedelta(seconds=MCP_OAUTH_CODE_SECONDS)))
        return code

    async def consume_oauth_code(self, *, code: str, client_id: str, redirect_uri: str,
                                 now=None) -> dict | None:
        if (not isinstance(code, str) or not code or len(code) > 256
                or not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id)):
            return None
        moment = now or datetime.now(timezone.utc)
        stamp = _stamp(moment)
        row = await self._first(
            "UPDATE padiem_mcp_oauth_codes SET consumed_at=? WHERE code_sha256=? AND client_id=? "
            "AND redirect_uri=? AND consumed_at IS NULL AND expires_at>? "
            "RETURNING user_id,device_id,code_challenge,code_challenge_method,scope,resource",
            stamp, hashlib.sha256(code.encode()).hexdigest(), client_id, redirect_uri, stamp)
        return _row_to_dict(row) if row else None

    async def issue_oauth_tokens(self, *, client_name: str, client_id: str, user_id: str,
                                 device_id: str, scope: str, resource: str, now=None) -> dict:
        owner = _owner(user_id)
        if not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id):
            raise McpGatewayStoreError("Invalid OAuth client")
        if not is_pc_device_id(device_id):
            raise McpGatewayStoreError("Invalid OAuth device")
        moment = now or datetime.now(timezone.utc)
        token_id = "mcp_" + uuid4().hex
        access_secret = secrets.token_urlsafe(32)
        refresh_secret = secrets.token_urlsafe(32)
        name = ((client_name.strip()[:96] if isinstance(client_name, str) and client_name.strip()
                 else "MCP OAuth") + " (OAuth)")
        access_token = token_id + "." + access_secret
        refresh_token = token_id + "." + refresh_secret
        access_expires = moment + timedelta(seconds=MCP_OAUTH_ACCESS_SECONDS)
        refresh_expires = moment + timedelta(seconds=MCP_OAUTH_REFRESH_SECONDS)
        await self._run(
            "INSERT INTO padiem_mcp_tokens (id,user_id,device_id,name,token_sha256,created_at,kind,"
            "expires_at,refresh_token_sha256,refresh_expires_at,client_id,scope,resource) "
            "VALUES (?,?,?,?,?,?,'oauth',?,?,?,?,?,?)",
            token_id, owner, device_id, name,
            hashlib.sha256(access_token.encode()).hexdigest(), _stamp(moment),
            _stamp(access_expires), hashlib.sha256(refresh_token.encode()).hexdigest(),
            _stamp(refresh_expires), client_id, scope, resource)
        return {"access_token": access_token, "refresh_token": refresh_token,
                "token_type": "Bearer", "expires_in": MCP_OAUTH_ACCESS_SECONDS,
                "scope": scope, "resource": resource}

    async def refresh_oauth_tokens(self, *, refresh_token: str, client_id: str, now=None) -> dict | None:
        split = self._split_oauth_token(refresh_token)
        if split is None or not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id):
            return None
        token_id, provided = split
        moment = now or datetime.now(timezone.utc)
        stamp = _stamp(moment)
        row = await self._first(
            "SELECT id,user_id,device_id,name,refresh_token_sha256,refresh_expires_at,client_id,"
            "scope,resource,revoked_at,kind FROM padiem_mcp_tokens WHERE id=? AND client_id=? AND kind='oauth'",
            token_id, client_id)
        if (row is None or row.get("revoked_at") is not None
                or not isinstance(row.get("refresh_token_sha256"), str)
                or not hmac.compare_digest(row["refresh_token_sha256"], hashlib.sha256(refresh_token.encode()).hexdigest())
                or not isinstance(row.get("refresh_expires_at"), str)
                or row["refresh_expires_at"] <= stamp):
            return None
        access_secret = secrets.token_urlsafe(32)
        refresh_secret = secrets.token_urlsafe(32)
        access_token = token_id + "." + access_secret
        new_refresh = token_id + "." + refresh_secret
        access_expires = _stamp(moment + timedelta(seconds=MCP_OAUTH_ACCESS_SECONDS))
        refresh_expires = _stamp(moment + timedelta(seconds=MCP_OAUTH_REFRESH_SECONDS))
        rotated = await self._first(
            "UPDATE padiem_mcp_tokens SET token_sha256=?,refresh_token_sha256=?,expires_at=?,"
            "refresh_expires_at=?,last_used_at=? WHERE id=? AND client_id=? AND kind='oauth' "
            "AND refresh_token_sha256=? AND revoked_at IS NULL AND refresh_expires_at>? RETURNING id",
            hashlib.sha256(access_token.encode()).hexdigest(),
            hashlib.sha256(new_refresh.encode()).hexdigest(), access_expires,
            refresh_expires, stamp, token_id, client_id, row["refresh_token_sha256"], stamp)
        if rotated is None:
            return None
        return {"access_token": access_token, "refresh_token": new_refresh,
                "token_type": "Bearer", "expires_in": MCP_OAUTH_ACCESS_SECONDS,
                "scope": row.get("scope"), "resource": row.get("resource")}

    async def revoke_oauth_token(self, *, token: str, client_id: str, now=None) -> bool:
        split = self._split_oauth_token(token)
        if split is None or not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id):
            return False
        token_id, _ = split
        row = await self._first(
            "SELECT id,token_sha256,refresh_token_sha256 FROM padiem_mcp_tokens "
            "WHERE id=? AND client_id=? AND kind='oauth'", token_id, client_id)
        if row is None:
            return False
        digest = hashlib.sha256(token.encode()).hexdigest()
        matches = (isinstance(row.get("token_sha256"), str)
                   and hmac.compare_digest(row["token_sha256"], digest)) or (
                   isinstance(row.get("refresh_token_sha256"), str)
                   and hmac.compare_digest(row["refresh_token_sha256"], digest))
        if not matches:
            return False
        await self._run("UPDATE padiem_mcp_tokens SET revoked_at=COALESCE(revoked_at,?) WHERE id=?",
                        _stamp(now), token_id)
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

    async def audit(self, *, identity: dict, tool_name: str, arguments: dict, status: str,
                    approval_id: str | None = None, now=None,
                    exit_code: int | None = None, duration_ms: int | None = None,
                    output_bytes: int | None = None,
                    output_truncated: bool | None = None) -> str:
        """Record metadata, never credential material or file contents/results."""
        if not isinstance(status, str) or not re.fullmatch(r"[a-z_]{1,64}", status):
            raise McpGatewayStoreError("Invalid audit status")
        if exit_code is not None and (
                not isinstance(exit_code, int) or isinstance(exit_code, bool)):
            raise McpGatewayStoreError("Invalid audit metadata")
        for value in (duration_ms, output_bytes):
            if value is not None and (
                    not isinstance(value, int) or isinstance(value, bool) or value < 0):
                raise McpGatewayStoreError("Invalid audit metadata")
        if output_truncated is not None and not isinstance(output_truncated, bool):
            raise McpGatewayStoreError("Invalid audit metadata")
        event_id = "mcpe_" + uuid4().hex
        await self._run("INSERT INTO padiem_mcp_audit (id,user_id,token_id,device_id,tool_name,request_digest,status,approval_id,created_at,exit_code,duration_ms,output_bytes,output_truncated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        event_id, _owner(identity["user_id"]), identity["token_id"], identity["device_id"], tool_name,
                        mcp_request_digest(tool_name, arguments), status, approval_id, _stamp(now),
                        exit_code, duration_ms, output_bytes,
                        None if output_truncated is None else int(output_truncated))
        return event_id
