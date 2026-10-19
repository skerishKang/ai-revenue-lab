"""B66 administrator and membership authority over the existing PADIEM_CHAT_DB.

Never use browser-submitted email/role/admin flags as authority. The single initial
administrator is the *verified Google subject* of the named owner account.
A password registration (including one with the same email) never grants admin.
Feature activation is separate from migration and public UI rollout.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .history import _row_to_dict, _rows_from_result, _user_id

_TIERS = frozenset(("FREE", "PLUS", "PRO", "MAX"))
_STATES = frozenset(("pending", "approved", "suspended"))
_UID = re.compile(r"^usr_[a-f0-9]{32}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class MemberMissing(Exception):
    pass


class MemberConflict(Exception):
    pass


class D1B66MemberAdminStore:
    def __init__(self, db: Any, *, admin_email: str = ""):
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("D1 membership binding missing")
        self.db = db
        # Trusted Worker binding only, never an email sent by the browser.
        self.admin_email = (admin_email or "").strip().lower() if isinstance(admin_email, str) else ""

    def _statement(self, sql: str, *params: Any) -> Any:
        stmt = self.db.prepare(sql)
        return stmt.bind(*params) if params else stmt

    async def _first(self, sql: str, *params: Any) -> dict[str, Any] | None:
        return _row_to_dict(await self._statement(sql, *params).first())

    async def _all(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        return _rows_from_result(await self._statement(sql, *params).run())

    async def is_google_admin(self, user_id: str) -> bool:
        if not isinstance(user_id, str) or not _UID.fullmatch(user_id) or not self.admin_email:
            return False
        row = await self._first(
            "SELECT u.provider_subject FROM users u "
            "LEFT JOIN password_credentials pc ON pc.user_id=u.id "
            "WHERE u.id=? AND u.auth_provider='google' "
            "AND lower(u.email)=? AND pc.user_id IS NULL LIMIT 1",
            user_id, self.admin_email,
        )
        subject = row.get("provider_subject") if row else None
        # The ID is derived from the Google-verified provider subject, not
        # from a client email or a password-account compatibility row.
        return bool(
            isinstance(subject, str)
            and subject and not subject.startswith("password:")
            and _user_id(subject) == user_id
        )

    @staticmethod
    def _member_filters(
        query: str = "", status: str = "all", tier: str = "all"
    ) -> tuple[str, tuple[str, ...]]:
        if (not isinstance(query, str) or len(query) > 80
            or any(ord(c) < 32 for c in query)
            or status not in {"all", "pending", "approved", "suspended"}
            or tier not in {"all", "FREE", "PLUS", "PRO", "MAX"}):
            raise ValueError("invalid member filter")
        clauses: list[str] = []
        params: list[str] = []
        if query.strip():
            clauses.append("(instr(lower(u.email),lower(?)) > 0 "
                           "OR instr(lower(u.display_name),lower(?)) > 0)")
            params.extend((query.strip(), query.strip()))
        if status != "all":
            clauses.append("m.status=?")
            params.append(status)
        if tier != "all":
            clauses.append("m.tier=?")
            params.append(tier)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", tuple(params)

    async def list_members(
        self, *, limit: int = 50, offset: int = 0,
        query: str = "", status: str = "all", tier: str = "all"
    ) -> list[dict[str, Any]]:
        limit = min(max(int(limit), 1), 100)
        offset = min(max(int(offset), 0), 10000)
        where, params = self._member_filters(query=query, status=status, tier=tier)
        rows = await self._all(
            "SELECT u.id AS user_id, u.email, u.display_name, u.created_at, "
            "m.status, m.tier, m.revision, m.updated_at AS access_updated_at "
            "FROM users u JOIN b66_memberships m ON m.user_id=u.id "
            + where +
            " ORDER BY CASE m.status WHEN 'pending' THEN 0 ELSE 1 END, "
            "u.created_at DESC LIMIT ? OFFSET ?",
            *params, limit, offset,
        )
        return [
            {
                "user_id": str(row["user_id"]),
                "email": str(row["email"]),
                "name": str(row.get("display_name") or ""),
                "created_at": str(row["created_at"]),
                "status": str(row["status"]),
                "tier": str(row["tier"]),
                "revision": int(row["revision"]),
            }
            for row in rows
        ]

    async def count_filtered_members(
        self, *, query: str = "", status: str = "all", tier: str = "all"
    ) -> int:
        where, params = self._member_filters(query=query, status=status, tier=tier)
        row = await self._first(
            "SELECT count(*) AS n FROM users u "
            "JOIN b66_memberships m ON m.user_id=u.id" + where,
            *params,
        )
        return int(row["n"]) if row else 0

    async def member_detail(self, user_id: str) -> dict[str, Any] | None:
        """Admin-only usage metadata; no message, quote text or provider payload.

        Global usage buckets cover all Padiem Chat AI requests, not B66-only
        completed model requests. Never mislabel them as model-specific events.
        """
        if not isinstance(user_id,str) or not _UID.fullmatch(user_id):
            return None
        member = await self._first(
            "SELECT u.id AS user_id,u.email,u.display_name,u.created_at,"
            "m.status,m.tier,m.revision FROM users u "
            "JOIN b66_memberships m ON m.user_id=u.id WHERE u.id=?",
            user_id,
        )
        if member is None:
            return None
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).date()
        cutoff = (now - datetime.timedelta(days=29)).isoformat()
        rows = await self._all(
            "SELECT substr(bucket_start,1,10) AS day, SUM(request_count) AS n "
            "FROM live_usage_buckets "
            "WHERE subject_type='user' AND subject_key=? AND bucket_type='day' "
            "AND substr(bucket_start,1,10)>=? "
            "GROUP BY substr(bucket_start,1,10) ORDER BY day DESC",
            user_id, cutoff,
        )
        by_day = {
            str(row["day"]):int(row["n"]) for row in rows
            if isinstance(row.get("day"),str) and row.get("n") is not None
        }
        def total(days: int) -> int:
            return sum(count for day,count in by_day.items()
                       if day >= (now-datetime.timedelta(days=days-1)).isoformat())
        quote_row = await self._first(
            "SELECT count(*) AS n, MAX(updated_at) AS latest "
            "FROM b66_quote_history WHERE user_id=?",user_id,
        )
        quotes = await self._all(
            "SELECT created_at,updated_at FROM b66_quote_history "
            "WHERE user_id=? ORDER BY updated_at DESC LIMIT 12",user_id,
        )
        changes = await self._all(
            "SELECT previous_status,previous_tier,current_status,current_tier,changed_at "
            "FROM b66_membership_audit WHERE user_id=? "
            "ORDER BY changed_at DESC LIMIT 20",user_id,
        )
        return {
            "member":{
                "user_id":str(member["user_id"]),
                "email":str(member["email"]),
                "name":str(member.get("display_name") or ""),
                "created_at":str(member["created_at"]),
                "status":str(member["status"]),
                "tier":str(member["tier"]),
                "revision":int(member["revision"]),
            },
            "usage":{
                "scope":"padiem_chat_all_ai_requests",
                "metric":"daily_quota_request_count",
                "today":total(1),"last_7_days":total(7),
                "last_30_days":total(30),
                "daily":[{"date":day,"requests":n} for day,n in sorted(by_day.items())],
                "model_breakdown_available":False,
            },
            "quotes":{
                "saved_count":int(quote_row["n"]) if quote_row else 0,
                "latest_saved_at":quote_row.get("latest") if quote_row else None,
                "recent":[{"created_at":r["created_at"],"updated_at":r["updated_at"]}
                          for r in quotes],
            },
            "changes":[{
                "at":r["changed_at"],
                "from_status":r["previous_status"],"from_tier":r["previous_tier"],
                "to_status":r["current_status"],"to_tier":r["current_tier"],
            } for r in changes],
        }

    async def count_members(self) -> dict[str, int]:
        rows = await self._all(
            "SELECT status, COUNT(*) AS count FROM b66_memberships GROUP BY status"
        )
        return {state: next((int(row["count"]) for row in rows if row["status"] == state), 0)
                for state in ("pending", "approved", "suspended")}

    async def access_for_user(self, user_id: str) -> dict[str, Any] | None:
        if not isinstance(user_id, str) or not _UID.fullmatch(user_id):
            return None
        return await self._first(
            "SELECT status, tier, revision FROM b66_memberships WHERE user_id=?",
            user_id,
        )

    async def set_access(
        self, *, actor_id: str, user_id: str, status: str,
        tier: str, expected_revision: int
    ) -> dict[str, Any]:
        if (not isinstance(user_id, str) or not _UID.fullmatch(user_id)
            or not isinstance(actor_id, str) or not _UID.fullmatch(actor_id)
            or status not in _STATES or tier not in _TIERS
            or type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("invalid access assignment")
        before = await self.access_for_user(user_id)
        if before is None:
            raise MemberMissing()
        if int(before["revision"]) != expected_revision:
            raise MemberConflict()
        if before["status"] == status and before["tier"] == tier:
            return {"status": status, "tier": tier, "revision": expected_revision}
        new_revision = expected_revision + 1
        now = _now()
        # Updating a member and writing the immutable change receipt are one
        # Cloudflare D1 batch transaction; the audit SELECT inserts only if
        # the compare-and-swap revision update succeeded.
        batch = getattr(self.db, "batch", None)
        if not callable(batch):
            raise RuntimeError("D1 batch required for audited access writes")
        update = self._statement(
            "UPDATE b66_memberships SET status=?,tier=?,revision=?,granted_by=?,updated_at=? "
            "WHERE user_id=? AND revision=?",
            status, tier, new_revision, actor_id, now, user_id, expected_revision,
        )
        audit = self._statement(
            "INSERT INTO b66_membership_audit "
            "(audit_id,user_id,actor_user_id,previous_status,previous_tier,"
            "current_status,current_tier,revision,changed_at) "
            "SELECT ?,user_id,?,?,?,?,?,?,? FROM b66_memberships "
            "WHERE user_id=? AND revision=?",
            "b66audit_" + uuid.uuid4().hex, actor_id,
            str(before["status"]), str(before["tier"]),
            status, tier, new_revision, now, user_id, new_revision,
        )
        result = await batch([update, audit])
        update_meta = getattr(result[0], "meta", None) if result else None
        if isinstance(update_meta, dict) and update_meta.get("changes") == 0:
            raise MemberConflict()
        after = await self.access_for_user(user_id)
        if after is None or int(after["revision"]) != new_revision:
            raise MemberConflict()
        return {"status": status, "tier": tier, "revision": new_revision}

    async def undelivered_signups(self) -> int:
        row = await self._first(
            "SELECT count(*) AS n FROM b66_signup_alert_outbox WHERE delivered_at IS NULL"
        )
        return int(row["n"]) if row else 0

    async def model_policy(self) -> dict[str, Any]:
        row = await self._first(
            "SELECT revision,active FROM b66_model_access_policy WHERE id='b66'"
        )
        if row is None:
            raise RuntimeError("model policy migration missing")
        grants = await self._all(
            "SELECT tier,model_id FROM b66_tier_model_grants ORDER BY tier,model_id"
        )
        tiers: dict[str, list[str]] = {tier: [] for tier in ("FREE","PLUS","PRO","MAX")}
        for grant in grants:
            tier = grant.get("tier")
            model_id = grant.get("model_id")
            if tier in tiers and isinstance(model_id, str):
                tiers[tier].append(model_id)
        disabled = await self._all(
            "SELECT model_id FROM b66_disabled_models ORDER BY model_id"
        )
        return {
            "revision": int(row["revision"]),
            "active": int(row["active"]) == 1,
            "tiers": tiers,
            "disabled_models": sorted({
                str(item["model_id"]) for item in disabled
                if isinstance(item.get("model_id"), str)
            }),
        }

    async def globally_disabled_models(self) -> frozenset[str]:
        """D1-owned OFF list independent of the separate membership/tier rollout.

        Model IDs come from the authenticated admin's registered-model policy.
        Missing/unavailable D1 raises; the production route must fail closed.
        """
        rows = await self._all(
            "SELECT model_id FROM b66_disabled_models ORDER BY model_id"
        )
        result: set[str] = set()
        for row in rows:
            model_id = row.get("model_id")
            if not isinstance(model_id, str) or not model_id:
                raise RuntimeError("invalid persisted disabled model ID")
            result.add(model_id)
        return frozenset(result)

    async def runtime_access(self, user_id: str) -> dict[str, Any] | None:
        access = await self.access_for_user(user_id)
        if access is None:
            return None
        status = str(access["status"])
        tier = str(access["tier"])
        if status != "approved" or tier not in _TIERS:
            return {"status": status, "tier": tier, "active_policy": False, "model_ids": []}
        policy = await self.model_policy()
        disabled = policy["disabled_models"]
        return {
            "status": status, "tier": tier,
            "active_policy": bool(policy["active"]),
            "disabled_models": disabled,
            "model_ids": [
                model for model in policy["tiers"][tier] if model not in disabled
            ] if policy["active"] else None,
        }

    async def set_model_policy(
        self, *, actor_id: str, expected_revision: int, active: bool,
        tiers: dict[str, list[str]], registered_models: set[str],
        disabled_models: list[str] | None = None
    ) -> dict[str, Any]:
        if (type(expected_revision) is not int or expected_revision < 0
            or type(active) is not bool
            or not isinstance(tiers, dict) or set(tiers) != _TIERS
            or not isinstance(registered_models, set)
            or not registered_models):
            raise ValueError("invalid model policy")
        # A model can be switched OFF globally independently of each tier's
        # checkbox. Only trusted B14-listed IDs may be persisted or disabled.
        if disabled_models is None:
            disabled_models = []
        if (not isinstance(disabled_models, list) or len(disabled_models) > 100
            or any(not isinstance(mid, str) or mid not in registered_models
                   for mid in disabled_models)
            or len(disabled_models) != len(set(disabled_models))):
            raise ValueError("model switch contains unsupported IDs")
        disabled = set(disabled_models)
        grants: list[tuple[str, str]] = []
        for tier, ids in tiers.items():
            if (not isinstance(ids, list) or len(ids) > 50
                or any(not isinstance(mid, str) or mid not in registered_models for mid in ids)
                or len(ids) != len(set(ids))):
                raise ValueError("model ID is not registered/live-ready")
            grants.extend((tier, mid) for mid in ids)
        if active and not any(mid not in disabled for mid in tiers["FREE"]):
            raise ValueError("FREE tier must have an ON model before activation")
        previous = await self.model_policy()
        if previous["revision"] != expected_revision:
            raise MemberConflict()
        batch = getattr(self.db, "batch", None)
        if not callable(batch):
            raise RuntimeError("D1 atomic batch required")
        rev, now = expected_revision + 1, _now()
        statements = [
            self._statement(
                "UPDATE b66_model_access_policy SET revision=?,active=?,changed_by=?,updated_at=? "
                "WHERE id='b66' AND revision=?",
                rev, int(active), actor_id, now, expected_revision
            ),
            self._statement(
                "DELETE FROM b66_tier_model_grants WHERE "
                "(SELECT revision FROM b66_model_access_policy WHERE id='b66')=?",
                rev
            ),
            self._statement(
                "DELETE FROM b66_disabled_models WHERE "
                "(SELECT revision FROM b66_model_access_policy WHERE id='b66')=?",
                rev
            )
        ]
        for model_id in sorted(disabled):
            statements.append(self._statement(
                "INSERT INTO b66_disabled_models(model_id) "
                "SELECT ? WHERE "
                "(SELECT revision FROM b66_model_access_policy WHERE id='b66')=?",
                model_id, rev,
            ))
        for tier, model_id in grants:
            statements.append(self._statement(
                "INSERT INTO b66_tier_model_grants (tier,model_id) "
                "SELECT ?,? WHERE (SELECT revision FROM b66_model_access_policy WHERE id='b66')=?",
                tier, model_id, rev
            ))
        statements.append(self._statement(
            "INSERT INTO b66_model_policy_audit (audit_id,actor_user_id,revision,active,changed_at) "
            "SELECT ?,?,?,?,? WHERE (SELECT revision FROM b66_model_access_policy WHERE id='b66')=?",
            "b66policy_" + uuid.uuid4().hex, actor_id, rev, int(active), now, rev
        ))
        await batch(statements)
        confirmed = await self.model_policy()
        if confirmed["revision"] != rev or confirmed["tiers"] != {
            k: sorted(v) for k,v in tiers.items()
        } or confirmed["active"] != active or confirmed["disabled_models"] != sorted(disabled):
            raise MemberConflict()
        return confirmed

    async def signup_alert_candidates(self, limit: int = 10) -> list[str]:
        rows = await self._all(
            "SELECT user_id FROM b66_signup_alert_outbox "
            "WHERE delivered_at IS NULL ORDER BY created_at ASC LIMIT ?",
            min(20, max(1, int(limit))),
        )
        return [str(r["user_id"]) for r in rows if _UID.fullmatch(str(r.get("user_id") or ""))]

    async def pending_signup_for_user(self, user_id: str) -> bool:
        if not _UID.fullmatch(user_id or ""):
            return False
        row = await self._first(
            "SELECT user_id FROM b66_signup_alert_outbox "
            "WHERE user_id=? AND delivered_at IS NULL",
            user_id,
        )
        return row is not None

    async def delivered_signup_channel(self, user_id: str, channel: str) -> bool:
        if not _UID.fullmatch(user_id or "") or channel not in ("telegram","discord","email"):
            return False
        row = await self._first(
            "SELECT user_id FROM b66_signup_alert_delivery WHERE user_id=? AND channel=?",
            user_id,channel,
        )
        return row is not None

    async def record_signup_alert_channel(self, user_id: str, channel: str) -> None:
        if not _UID.fullmatch(user_id or "") or channel not in ("telegram","discord","email"):
            raise ValueError("invalid alert receipt")
        await self._statement(
            "INSERT OR IGNORE INTO b66_signup_alert_delivery(user_id,channel,delivered_at) "
            "VALUES(?,?,?)",user_id,channel,_now(),
        ).run()

    async def finalize_signup_alert(self, user_id: str, channels: tuple[str, ...]) -> bool:
        if not channels or not _UID.fullmatch(user_id or ""):
            return False
        for channel in channels:
            if not await self.delivered_signup_channel(user_id,channel):
                return False
        await self._statement(
            "UPDATE b66_signup_alert_outbox SET delivered_at=? "
            "WHERE user_id=? AND delivered_at IS NULL",
            _now(),user_id,
        ).run()
        return True
