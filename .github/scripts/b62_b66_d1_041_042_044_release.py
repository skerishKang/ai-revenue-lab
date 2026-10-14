#!/usr/bin/env python3
"""B66 #4316 exact-main Cloudflare D1 041/042/044 release; no customer row reads.

Mode=readonly only inspects Worker binding, SQLite metadata and Time Travel.
Mode=apply is separately authorized by production environment and exact phrase.
Fail closed on partial application, malformed evidence, ownership drift or errors.
Never print Cloudflare secret, D1 identifiers, schema/row contents or bookmark.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from b62_d1_migration_041_042_schema import SCHEMA_SQL as SQL_41_42, classify as classify_41_42
from b62_d1_migration_044_schema import SQL as SQL_44, classify as classify_44

EXACT_PHRASE = "APPLY_B66_D1_041_042_044_FROM_EXACT_MAIN"
ROOT = Path(__file__).resolve().parents[2]
FIXED_SQL = {
    "041": ROOT / "apps/padiem-chat/migrations/041_b66_ai_conversation.sql",
    "042": ROOT / "apps/padiem-chat/migrations/042_conversation_product_scope.sql",
    "044": ROOT / "apps/padiem-chat/migrations/044_b66_ai_turn_attempt.sql",
}
_ALLOWED_IDS = re.compile(r"[a-fA-F0-9-]{32,36}\Z")
_BOOKMARK = re.compile(r"[A-Za-z0-9_-]{12,130}\Z")


class ReleaseRefusal(RuntimeError):
    pass


def plan(state_41_42: str, state_44: str) -> list[str]:
    if state_41_42 == "exact" and state_44 == "exact":
        return []
    if state_44 != "pre_044":
        raise ReleaseRefusal("B66_UNEXPECTED_044_STATE")
    if state_41_42 == "pre_041":
        return ["041", "042", "044"]
    if state_41_42 == "pre_042":
        return ["042", "044"]
    if state_41_42 == "exact":
        return ["044"]
    raise ReleaseRefusal("B66_041_042_DRIFT_OR_MISSING")


class Client:
    def __init__(self, token: str, account: str):
        if not token or not account or not _ALLOWED_IDS.fullmatch(account):
            raise ReleaseRefusal("B66_CLOUDFLARE_CREDENTIALS_UNAVAILABLE")
        self._token = token
        self._root = f"https://api.cloudflare.com/client/v4/accounts/{account}"

    def _request(self, url: str, sql: str | None = None) -> dict:
        data = json.dumps({"sql": sql}).encode("utf-8") if sql is not None else None
        req = Request(url, data=data, method="POST" if data is not None else "GET",
                      headers={"Authorization": f"Bearer {self._token}",
                               "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=30) as rsp:
                if rsp.status != 200:
                    raise ReleaseRefusal("B66_CLOUDFLARE_REQUEST_UNVERIFIED")
                payload = json.load(rsp)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            raise ReleaseRefusal("B66_CLOUDFLARE_REQUEST_FAILED") from None
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ReleaseRefusal("B66_CLOUDFLARE_RESPONSE_INVALID")
        return payload

    def db_id(self) -> str:
        payload = self._request(self._root + "/workers/scripts/padiem-chat/settings")
        result = payload.get("result")
        bindings = result.get("bindings") if isinstance(result, dict) else None
        if not isinstance(bindings, list):
            raise ReleaseRefusal("B66_LIVE_WORKER_SETTINGS_INVALID")
        found = [v for v in bindings if isinstance(v, dict)
                 and v.get("type") == "d1" and v.get("name") == "PADIEM_CHAT_DB"]
        if len(found) != 1 or not isinstance(found[0].get("id"), str):
            raise ReleaseRefusal("B66_CANONICAL_D1_BINDING_NOT_EXACT")
        ident = found[0]["id"]
        if not _ALLOWED_IDS.fullmatch(ident):
            raise ReleaseRefusal("B66_D1_BINDING_ID_INVALID")
        return ident

    def query(self, db: str, sql: str) -> dict:
        value = self._request(self._root + f"/d1/database/{db}/query", sql)
        blocks = value.get("result")
        if not isinstance(blocks, list) or not blocks or not all(
            isinstance(block, dict) and block.get("success") is True for block in blocks
        ):
            raise ReleaseRefusal("B66_D1_STATEMENT_UNVERIFIED")
        return value

    def recovery(self, db: str) -> None:
        payload = self._request(self._root + f"/d1/database/{db}/time_travel/bookmark")
        result = payload.get("result")
        bookmark = result.get("bookmark") if isinstance(result, dict) else None
        if not isinstance(bookmark, str) or not _BOOKMARK.fullmatch(bookmark):
            raise ReleaseRefusal("B66_D1_RECOVERY_UNAVAILABLE")


def states(client: Client, db: str) -> tuple[str, str]:
    try:
        left = classify_41_42(client.query(db, SQL_41_42))
        right = classify_44(client.query(db, SQL_44))
    except (ValueError, KeyError, TypeError):
        raise ReleaseRefusal("B66_D1_SCHEMA_EVIDENCE_INVALID") from None
    if left not in ("exact", "pre_041", "pre_042") or right not in ("exact", "pre_044"):
        raise ReleaseRefusal("B66_D1_SCHEMA_DRIFT_OR_MISSING")
    return left, right


def execute(mode: str, confirmation: str, client: Client) -> None:
    if mode not in ("readonly", "apply"):
        raise ReleaseRefusal("B66_MODE_NOT_ALLOWLISTED")
    if mode == "apply" and confirmation != EXACT_PHRASE:
        raise ReleaseRefusal("B66_MUTATION_NOT_AUTHORIZED")
    db = client.db_id()
    left, right = states(client, db)
    plan_now = plan(left, right)
    client.recovery(db)
    print(f"B66_D1_SCHEMA_041_042={left.upper()}")
    print(f"B66_D1_SCHEMA_044={right.upper()}")
    print("B66_CANONICAL_D1_AND_RECOVERY=PASS")
    print("D1_SCHEMA_QUERY=READ_ONLY")
    print("APPLICATION_ROW_READ=0")
    if mode == "readonly":
        print("PRODUCTION_MUTATION=0")
        return
    if not plan_now:
        print("B66_D1_RELEASE=ALREADY_EXACT_NOOP")
        print("PRODUCTION_MUTATION=0")
        return
    print("B66_D1_MIGRATIONS_TO_APPLY=" + ",".join(plan_now))
    for step in plan_now:
        if client.db_id() != db:
            raise ReleaseRefusal("B66_D1_BINDING_CHANGED")
        before_41_42, before_44 = states(client, db)
        expected = {"041": ("pre_041", "pre_044"),
                    "042": ("pre_042", "pre_044"),
                    "044": ("exact", "pre_044")}[step]
        if (before_41_42, before_44) != expected:
            raise ReleaseRefusal("B66_D1_PREMUTATION_STATE_CHANGED")
        sql = FIXED_SQL[step].read_text(encoding="utf-8")
        if not sql.strip() or "CREATE" not in sql.upper() and "ALTER" not in sql.upper():
            raise ReleaseRefusal("B66_MIGRATION_SOURCE_INVALID")
        # ONE fixed source migration per write. No retry on HTTP uncertainty.
        client.query(db, sql)
        after_41_42, after_44 = states(client, db)
        target = {"041": ("pre_042", "pre_044"),
                  "042": ("exact", "pre_044"),
                  "044": ("exact", "exact")}[step]
        if (after_41_42, after_44) != target:
            raise ReleaseRefusal("B66_D1_POSTMUTATION_SCHEMA_NOT_EXACT")
        print(f"B66_D1_APPLIED_{step}_AND_READBACK=PASS")
    print("B66_D1_SCHEMA_041_042=EXACT")
    print("B66_D1_SCHEMA_044=EXACT")
    print("B66_D1_RELEASE=APPLIED_AND_VERIFIED")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in ("readonly", "apply"):
        print("B66_RELEASE_MODE_INVALID", file=sys.stderr)
        return 2
    try:
        execute(args[0], os.environ.get("B66_MUTATION_CONFIRMATION", ""),
                Client(os.environ.get("CLOUDFLARE_API_TOKEN", ""),
                       os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")))
        return 0
    except ReleaseRefusal as exc:
        # Fixed, non-secret refusal labels only.
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
