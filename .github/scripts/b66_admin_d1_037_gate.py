"""B66 admin migration 037: exact bound Padiem D1, read-only attestation or guarded apply.

This CLI prints no member data, provider secrets or API responses. Readonly is
non-mutating; apply requires a pre-apply Cloudflare D1 Time Travel bookmark.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

PADIEM_ACCOUNT = "5a305a04650f4ad419062f8d4a96a41d"
BASE = "https://api.cloudflare.com/client/v4"
EXPECTED = {
    "b66_memberships", "b66_membership_audit",
    "b66_signup_alert_outbox", "b66_model_access_policy",
    "b66_tier_model_grants", "b66_disabled_models",
    "b66_model_policy_audit", "b66_signup_alert_delivery",
}
TRIGGER = "b66_member_after_signup"
ROOT = Path(__file__).resolve().parents[2]
SQL = ROOT / "apps/padiem-chat/migrations/037_b66_admin_memberships.sql"


def request(method: str, path: str, body=None):
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    if not token or os.getenv("CLOUDFLARE_ACCOUNT_ID", "") != PADIEM_ACCOUNT:
        raise RuntimeError("PADIEM_ACCOUNT_AUTHORITY_UNVERIFIED")
    payload = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=payload, method=method, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            x = json.loads(r.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as e:
        raise RuntimeError("CLOUDFLARE_" + type(e).__name__) from None
    if x.get("success") is not True:
        raise RuntimeError("CLOUDFLARE_API_REFUSED")
    return x["result"]


def bound_database():
    account = PADIEM_ACCOUNT
    settings = request("GET", f"/accounts/{account}/workers/scripts/padiem-chat/settings")
    bindings = settings.get("bindings", [])
    matches = [b for b in bindings if b.get("name") == "PADIEM_CHAT_DB" and b.get("type") == "d1"]
    if len(matches) != 1:
        raise RuntimeError("PADIEM_CHAT_DB_LIVE_BINDING_MISSING_OR_AMBIGUOUS")
    dbid = str(matches[0].get("id", ""))
    if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", dbid):
        raise RuntimeError("D1_BINDING_ID_INVALID")
    metadata = request("GET", f"/accounts/{account}/d1/database/{dbid}")
    db_name = metadata.get("name", "")
    if not isinstance(db_name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", db_name):
        raise RuntimeError("D1_NAME_INVALID")
    return dbid, db_name


def read_query(dbid: str, sql: str):
    x = request("POST", f"/accounts/{PADIEM_ACCOUNT}/d1/database/{dbid}/query", {"sql": sql})
    if not isinstance(x, list) or len(x) != 1 or x[0].get("success") is not True:
        raise RuntimeError("D1_QUERY_NOT_SUCCESSFUL")
    return x[0].get("results", [])


def verify(dbid: str):
    rows = read_query(dbid, "SELECT type,name FROM sqlite_master WHERE type IN ('table','trigger') "
                               "AND (name LIKE 'b66_%' OR name IN ('users','password_credentials'))")
    names = {r.get("name") for r in rows if r.get("type") == "table"}
    triggers = {r.get("name") for r in rows if r.get("type") == "trigger"}
    if not {"users","password_credentials"}.issubset(names):
        raise RuntimeError("EXISTING_AUTH_TABLES_NOT_PROVEN")
    columns = {r.get("name") for r in read_query(dbid, "PRAGMA table_info(users)")}
    if not {"id","email","display_name","auth_provider","provider_subject","created_at","updated_at"}.issubset(columns):
        raise RuntimeError("USER_SCHEMA_INCOMPATIBLE")
    existing = {r.get("name") for r in rows if r.get("name") in EXPECTED}
    trigger_present = TRIGGER in triggers
    if not existing and not trigger_present:
        return "MISSING"
    if existing == EXPECTED and trigger_present:
        return "EXACT"
    return "DRIFT"


def bookmark(dbid):
    x = request("GET", f"/accounts/{PADIEM_ACCOUNT}/d1/database/{dbid}/time_travel/bookmark")
    mark = x.get("bookmark") if isinstance(x, dict) else None
    if not isinstance(mark, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{12,130}", mark):
        raise RuntimeError("D1_RECOVERY_BOOKMARK_UNAVAILABLE")
    return mark


def apply(dbid, name):
    if not SQL.exists():
        raise RuntimeError("MIGRATION_SOURCE_MISSING")
    with tempfile.TemporaryDirectory(prefix="b66-admin-d1-") as tmp:
        config = Path(tmp) / "wrangler.toml"
        config.write_text(
            'name = "b66-admin-d1-migration-only"\n'
            'compatibility_date = "2026-09-01"\n'
            f'account_id = "{PADIEM_ACCOUNT}"\n'
            '[[d1_databases]]\n'
            'binding = "PADIEM_CHAT_DB"\n'
            f'database_name = "{name}"\n'
            f'database_id = "{dbid}"\n',
            encoding="utf-8"
        )
        # Wrangler uses an atomic file import with built-in rollback on failure.
        env = os.environ.copy()
        result = subprocess.run(
            ["npx","--yes","wrangler@4.129.0","d1","execute",name,
             "--remote","--file",str(SQL),"--config",str(config)],
            env=env,cwd=tmp,capture_output=True,text=True,timeout=240
        )
        if result.returncode != 0:
            # Deliberately never echo untrusted CLI output containing secrets.
            raise RuntimeError("WRANGLER_MIGRATION_FILE_APPLY_FAILED")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("readonly","apply"):
        raise SystemExit("mode must be readonly or apply")
    mode = sys.argv[1]
    if mode == "apply" and os.getenv("B66_037_CONFIRMATION") != "APPLY_B66_ADMIN_037_PADIEM_D1_ONCE":
        raise RuntimeError("EXPLICIT_MIGRATION_APPROVAL_MISSING")
    dbid, dbname = bound_database()
    print("PADIEM_LIVE_WORKER_D1_BINDING=PASS",flush=True)
    state = verify(dbid)
    print("B66_037_SCHEMA_BEFORE="+state,flush=True)
    if state == "DRIFT":
        raise RuntimeError("SCHEMA_DRIFT_HOLD")
    if mode == "readonly":
        print("B66_037_PRODUCTION_MUTATION=0",flush=True)
        return
    mark = bookmark(dbid)
    # Preserve a recoverable reference in the protected Actions job log;
    # never auto-restore since Time Travel restores the entire database.
    print("B66_037_PREAPPLY_RECOVERY_BOOKMARK="+mark,flush=True)
    if state == "MISSING":
        apply(dbid,dbname)
        print("B66_037_SCHEMA_APPLY=PASS",flush=True)
    result = verify(dbid)
    print("B66_037_SCHEMA_AFTER="+result,flush=True)
    if result != "EXACT":
        raise RuntimeError("POST_APPLY_SCHEMA_INCOMPLETE")
    counts = read_query(dbid, "SELECT (SELECT COUNT(*) FROM users) AS u, "
                              "(SELECT COUNT(*) FROM b66_memberships) AS m")
    if not counts or int(counts[0]["u"]) != int(counts[0]["m"]):
        raise RuntimeError("LEGACY_MEMBERSHIP_BACKFILL_MISMATCH")
    print("B66_037_EXISTING_MEMBER_BACKFILL=PASS",flush=True)


if __name__ == "__main__":
    try: main()
    except Exception as e:
        print("B66_037_FAIL_CLOSED="+str(e),file=sys.stderr)
        sys.exit(1)
