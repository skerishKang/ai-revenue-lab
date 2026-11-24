"""메시 배포 (#7813 H7-1, H7-2).

`app/history.py`의 `D1HistoryStore`에서 위치만 옮긴 Oracle 메시 디스패치의
생성·청구·취소·소비·원본 보관·노드 상태 메서드다. 동작·응답 형식·DB 쿼리 결과는
변하지 않으며, 기존 경로는 `app/history.py`가 `D1HistoryStore`를 조합으로 다시
내보낸다. 이 모듈은 `history.py`를 모듈 수준에서 import 하지 않는다.
"""
from __future__ import annotations

import hashlib
import inspect
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .history_constants import ORACLE_MESH_CLAIMABLE_SQL, ORACLE_MESH_CLAIM_LEASE_SECONDS, ORACLE_MESH_UNREDELIVERABLE_SQL
from .history_errors import HistoryError, HistoryForbidden
from .history_mesh_original import MAX_MESH_PATH_CHARS, MAX_MESH_REFERENCE_CHARS, MAX_MESH_ROW_BYTES, ORACLE_MESH_ORIGINAL_MAX_BYTES, _MESH_PATH_FIELDS, _oracle_mesh_original_max_bytes
from .history_rows import _changed_rows, _tagged
from .history_text import _iso, _lane_count_age, _lane_node, _now_iso
from .history_store_core import StoreCore
from padiem_ai_core.pc_device_identity import is_pc_device_id


class MeshDispatchStore(StoreCore):
    """메시 디스패치 생성·청구·취소 (P구역 첫 묶음)."""

    async def create_oracle_mesh_dispatch(
        self,
        *,
        user_id: str,
        run_id: str,
        command_id: str,
        tool_request_ref: str,
        request_id: str,
        revision_ref: str,
        evidence_ref: str | None,
        request_fingerprint: str,
        account_ref: str,
        workspace_ref: str,
        device_id: str,
        binding_ref: str | None,
        node_ref: str,
        root_ref: str,
        path_relative: str,
        file_path: str,
        expires_at: str,
        kind: str = "read",
        command_text: str | None = None,
        tool_call_ref: str | None = None,
        user_mode: bool = False,
        read_only: bool | None = None,
        share_roots: list[str] | None = None,
    ) -> dict[str, Any]:
        """#4139 — stage one Oracle management-host execution for one run.

        The row snapshots the broker-bound correlation when Broker admission
        exists, plus the deployment-verified Mesh target. An identical pending
        row is reused, a terminal (done/failed) row refuses any second
        execution of the *same* correlation, and an expired pending row is
        replaced. Every statement is owner-scoped; cross-owner existence is
        never disclosed.

        ``tool_call_ref`` narrows the correlation key from the legacy one
        dispatch per owner+run to one dispatch per tool call inside that run.
        A bounded multi-tool turn (for example list then read) therefore stages
        a distinct row for each call, while re-staging the exact same call still
        finds its terminal row and refuses a second execution.

        The stored ``tool_call_ref`` (NULL for the legacy lane) is what 063's
        indexes enforce, and it is the database — not this read-then-write —
        that decides a concurrent staging: the loser of an INSERT race re-reads
        the winner's row and returns it only when it is the same payload, never
        when a different call won. The legacy lane is correlated to the
        run-scoped rows only, so a trusted file call staged in the same run is
        never selected, reused or replaced by it; the trusted lane keeps
        correlating on ``tool_request_ref`` so a row written before 063 (which
        has no scope column) is still found and still refuses a replay.

        ``evidence_ref`` and ``binding_ref`` are nullable on purpose. A PC that
        has never completed the native PC offer has no Broker binding and no
        Broker-minted evidence, and this table stores NULL for both rather than
        inventing a reference that would read as one.
        """
        if read_only is not None and type(read_only) is not bool:
            raise HistoryError("read_only must be a boolean or null")
        read_only_flag = None if read_only is None else (1 if read_only else 0)
        # #8037: the server-declared share addresses of this command. They ride
        # the staging call, never a caller value, and are echoed on the claimed
        # row so the executor can bound a share command without a schema column.
        if share_roots is not None and (
            not isinstance(share_roots, list)
            or any(
                not isinstance(item, str) or not item or len(item) > 32000
                or any(ord(ch) < 32 for ch in item)
                for item in share_roots
            )
        ):
            raise HistoryError("share_roots must be bounded path strings")
        fields = {
            "user_id": user_id, "run_id": run_id, "command_id": command_id,
            "tool_request_ref": tool_request_ref, "request_id": request_id,
            "revision_ref": revision_ref, "evidence_ref": evidence_ref,
            "request_fingerprint": request_fingerprint,
            "account_ref": account_ref, "workspace_ref": workspace_ref,
            "device_id": device_id, "binding_ref": binding_ref,
            "node_ref": node_ref, "root_ref": root_ref,
            "path_relative": path_relative, "file_path": file_path,
            "kind": kind, "command_text": command_text,
        }
        if kind not in ("read", "command", "desktop"):
            raise HistoryError("kind must be read, command or desktop")
        if kind in ("command", "desktop"):
            # #4139 terminal lane: the command is the execution target, so it is
            # mandatory and it is ordinary text — Korean, quotes, tabs and
            # several lines. There is no product length rule; the bound is the
            # row it is written into. Only the characters that break the lane
            # are refused: NUL and the other C0 controls except tab and LF
            # (CR is refused because the exit-code sentinel is parsed per line).
            # The desktop lane carries its op in the same field
            # (``desktop:<op>`` plus an optional argument line) under the same
            # text rules, verified again by the executor before the PC acts.
            if not isinstance(command_text, str) or not command_text.strip():
                raise HistoryError("command_text is required for a command dispatch")
            if any(
                ord(ch) < 32 and ch not in "\t\n" for ch in command_text
            ) or "\x7f" in command_text:
                raise HistoryError("command_text carries a control character")
        elif command_text is not None:
            raise HistoryError("command_text is only valid for a command dispatch")
        for name, value in fields.items():
            if value is None:
                if name not in ("evidence_ref", "binding_ref", "command_text"):
                    raise HistoryError(f"{name} must be a bounded reference")
                continue
            if not isinstance(value, str) or not value:
                raise HistoryError(f"{name} must be a bounded reference")
            if name in _MESH_PATH_FIELDS:
                if len(value) > MAX_MESH_PATH_CHARS:
                    raise HistoryError(f"{name} exceeds the Windows path bound")
                if any(ord(ch) < 32 for ch in value):
                    raise HistoryError(f"{name} carries a control character")
                continue
            if name == "command_text":
                continue  # text, not a reference: bounded by the row below
            if len(value) > MAX_MESH_REFERENCE_CHARS:
                raise HistoryError(f"{name} must be a bounded reference")
        row_bytes = sum(
            len(value.encode("utf-8"))
            for value in fields.values() if isinstance(value, str)
        )
        if row_bytes > MAX_MESH_ROW_BYTES:
            raise HistoryError("oracle mesh dispatch row exceeds the storage row bound")
        if not isinstance(expires_at, str) or not expires_at:
            raise HistoryError("expires_at must be a bounded timestamp")
        if tool_call_ref is not None:
            if (
                not isinstance(tool_call_ref, str)
                or not tool_call_ref
                or len(tool_call_ref) > 128
                or any(ord(ch) < 33 or ord(ch) > 126 for ch in tool_call_ref)
            ):
                raise HistoryError(
                    "tool_call_ref must be a bounded safe reference"
                )
            correlation_sql = "user_id=? AND run_id=? AND tool_request_ref=?"
            correlation_params = (user_id, run_id, tool_call_ref)
        else:
            # The legacy single-command lane owns the run-scoped rows and
            # nothing else. Selecting by run alone would read a trusted file
            # call of the same run as if it were the legacy dispatch, and an
            # expired pending file row would then be replaced — losing the
            # file call's own replay protection.
            correlation_sql = "user_id=? AND run_id=? AND tool_call_ref IS NULL"
            correlation_params = (user_id, run_id)
        # The owner is established by the layer that holds the run rows: on D1 that is
        # `claw_run_history`; on the 컴2 queue it is the Worker, whose route already fetched
        # this run for this user and answered 404 before forwarding (see `run_ownership`).
        if not await self._run_is_owned(run_id, user_id):
            raise HistoryForbidden("claw run is not owned by current user")
        existing = await self._first(
            "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, revision_ref, "
            "evidence_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
            "binding_ref, node_ref, root_ref, path_relative, file_path, nonce_sha256, "
            f"state, expires_at, COALESCE(user_mode,0) AS user_mode FROM oracle_mesh_dispatch WHERE {correlation_sql}",
            *correlation_params,
        )
        def same_payload(row: dict[str, Any]) -> bool:
            return all(
                row.get(name) == value
                for name, value in fields.items()
                if name not in ("user_id", "run_id")
            )

        now = _now_iso()
        if existing is not None:
            same = same_payload(existing)
            if same and existing.get("state") == "pending" and existing.get("expires_at", "") > now:
                return {**dict(existing), **({"share_roots": list(share_roots)} if share_roots else {})}
            if same and existing.get("state") in ("done", "failed"):
                raise HistoryError("oracle mesh run already executed")
            if not (existing.get("state") == "pending" and existing.get("expires_at", "") <= now):
                raise HistoryError("oracle mesh run already dispatched")
            if kind in ("command", "desktop") and (
                existing.get("nonce_sha256") is not None
                or existing.get("state") in ("received", "store_failed")
            ):
                # A terminal command — or a desktop input, which also mutates
                # the PC — may ALREADY have run: the row was handed to the
                # executor (a nonce was minted) or its result was received but
                # never stored. Re-staging it would let a restart execute the
                # same action again, so the row is left exactly as it is — an
                # uncertain state, never a silent second execution.
                raise HistoryError("oracle mesh command execution is uncertain")
            await self._run(
                "UPDATE oracle_mesh_dispatch SET command_id=?, tool_request_ref=?, "
                "request_id=?, revision_ref=?, evidence_ref=?, request_fingerprint=?, "
                "account_ref=?, workspace_ref=?, device_id=?, binding_ref=?, node_ref=?, "
                "root_ref=?, path_relative=?, file_path=?, kind=?, command_text=?, "
                "tool_call_ref=?, user_mode=?, read_only=?, nonce_sha256=NULL, "
                "claimed_until=NULL, state=?, expires_at=?, created_at=? WHERE "
                f"{correlation_sql} AND state=? AND expires_at<=?",
                command_id, tool_request_ref, request_id, revision_ref,
                evidence_ref, request_fingerprint, account_ref, workspace_ref,
                device_id, binding_ref, node_ref, root_ref, path_relative,
                file_path, kind, command_text, tool_call_ref, 1 if user_mode else 0,
                read_only_flag, "pending", expires_at, now,
                *correlation_params, "pending", now,
            )
            replaced = await self._first(
                "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, revision_ref, "
                "evidence_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
                "binding_ref, node_ref, root_ref, path_relative, file_path, nonce_sha256, "
                f"state, expires_at, COALESCE(user_mode,0) AS user_mode FROM oracle_mesh_dispatch WHERE {correlation_sql}",
                *correlation_params,
            )
            if replaced is None:
                raise HistoryError("oracle mesh dispatch unavailable")
            return {**dict(replaced), **({"share_roots": list(share_roots)} if share_roots else {})}
        dispatch_id = "dsp_" + uuid.uuid4().hex
        try:
            await self._run(
                "INSERT INTO oracle_mesh_dispatch "
                "(dispatch_id, user_id, run_id, command_id, tool_request_ref, request_id, "
                "revision_ref, evidence_ref, request_fingerprint, account_ref, workspace_ref, "
                "device_id, binding_ref, node_ref, root_ref, path_relative, file_path, "
                "kind, command_text, tool_call_ref, "
                "read_only, nonce_sha256, state, expires_at, created_at, user_mode) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                dispatch_id, user_id, run_id, command_id, tool_request_ref,
                request_id, revision_ref, evidence_ref, request_fingerprint,
                account_ref, workspace_ref, device_id, binding_ref, node_ref,
                root_ref, path_relative, file_path, kind, command_text,
                tool_call_ref, read_only_flag, "pending", expires_at, now,
                1 if user_mode else 0,
            )
        except Exception:
            # 063 makes the database the decider of a concurrent staging: two
            # requests can both read no row and then race to INSERT, and only
            # one of them can win. The loser resolves to the winner's row when
            # it is the exact same payload, and is refused otherwise — it never
            # reports a dispatch it did not stage, and it never retries the
            # INSERT.
            raced = await self._first(
                "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, "
                "revision_ref, evidence_ref, request_fingerprint, account_ref, workspace_ref, "
                "device_id, binding_ref, node_ref, root_ref, path_relative, file_path, "
                "nonce_sha256, state, expires_at, COALESCE(user_mode,0) AS user_mode FROM oracle_mesh_dispatch "
                f"WHERE {correlation_sql}",
                *correlation_params,
            )
            if raced is None:
                raise
            if (
                same_payload(raced)
                and raced.get("state") == "pending"
                and raced.get("expires_at", "") > now
            ):
                return {**dict(raced), **({"share_roots": list(share_roots)} if share_roots else {})}
            if same_payload(raced) and raced.get("state") in ("done", "failed"):
                raise HistoryError("oracle mesh run already executed") from None
            raise HistoryError("oracle mesh run already dispatched") from None
        created = await self._first(
            "SELECT dispatch_id, kind, command_text, command_id, tool_request_ref, request_id, revision_ref, "
            "evidence_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
            "binding_ref, node_ref, root_ref, path_relative, file_path, nonce_sha256, "
            f"state, expires_at, COALESCE(user_mode,0) AS user_mode FROM oracle_mesh_dispatch WHERE {correlation_sql}",
            *correlation_params,
        )
        if created is None:
            raise HistoryError("oracle mesh dispatch unavailable")
        return {**dict(created), **({"share_roots": list(share_roots)} if share_roots else {})}

    async def oldest_pending_oracle_mesh_dispatch(self) -> dict[str, Any] | None:
        """#4139 — the single oldest claimable Oracle execution, if any.

        Claimable means pending, unexpired and either never handed out or — for a
        ``read`` the owner has not stopped — handed out under a lease that has run
        out (#5895). A run-out lease cannot tell "the response never reached the
        executor" from "the executor ran it and restarted", so a row that changes
        the PC is settled as uncertain first instead of being offered again
        (#7562). The caller (the poll route, under the channel secret) re-claims
        atomically before responding; this read hands out nothing.
        """
        await self.settle_unredeliverable_oracle_mesh_claims()
        now = _now_iso()
        row = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_text, command_id, tool_request_ref, "
            "request_id, revision_ref, evidence_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, binding_ref, node_ref, root_ref, path_relative, "
            "file_path, nonce_sha256, state, expires_at, tool_call_ref, COALESCE(user_mode,0) AS user_mode "
            "FROM oracle_mesh_dispatch WHERE state=? AND expires_at>? "
            f"AND {ORACLE_MESH_CLAIMABLE_SQL} "
            "ORDER BY created_at ASC LIMIT 1",
            "pending", now, now,
        )
        return dict(row) if row is not None else None

    async def settle_unredeliverable_oracle_mesh_claims(self) -> int:
        """#7562 — end the handed-out rows a run-out lease must not hand out again.

        A ``command`` or ``desktop`` row that already carries a nonce may have run
        on the PC, so it ends as ``failed`` with ``termination='no_reply'``: the PC
        sent no result and whether it ran is not known. That is the same honest
        "uncertain" the re-staging guard keeps, and it is never a second run. A row
        the owner stopped ends as ``cancelled``, the word the owner's own stop
        already uses for a row nobody claimed.

        One conditional statement: a result that lands first (state leaves
        ``pending``) or a renewal that lands first (``claimed_until`` moves on) is
        left alone, and a late submission under the old nonce is then refused by
        the existing ``state='pending'`` gate instead of attaching to a row that
        has been settled. A ``read`` that nobody stopped is not touched: it is
        still re-delivered by the claim below.
        """
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET state='failed', termination=CASE "
            "WHEN COALESCE(termination,'')='cancelled' THEN 'cancelled' ELSE 'no_reply' END "
            f"WHERE {ORACLE_MESH_UNREDELIVERABLE_SQL}",
            _now_iso(),
        )
        return _changed_rows(written)

    async def claim_oracle_mesh_dispatch(
        self, *, dispatch_id: str, nonce_sha256: str
    ) -> bool:
        """#4139 — atomically hand one pending dispatch to the executor.

        The conditional update is the single-claim gate: exactly one poll wins
        one round. #5895 makes the hand-out a lease — the same UPDATE records the
        instant the claim may be handed out again, under the same condition the
        yield uses — so a claim whose response never reached the executor is not
        a permanent loss. Re-claiming rolls the nonce, so a submission still
        carrying the superseded nonce is refused by the existing nonce comparison
        instead of attaching a second result. Returns False when another poll won
        this round, when it expired, or when it left pending meanwhile.
        """
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        if not isinstance(nonce_sha256, str) or not nonce_sha256:
            raise HistoryError("nonce_sha256 is required")
        moment = datetime.now(timezone.utc)
        now = _iso(moment)
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET nonce_sha256=?, claimed_until=? "
            "WHERE dispatch_id=? AND state=? AND expires_at>? "
            f"AND {ORACLE_MESH_CLAIMABLE_SQL}",
            nonce_sha256,
            _iso(moment + timedelta(seconds=ORACLE_MESH_CLAIM_LEASE_SECONDS)),
            dispatch_id, "pending", now, now,
        )
        return _changed_rows(written) == 1

    async def renew_oracle_mesh_claim(
        self, *, dispatch_id: str, nonce_sha256: str,
    ) -> str | None:
        """#5997 — extend the lease of a command this executor is still running.

        The condition is the same proof a submission carries: the row is still
        pending and still names this nonce. A renewal whose claim was lost — the
        lease ran out and a later poll re-rolled the nonce — changes nothing and is
        told so, so the executor stops renewing instead of resurrecting a claim the
        lane has already given to somebody else. A running executor that keeps
        renewing is never handed out again; one that dies stops renewing, and the
        lease expiry re-delivers a read or settles anything that changes the PC as
        uncertain (#7562) — a settled row is no longer pending, so it cannot be
        renewed back to life either.
        """
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        if not isinstance(nonce_sha256, str) or not nonce_sha256:
            raise HistoryError("nonce_sha256 is required")
        moment = datetime.now(timezone.utc)
        until = _iso(moment + timedelta(seconds=ORACLE_MESH_CLAIM_LEASE_SECONDS))
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET claimed_until=? "
            "WHERE dispatch_id=? AND state=? AND nonce_sha256=?",
            until, dispatch_id, "pending", nonce_sha256,
        )
        return until if _changed_rows(written) == 1 else None

    async def cancel_oracle_mesh_dispatches_for_run(
        self, *, user_id: str, run_id: str,
    ) -> int:
        """#5895 — stop one owner run's PC work, whether it is queued or running.

        ``pending`` with no claim nonce is exactly "no executor has ever seen
        this": stopping it removes the work from the queue, and the existing poll
        — which yields only ``pending`` rows — never hands it out again, so the
        next request the owner makes is claimed straight away instead of sitting
        behind it.

        A row that already carries a nonce is the case the owner is really asking
        about: the PC has the command and the wait has no deadline (#5995 took the
        client ceiling away, and a command the customer's shell never finishes -
        measured on 2026-10-28 - holds every later operation on that PC behind it).
        That row is not failed here. Its ``termination`` is set to ``cancelled``
        and its ``state`` stays ``pending``, so the executor can read the owner's
        stop through the existing channel, end its own child, and land its result
        through the nonce gate it already holds. The row stays submittable on
        purpose: a refused submission would be resent until quarantined, which
        holds the queue longer than the stop the owner asked for.

        The terminal row says ``cancelled`` in the column that already records how
        a command ended, so an owner's own stop is never reported back as a PC
        failure. Both the read and the write are owner-scoped in the WHERE clause,
        so another account's dispatch is not addressable, and each update is one
        conditional statement: a claim that won the race is not cancelled as
        queued work, and a cancel that won is never claimed twice.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(run_id, str) or not run_id:
            raise HistoryError("run_id is required")
        stopped = await self._run(
            "UPDATE oracle_mesh_dispatch SET state=?, termination=? "
            "WHERE user_id=? AND run_id=? AND state=? AND nonce_sha256 IS NULL",
            "failed", "cancelled", user_id, run_id, "pending",
        )
        running = await self._run(
            "UPDATE oracle_mesh_dispatch SET termination=? "
            "WHERE user_id=? AND run_id=? AND state=? AND nonce_sha256 IS NOT NULL",
            "cancelled", user_id, run_id, "pending",
        )
        return _changed_rows(stopped) + _changed_rows(running)

    async def oracle_mesh_dispatch_cancellation(self, *, dispatch_id: str) -> bool:
        """Whether the owner stopped one already-claimed dispatch, for the executor.

        One bounded read on a single column, addressed only by the dispatch id the
        executor already holds. It never claims, never writes, and answers ``False``
        for anything it cannot read: an unreachable store must not look like an
        owner's stop, because ``False`` leaves the running command alone while
        ``True`` ends it.
        """
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        row = await self._first(
            "SELECT termination FROM oracle_mesh_dispatch "
            "WHERE dispatch_id=? AND state=?",
            dispatch_id, "pending",
        )
        return isinstance(row, dict) and row.get("termination") == "cancelled"

    async def oracle_mesh_node_live_claims(
        self, *, node_ref: str, except_dispatch_id: str = "",
    ) -> int:
        """How many dispatches are claimed on one PC right now, for the executor.

        #6106 leaves a held console line only when nothing on that PC is working.
        The connector's own map covers the host that runs it, and this row set is
        the only view that also covers the failover partner (#5462): during a
        handover both hosts can hold a claim, and a sweep that ended the partner's
        running command would break standard rule 1 — the work on a PC is never
        cut short.

        The claim is read from the same real columns the lease already uses: a row
        still ``pending``, unexpired, handed out (``nonce_sha256`` set) and not yet
        yielded (``claimed_until`` in the future). Nothing is inferred from text.
        ``except_dispatch_id`` removes the asker's own claim, which is live for
        exactly as long as it is asking, so without it the answer would always be
        "busy" and no wedged line could ever be cleared.

        It never claims, never writes, and raises on an unreadable row like every
        other reader here: the route turns that into the safe answer, which is
        "busy", because the alternative ends a real command on a customer machine.
        """
        if not isinstance(node_ref, str) or not node_ref or len(node_ref) > 256:
            raise HistoryError("node_ref is required")
        if not isinstance(except_dispatch_id, str):
            raise HistoryError("except_dispatch_id must be text")
        now = _now_iso()
        sql = (
            "SELECT COUNT(*) AS n FROM oracle_mesh_dispatch "
            "WHERE node_ref=? AND state=? AND expires_at>? "
            "AND nonce_sha256 IS NOT NULL AND claimed_until>?"
        )
        params: list[Any] = [node_ref, "pending", now, now]
        if except_dispatch_id:
            sql += " AND dispatch_id<>?"
            params.append(except_dispatch_id)
        row = await self._first(sql, *params)
        if not isinstance(row, dict):
            raise HistoryError("oracle mesh claim read unavailable")
        count = row.get("n")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise HistoryError("oracle mesh claim read is not a count")
        return count

    #: #82 monitoring reads this to answer "is anything waiting that nobody is
    #: claiming" without a log line and without a string match. The node list is
    #: bounded the same way the presence beat is (#5553 shares the number).
    LANE_STATUS_NODE_LIMIT = 8

    async def oracle_mesh_lane_status(
        self, *, node_limit: int = LANE_STATUS_NODE_LIMIT,
    ) -> dict[str, Any]:
        """The dispatch lane's own state, as counts and ages.

        Three questions, all of them answerable from the columns the lane already
        writes: work that no executor has claimed (`state='pending'`, unexpired, no
        nonce or a lease that has run out — the exact condition the poll yields on),
        work a claim is held for right now (the lease columns #5997 renews), and,
        per PC, how long its oldest unanswered dispatch has been waiting.

        Ages are computed here from the stored timestamps rather than in SQL, so the
        D1 and the local SQLite dialect answer the same way and one number cannot
        drift between environments.
        """
        if (isinstance(node_limit, bool) or not isinstance(node_limit, int)
                or not 1 <= node_limit <= 64):
            raise HistoryError("node_limit is out of range")
        moment = datetime.now(timezone.utc)
        now = _iso(moment)
        waiting = await self._first(
            "SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM oracle_mesh_dispatch "
            "WHERE state=? AND expires_at>? "
            "AND (nonce_sha256 IS NULL OR (claimed_until IS NOT NULL AND claimed_until<=?))",
            "pending", now, now,
        )
        claimed = await self._first(
            "SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM oracle_mesh_dispatch "
            "WHERE state=? AND expires_at>? AND nonce_sha256 IS NOT NULL AND claimed_until>?",
            "pending", now, now,
        )
        # Per PC, two different questions, because the owner standard keeps them
        # apart: `open` is everything still unfinished there (a long command under a
        # live claim is that, and nothing may call it a stop), while `waiting` is
        # only the work no claim covers. A silence verdict reads `waiting` alone.
        nodes = await self._all(
            "SELECT node_ref, COUNT(*) AS n, MIN(created_at) AS oldest, "
            "SUM(CASE WHEN nonce_sha256 IS NULL "
            "OR (claimed_until IS NOT NULL AND claimed_until<=?) THEN 1 ELSE 0 END) "
            "AS waiting, "
            "MIN(CASE WHEN nonce_sha256 IS NULL "
            "OR (claimed_until IS NOT NULL AND claimed_until<=?) THEN created_at "
            "ELSE NULL END) AS waiting_oldest "
            "FROM oracle_mesh_dispatch WHERE state=? AND expires_at>? "
            "AND node_ref IS NOT NULL AND node_ref<>'' "
            "GROUP BY node_ref ORDER BY oldest ASC LIMIT ?",
            now, now, "pending", now, node_limit,
        )
        return {
            "unclaimed": _lane_count_age(waiting, moment),
            "claimed": _lane_count_age(claimed, moment),
            "nodes": [_lane_node(row, moment) for row in nodes if isinstance(row, dict)],
        }

    async def consume_oracle_mesh_dispatch(
        self, *, dispatch_id: str, nonce: str, node_ref: str | None = None
    ) -> dict[str, Any] | None:
        """#4139 — accept one result submission for one dispatch, atomically.

        Two clearly separated paths:

        * **First submission.** A conditional ``pending -> received`` update
          is the single-winner gate. Only the request whose update actually
          changed the row is accepted; every concurrent loser updates nothing
          and receives ``None`` (409), so a duplicate delivery can never look
          like the winner.
        * **Retry after a transient conversation-store failure.** A prior
          attempt parked the row in ``store_failed`` with its claim intact.
          That state is not a race — the winner already finished — so the same
          nonce is accepted again as ``claim="retry"``. The append itself is
          idempotent, so a retry can never add a second message, and the PC
          file is never read again.

        Anything else — unknown dispatch, expired claim, foreign nonce,
        already ``done``/``failed`` — is refused.

        When the executor names the PC it claimed (``node_ref``), it must be the
        row's own target. A result produced on another PC is never attached to
        this dispatch, even with a valid nonce.
        """
        import hashlib as _hashlib
        import hmac as _hmac

        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        if not isinstance(nonce, str) or not nonce:
            return None
        if node_ref is not None:
            if not isinstance(node_ref, str) or not node_ref:
                raise HistoryError("node_ref must be a bounded reference")
        row = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_text, command_id, tool_request_ref, "
            "request_id, revision_ref, evidence_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, binding_ref, node_ref, root_ref, path_relative, "
            "file_path, nonce_sha256, state, expires_at, tool_call_ref, COALESCE(user_mode,0) AS user_mode "
            "FROM oracle_mesh_dispatch WHERE dispatch_id=?",
            dispatch_id,
        )
        if row is None:
            return None
        expected = row.get("nonce_sha256")
        if not isinstance(expected, str) or not expected:
            return None
        if node_ref is not None and row.get("node_ref") != node_ref:
            return None
        # Owner decision 2026-10-28: the dispatch TTL does not expire a result.
        # A run whose lease is being extended (#5997 renew) may finish late; the
        # nonce still proves this is the claimed executor, and the claim/lease
        # gate above still decides delivery. Only a foreign or stale nonce is
        # refused here.
        presented = _hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        if not _hmac.compare_digest(presented, expected):
            return None
        state = row.get("state")
        if state == "store_failed":
            # The winner already failed to store; this is its retry. Move the
            # row back to received under a guarded update so the close below
            # stays a single uniform transition.
            written = await self._run(
                "UPDATE oracle_mesh_dispatch SET state=? "
                "WHERE dispatch_id=? AND state=? AND nonce_sha256=?",
                "received", dispatch_id, "store_failed", expected,
            )
            if _changed_rows(written) != 1:
                return None
            return _tagged({**dict(row), "state": "received", "claim": "retry"})
        if state != "pending":
            return None
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET state=? "
            "WHERE dispatch_id=? AND state=? AND nonce_sha256=?",
            "received", dispatch_id, "pending", expected,
        )
        if _changed_rows(written) != 1:
            # A concurrent submission won this dispatch.
            return None
        accepted = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_text, command_id, tool_request_ref, "
            "request_id, revision_ref, evidence_ref, request_fingerprint, account_ref, "
            "workspace_ref, device_id, binding_ref, node_ref, root_ref, path_relative, "
            "file_path, nonce_sha256, state, expires_at, tool_call_ref, COALESCE(user_mode,0) AS user_mode "
            "FROM oracle_mesh_dispatch WHERE dispatch_id=?",
            dispatch_id,
        )
        if accepted is None or accepted.get("state") != "received":
            return None
        return _tagged({**dict(accepted), "claim": "first"})

    async def record_oracle_mesh_first_result(
        self, *, dispatch_id: str, content_sha256: str, content_bytes: int,
        termination: str | None = None, exit_code: int | None = None,
    ) -> bool:
        """#4139 — pin the first accepted result fingerprint for one dispatch.

        A resend after a transient store failure must be the *same* result: the
        executor never re-reads the PC file, so the server pins what arrived
        first and compares every retry against it. A mismatch is refused instead
        of appending a second, different body to the same conversation.
        """
        for name, value in (("dispatch_id", dispatch_id),
                            ("content_sha256", content_sha256)):
            if not isinstance(value, str) or not value:
                raise HistoryError(f"{name} is required")
        if isinstance(content_bytes, bool) or not isinstance(content_bytes, int):
            raise HistoryError("content_bytes must be an integer")
        if termination is not None and not isinstance(termination, str):
            raise HistoryError("termination must be a string")
        if exit_code is not None and (
            isinstance(exit_code, bool) or not isinstance(exit_code, int)
        ):
            raise HistoryError("exit_code must be an integer or null")
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET result_sha256=?, result_bytes=? "
            "WHERE dispatch_id=? AND result_sha256 IS NULL",
            content_sha256, content_bytes, dispatch_id,
        )
        if _changed_rows(written) != 1:
            pinned = await self._first(
                "SELECT result_sha256, result_bytes FROM oracle_mesh_dispatch "
                "WHERE dispatch_id=?",
                dispatch_id,
            )
            return (
                pinned is not None
                and pinned.get("result_sha256") == content_sha256
                and pinned.get("result_bytes") == content_bytes
            )
        if termination is not None:
            # #5015: the executor-observed termination/exit_code travels with
            # the pinned result so the model lane re-feeds the exact evidence
            # instead of inventing one. The additive 049 columns must exist:
            # a missing-column failure here stays a retryable 503 upstream and
            # never a silent deploy success — apply the 049 gate first.
            await self._run(
                "UPDATE oracle_mesh_dispatch SET termination=?, exit_code=? "
                "WHERE dispatch_id=?",
                termination, exit_code, dispatch_id,
            )
        return True

    async def mark_oracle_mesh_store_failed(self, *, dispatch_id: str) -> bool:
        """#4139 — park a received dispatch so the same result can be resent.

        Only a transient conversation-store failure reaches here. The claim and
        expiry stay intact, the PC file is not read again, and the retry is
        still single-delivery because the append is idempotent.
        """
        if not isinstance(dispatch_id, str) or not dispatch_id:
            raise HistoryError("dispatch_id is required")
        await self._run(
            "UPDATE oracle_mesh_dispatch SET state=? "
            "WHERE dispatch_id=? AND state=?",
            "store_failed", dispatch_id, "received",
        )
        parked = await self._first(
            "SELECT state FROM oracle_mesh_dispatch WHERE dispatch_id=?",
            dispatch_id,
        )
        return parked is not None and parked.get("state") == "store_failed"

    async def finish_oracle_mesh_dispatch(
        self, *, dispatch_id: str, outcome: str
    ) -> bool:
        """#4139 — close one received (or retried) dispatch, once.

        A retry submission parks the row back in ``received``, so both the
        first and the retry path close through the same guarded transition.
        """
        if outcome not in ("done", "failed"):
            raise HistoryError("outcome must be done or failed")
        written = await self._run(
            "UPDATE oracle_mesh_dispatch SET state=? "
            "WHERE dispatch_id=? AND state=?",
            outcome, dispatch_id, "received",
        )
        return _changed_rows(written) == 1

    async def store_oracle_mesh_original(
        self, *, user_id: str, dispatch_id: str, conversation_id: str,
        message_id: str, raw: str, expected_sha256: str, expected_bytes: int,
        verified: Any = None,
    ) -> str:
        """#4139 — keep one over-budget command output in the private R2
        original store under a server-derived key.

        The dispatch row is owner-scoped and its pin (SHA + byte length, set
        before this call) must match the presented bytes: a stored original
        that disagrees with the pin is a corruption signal, not a second
        truth. The key reuses the existing full-context layout
        (conversation + deterministic result id), so no browser-supplied key
        or foreign-account result can address it. Bytes are verified again on
        every read against the same pin.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(raw, str) or not raw:
            raise HistoryError("original text is required")
        if not isinstance(expected_sha256, str) or not expected_sha256:
            raise HistoryError("expected digest is required")
        row = await self._mesh_dispatch_pin(
            user_id=user_id, dispatch_id=dispatch_id, expected_sha256=expected_sha256,
            expected_bytes=expected_bytes, verified=verified,
        )
        data = raw.encode("utf-8")
        if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise HistoryError("mesh original bytes do not match the pinned result")
        key = await self._put_full_message(
            conversation_id, message_id, raw, max_bytes=_oracle_mesh_original_max_bytes(row, self.mesh_command_output_max_bytes),
        )
        if key is None:
            # _put_full_message only skips short texts; an over-budget output
            # always exceeds one message, so a skip here means the caller
            # passed the wrong body rather than a stored one.
            raise HistoryError("mesh original was not stored")
        return key

    async def store_oracle_mesh_command_result(
        self, *, user_id: str, dispatch_id: str, conversation_id: str,
        message_id: str, raw: str, expected_sha256: str, expected_bytes: int,
        verified: Any = None,
    ) -> str:
        """#5015 — keep one small verified command output for Engine re-feed.

        Same owner/pin checks as :meth:`store_oracle_mesh_original`, but the
        short-text gate of the over-budget path does not apply: a typical
        drive inventory is a few hundred bytes and still needs exact bytes for
        the model lane. Large outputs keep using the over-budget method so the
        existing non-delivery/retry contract for ``output_too_large`` is
        unchanged. Empty bodies are never stored here; the withheld-body notice
        path owns those.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(raw, str) or not raw:
            raise HistoryError("original text is required")
        if not isinstance(expected_sha256, str) or not expected_sha256:
            raise HistoryError("expected digest is required")
        row = await self._mesh_dispatch_pin(
            user_id=user_id, dispatch_id=dispatch_id, expected_sha256=expected_sha256,
            expected_bytes=expected_bytes, verified=verified,
        )
        data = raw.encode("utf-8")
        if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise HistoryError("mesh original bytes do not match the pinned result")
        limit = _oracle_mesh_original_max_bytes(row, self.mesh_command_output_max_bytes)
        if limit is not None and len(data) > limit:
            raise HistoryError("mesh original exceeds the bounded storage envelope")
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "put", None)):
            raise HistoryError("private full model-context storage is unavailable")
        import inspect as _inspect
        key = self._context_key(conversation_id, message_id)
        result = bucket.put(key, data, httpMetadata={"contentType": "text/plain; charset=utf-8"})
        if _inspect.isawaitable(result):
            await result
        return key

    async def store_oracle_mesh_original_bytes(
        self, *, user_id: str, dispatch_id: str, conversation_id: str,
        message_id: str, raw: bytes, media_type: str,
        expected_sha256: str, expected_bytes: int,
    ) -> str:
        """#4139 — keep one desktop screenshot in the private R2 original store.

        The binary twin of :meth:`store_oracle_mesh_original`: same
        server-derived key layout, same dispatch-pin verification before the
        put and the same pin check on every read. The only blob type this
        lane produces is the composited screenshot JPEG; anything else is
        refused rather than stored under an evidence key.
        """
        if not isinstance(user_id, str) or not user_id:
            raise HistoryError("user_id is required")
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            raise HistoryError("original bytes are required")
        if media_type != "image/jpeg":
            raise HistoryError("unsupported mesh original media type")
        if not isinstance(expected_sha256, str) or not expected_sha256:
            raise HistoryError("expected digest is required")
        row = await self._mesh_dispatch_pin(
            user_id=user_id, dispatch_id=dispatch_id, expected_sha256=expected_sha256,
            expected_bytes=expected_bytes, verified=verified,
        )
        data = bytes(raw)
        if len(data) != expected_bytes or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise HistoryError("mesh original bytes do not match the pinned result")
        if len(data) > ORACLE_MESH_ORIGINAL_MAX_BYTES:
            raise HistoryError("mesh original exceeds the bounded storage envelope")
        if not data.startswith(b"\xff\xd8\xff"):
            raise HistoryError("mesh original is not a JPEG screenshot")
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "put", None)):
            raise HistoryError("private full model-context storage is unavailable")
        key = self._context_key(conversation_id, message_id)
        result = bucket.put(key, data, httpMetadata={"contentType": "image/jpeg"})
        if inspect.isawaitable(result):
            await result
        return key

    async def read_oracle_mesh_original(
        self, *, user_id: str, dispatch_id: str, conversation_id: str,
        message_id: str,
    ) -> tuple[bytes, str] | None:
        """#4139 — read one stored command original for its owning account.

        Unknown ids and foreign accounts return None so the route answers
        404 without disclosing which part failed. A pin with no stored
        object, or stored bytes that disagree with the dispatch pin, raises
        instead of serving missing or corrupt bytes.
        """
        if not isinstance(user_id, str) or not user_id:
            return None
        row = await self._dispatch(
            "get_oracle_mesh_dispatch_pin", user_id=user_id, dispatch_id=dispatch_id)
        if row is None:
            return None
        pinned_sha = row.get("result_sha256")
        pinned_bytes = row.get("result_bytes")
        if not isinstance(pinned_sha, str) or not pinned_sha:
            return None
        try:
            key = self._context_key(conversation_id, message_id)
        except HistoryError:
            return None
        bucket = self.full_context_bucket
        if bucket is None or not callable(getattr(bucket, "get", None)):
            raise HistoryError("private full model-context storage is unavailable")
        try:
            obj = bucket.get(key)
            if inspect.isawaitable(obj):
                obj = await obj
            if obj is None:
                raise HistoryError("mesh original missing from store")
            from .workspace_storage import _read_r2_object_bytes
            payload = await _read_r2_object_bytes(obj)
        except HistoryError:
            raise
        except Exception as exc:
            raise HistoryError("mesh original read failed") from exc
        if len(payload) != pinned_bytes or hashlib.sha256(payload).hexdigest() != pinned_sha:
            raise HistoryError("mesh original does not match the pinned result")
        return payload, pinned_sha

    async def get_oracle_mesh_dispatch_for_owner(
        self, *, user_id: str, dispatch_id: str
    ) -> dict[str, Any] | None:
        """#4139 — one dispatch row for its owning account, or None.

        The retrieval route re-derives the conversation and the result id
        from this row; an unknown id or a foreign account both return None
        so the route answers 404 without disclosing which part failed.
        """
        if not isinstance(user_id, str) or not user_id:
            return None
        if not isinstance(dispatch_id, str) or not dispatch_id:
            return None
        # #5015: the 049 termination/exit_code columns are required. A database
        # without them raises here and every caller fails closed (503), so a
        # missing migration can never read as a successful deploy.
        row = await self._first(
            "SELECT dispatch_id, user_id, run_id, kind, command_id, revision_ref, tool_request_ref, "
            "result_sha256, result_bytes, termination, exit_code, state "
            "FROM oracle_mesh_dispatch WHERE dispatch_id=? AND user_id=?",
            dispatch_id, user_id,
        )
        if row is None:
            return None
        return _tagged(row)

    async def consent_key_for_owner_node(
        self, *, user_id: str, node_ref: str,
        account_ref: str, workspace_ref: str,
    ) -> tuple[str | None, str]:
        """The consent key the server recorded for one owner and Mesh node.

        #8359 E: the deployment ownership map is the file-read lane's record,
        and production's copy is stale. A server-owned dispatch row instead
        pairs the consent key (``device_id``, the value the human consent
        screen read) with the Mesh ``node_ref`` at dispatch time, under the
        owner and the exact connector account/workspace. Only this pair may
        supply a maintenance consent key. A missing row, a different account,
        competing keys or a value the canonical grammar refuses all fail
        closed with a value-free code - no device or account value is returned.
        """
        if (not isinstance(user_id, str) or not user_id
                or not isinstance(account_ref, str) or not account_ref
                or not isinstance(workspace_ref, str) or not workspace_ref
                or not is_pc_device_id(node_ref)):
            return None, "consent_key_invalid_request"
        rows = await self._all(
            "SELECT device_id, account_ref, workspace_ref FROM oracle_mesh_dispatch "
            "WHERE user_id=? AND node_ref=? ORDER BY created_at DESC LIMIT 8",
            user_id, node_ref,
        )
        if not rows:
            return None, "consent_key_record_missing"
        scoped = [
            row for row in rows
            if isinstance(row, dict)
            and row.get("account_ref") == account_ref
            and row.get("workspace_ref") == workspace_ref
        ]
        if not scoped:
            return None, "consent_key_scope_mismatch"
        # A row whose device_id is the Mesh node itself records that no
        # connector key was ever paired; it cannot supply a consent key.
        keyed = [row for row in scoped if row.get("device_id") != node_ref]
        if not keyed:
            return None, "consent_key_unpinned"
        keys = {row.get("device_id") for row in keyed}
        if len(keys) != 1:
            return None, "consent_key_ambiguous"
        key = next(iter(keys))
        if not is_pc_device_id(key):
            return None, "consent_key_invalid"
        return key, "observed"

