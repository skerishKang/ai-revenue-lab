"""#4139: select only the dedicated private Connector D1 via Wrangler OAuth.

Read-only by default. With --render, write a gitignored *local* TOML
overlay after confirming the exact one Cloudflare D1 resource exists.
Never create/migrate a database, deploy Workers, publish a route, or read
a production credential. All such steps remain separate explicit actions.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tomllib

APP = Path(__file__).resolve().parents[1]
TEMPLATE = APP / "wrangler.connector-acceptance-4139.toml"
OUTPUT = APP / "wrangler.connector-acceptance-4139.local.toml"
DB_NAME = "padiem-connector-acceptance-4139"
WORKER_NAME = "padiem-chat-connector-acceptance-4139"
STAGE_ORIGIN = "https://connector-acceptance.padiem.net"
SERVICE_NAMES = {
    "IDENTITY_AUTHORITY_SERVICE": "padiem-control-plane-identity-acceptance-4139",
    "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": "padiem-local-agent-broker-state-acceptance-4139",
}
UUID = re.compile(r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")


class StageRefused(ValueError):
    """An intentionally bounded refusal; no Cloudflare error is echoed."""


def trusted_template() -> str:
    raw = TEMPLATE.read_text(encoding="utf-8")
    x = tomllib.loads(raw)
    if (
        x.get("name") != WORKER_NAME
        or x.get("workers_dev") is not False
        or x.get("preview_urls") is not False
        or "route" in x or "routes" in x or "d1_databases" in x
        or x.get("vars", {}).get("PADIEM_CHAT_RUNTIME_MODE") != "mock"
        or x.get("vars", {}).get("PADIEM_CHAT_LIVE_ENABLED") != "false"
        or x.get("vars", {}).get("PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE")
        != "isolated-operator-acceptance-4139"
        or x.get("vars", {}).get("PADIEM_CHAT_PUBLIC_BASE_URL") != STAGE_ORIGIN
        or x.get("vars", {}).get("PADIEM_CONNECTOR_ACCEPTANCE_PUBLIC_ORIGIN") != STAGE_ORIGIN
        or {s.get("binding"): s.get("service") for s in x.get("services", [])}
        != SERVICE_NAMES
    ):
        raise StageRefused("unreviewed_stage_template")
    return raw


def cloudflare_d1_inventory() -> list[dict]:
    wrangler = shutil.which("wrangler")
    if not wrangler:
        raise StageRefused("wrangler_unavailable")
    env = os.environ.copy()
    for name in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY", "CLOUDFLARE_EMAIL"):
        env.pop(name, None)
    try:
        r = subprocess.run(
            [wrangler, "d1", "list", "--json"],
            cwd=APP, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
        if r.returncode != 0:
            raise StageRefused("cloudflare_d1_inventory_unavailable")
        data = json.loads(r.stdout)
        if not isinstance(data, list) or not all(isinstance(v, dict) for v in data):
            raise StageRefused("cloudflare_d1_inventory_invalid")
        return data
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        if isinstance(exc, StageRefused):
            raise
        raise StageRefused("cloudflare_d1_inventory_unavailable") from exc


def dedicated_d1(inventory: list[dict]) -> dict[str, str]:
    matches = [item for item in inventory if item.get("name") == DB_NAME]
    if len(matches) != 1:
        raise StageRefused(
            "dedicated_d1_missing" if not matches else "dedicated_d1_ambiguous"
        )
    uuid = matches[0].get("uuid")
    if not isinstance(uuid, str) or not UUID.fullmatch(uuid):
        raise StageRefused("dedicated_d1_invalid_uuid")
    if any(item.get("uuid") == uuid and item.get("name") != DB_NAME
           for item in inventory):
        raise StageRefused("dedicated_d1_aliases_other_database")
    return {"name": DB_NAME, "uuid": uuid}


def render(d1: dict[str, str], template: str) -> str:
    if (
        d1.get("name") != DB_NAME
        or not isinstance(d1.get("uuid"), str)
        or not UUID.fullmatch(d1["uuid"])
    ):
        raise StageRefused("unreviewed_d1_resource")
    rendered = template.rstrip() + (
        '\nPADIEM_CHAT_AUTH_MODE = "password"\n'
        '\n# New, independent staging D1. No production or shared QA data.\n'
        '[[d1_databases]]\n'
        'binding = "PADIEM_CHAT_DB"\n'
        'database_name = "' + DB_NAME + '"\n'
        'database_id = "' + d1["uuid"] + '"\n'
        'migrations_dir = "migrations"\n'
    )
    x = tomllib.loads(rendered)
    if (
        x["vars"]["PADIEM_CHAT_AUTH_MODE"] != "password"
        or x["vars"]["PADIEM_CHAT_LIVE_ENABLED"] != "false"
        or x["vars"]["PADIEM_CHAT_RUNTIME_MODE"] != "mock"
        or x["workers_dev"] is not False
        or x["preview_urls"] is not False
        or "routes" in x or "route" in x
        or x.get("d1_databases") != [{
            "binding": "PADIEM_CHAT_DB",
            "database_name": DB_NAME,
            "database_id": d1["uuid"],
            "migrations_dir": "migrations",
        }]
    ):
        raise StageRefused("unsafe_stage_overlay")
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description="Guard isolated Connector staging D1")
    parser.add_argument("--render", action="store_true",
                        help="create gitignored local overlay; no Cloudflare write")
    opts = parser.parse_args()
    try:
        template = trusted_template()
        d1 = dedicated_d1(cloudflare_d1_inventory())
        if opts.render:
            if OUTPUT.exists():
                raise StageRefused("local_stage_overlay_exists_no_overwrite")
            OUTPUT.write_text(render(d1, template), encoding="utf-8", newline="\n")
        print(json.dumps({
            "ok": True, "dedicated_d1_exists": True,
            "wrote_gitignored_local_overlay": bool(opts.render),
            "production_cloudflare_mutations": 0,
            "public_route_created": False, "physical_pairing_proven": False,
        }))
        return 0
    except StageRefused as exc:
        print(json.dumps({
            "ok": False, "reason": str(exc), "production_cloudflare_mutations": 0
        }))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
