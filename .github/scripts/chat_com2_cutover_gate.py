#!/usr/bin/env python3
"""Manual Chat front gate. No network or mutation happens at import time.

Only switch deploys. Switch and rollback detach, attach and verify the domain.
A failed attachment is restored to the original Worker when absence is verified.
Responses and child stdout/stderr are private inputs, never log messages.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chat_domain_transfer import transfer, TransferError, read_owner
from chat_rehearsal_evidence import (
    EvidenceError as Refused, REHEARSAL_STAGES, https_url, identity,
    parse_json, require, validate_rehearsal, verify_summary,
)

ROOT = Path(__file__).resolve().parents[2]
HOST = "chat.padiem.net"
PUBLIC = "https://" + HOST
ORIGIN = "https://chat-com2.padiem.net"
LEGACY = "padiem-chat"
FRONT = "padiem-chat-front"
SECRET_NAME = "PADIEM_COM2_EDGE_SECRET"
WORKFLOW = "chat-com2-cutover-gate.yml"
MODES = ("preflight", "readonly", "switch", "rollback")
FROZEN_PATHS = (
    "/auth/google/callback", "/auth/lovetree/start",
    "/api/connectors/github/start", "/api/connectors/github/callback",
)


def validate_dispatch(env):
    mode, sha = env.get("MODE"), env.get("TARGET_SHA", "")
    require(env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "dispatch_required")
    require(env.get("GITHUB_REF") == "refs/heads/main", "main_required")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", sha)), "sha_invalid")
    require(sha == env.get("GITHUB_SHA"), "dispatch_sha_mismatch")
    require(mode in MODES, "mode_invalid")
    require(env.get("CONFIRMATION") == f"{mode.upper()}_CHAT_COM2_{sha}", "confirmation_mismatch")
    if mode != "rollback":
        identity(sha, env.get("TARGET_GENERATION_ID", ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, *, method="GET", headers=None, data=None):
    """No redirect following, response/body/header printing, or write retry."""
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()
    except (OSError, ValueError):
        raise Refused("transport_failed") from None


def run_command(argv, *, env=None):
    # Never let Wrangler/Git error text echo credentials, headers or bindings.
    result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    require(result.returncode == 0, "command_failed")
    return result.stdout.strip()


class Gate:
    def __init__(self, env=None):
        self.env = dict(os.environ if env is None else env)
        self.sha = self.env.get("TARGET_SHA", "")
        self.mode = self.env.get("MODE", "")
        self.generation = self.env.get("TARGET_GENERATION_ID", "")

    def exact_main(self):
        require(run_command(["git", "rev-parse", "HEAD"]) == self.sha, "checkout_sha_mismatch")
        remote = run_command(["git", "ls-remote", "https://github.com/skerishKang/ai-revenue-lab.git", "refs/heads/main"])
        require(remote.split() == [self.sha, "refs/heads/main"], "main_sha_mismatch")

    def cf(self, path, *, method="GET", payload=None):
        account, token = self.env.get("CLOUDFLARE_ACCOUNT_ID", ""), self.env.get("CLOUDFLARE_API_TOKEN", "")
        require(bool(token) and bool(re.fullmatch(r"[0-9a-f]{32}", account)), "cloudflare_credentials_missing")
        status, _, raw = request("https://api.cloudflare.com/client/v4/accounts/" + account + path,
                                 method=method, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                                 data=None if payload is None else json.dumps(payload).encode())
        require(200 <= status < 300, "cloudflare_http_failed")
        if method == "DELETE" and status == 200 and not raw:
            return None
        result = parse_json(raw)
        require(result.get("success") is True, "cloudflare_api_failed")
        return result["result"]

    def account(self):
        text = (ROOT / "docs/operations/PADIEM_WEB_SEARCH_PROVIDER_POLICY_3385.md").read_text(encoding="utf-8")
        known = re.findall(r"Charliekant Account ID `([0-9a-f]{32})`", text)
        require(len(known) == 1 and self.env.get("CLOUDFLARE_ACCOUNT_ID") == known[0], "account_scope_mismatch")
        require(self.cf("").get("id") == known[0], "account_scope_mismatch")

    def bindings(self, worker):
        # Only select the non-secret fields needed by this gate. No raw JSON
        # is written to logs/artifacts or echoed on any failure path.
        result = self.cf(f"/workers/scripts/{worker}/settings")
        values = {}
        for binding in result.get("bindings", []):
            if binding.get("type") == "plain_text":
                name = binding.get("name")
                require(name not in values, "duplicate_binding")
                values[name] = binding.get("text")
        return values

    def domain(self):
        rows = self.cf("/workers/domains?hostname=" + HOST)
        matches = [row for row in rows if row.get("hostname") == HOST]
        require(len(matches) == 1, "domain_not_unique")
        row = matches[0]
        require(row.get("service") in (LEGACY, FRONT) and row.get("enabled") is True and
                row.get("previews_enabled") is False and
                row.get("zone_name") == "padiem.net" and
                bool(re.fullmatch(r"[0-9a-f]{32}", row.get("zone_id", ""))), "domain_scope_mismatch")
        return row

    def github(self, path):
        require(self.env.get("GITHUB_REPOSITORY") == "skerishKang/ai-revenue-lab", "repository_mismatch")
        token = self.env.get("GH_TOKEN", "")
        require(bool(token), "github_token_missing")
        status, _, raw = request("https://api.github.com/repos/skerishKang/ai-revenue-lab" + path,
                                 headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
        require(status == 200, "github_read_failed")
        return parse_json(raw)

    def source_run(self, run_id, workflow):
        require(bool(re.fullmatch(r"[1-9][0-9]*", run_id)), "source_run_required")
        run = self.github("/actions/runs/" + run_id)
        require(run.get("head_sha") == self.sha and run.get("head_branch") == "main" and
                run.get("event") == "workflow_dispatch" and run.get("status") == "completed" and
                run.get("conclusion") == "success" and run.get("path") == ".github/workflows/" + workflow,
                "source_run_not_successful_exact_main")
        return run

    def rehearsal(self):
        identity(self.sha, self.generation)
        url = https_url(self.env.get("REHEARSAL_EVIDENCE_URL", ""))
        public_pem = self.env.get("REHEARSAL_PUBLIC_KEY_PEM", "").encode()
        require(bool(public_pem), "evidence_public_key_missing")
        status, _, raw = request(url, headers={"Cache-Control": "no-cache"})
        require(status == 200, "evidence_download_failed")
        verify_summary(parse_json(raw), public_pem, expected_sha=self.sha,
                       expected_generation=self.generation)
        print("REHEARSAL_EVIDENCE=PASS signature=Ed25519 max_age_hours=24")

    def probe(self, origin, path, expected, *, method="GET", maintenance=False):
        status, response_headers, raw = request(origin + path, method=method, headers={"User-Agent": "padiem-boot-recovery/1.0"})
        require(status == expected, "probe_status_mismatch")
        lower = {key.lower(): value for key, value in response_headers.items()}
        require("x-padiem-front" not in lower, "front_fallback_detected")
        if maintenance:
            body = parse_json(raw)
            require(body.get("error", {}).get("code") == "maintenance" and
                    "no-store" in lower.get("cache-control", ""), "freeze_unverified")

    def front_config(self, *, deployed=False):
        with (ROOT / "apps/padiem-chat-front/wrangler.toml").open("rb") as handle:
            config = tomllib.load(handle)
        require(config.get("name") == FRONT and "routes" not in config and "route" not in config and
                config.get("workers_dev") is False and config.get("preview_urls") is False,
                "front_route_config_drift")
        require(config["vars"].get("FRONT_ORIGIN") == ORIGIN, "front_origin_drift")
        unit = (ROOT / "deploy/host-com2/chat/padiem-chat-com2.service").read_text()
        require("--host 127.0.0.1 --port 8798" in unit, "host_port_contract_drift")
        values = self.bindings(FRONT)
        require(values.get("FRONT_ORIGIN") == ORIGIN and values.get("FALLBACK_MODE") == "static" and
                values.get("COM2_CANONICAL") in (("writes",) if deployed else ("off", "writes")), "front_settings_drift")
        names = [s.get("name") for s in self.cf(f"/workers/scripts/{FRONT}/secrets")]
        require(names.count(SECRET_NAME) == 1, "edge_secret_missing")
        print("FRONT_CONFIG=PASS FRONT_ORIGIN=https://chat-com2.padiem.net FALLBACK_MODE=static COM2_CANONICAL=" + values["COM2_CANONICAL"])
        print("EDGE_SECRET_NAME=PADIEM_COM2_EDGE_SECRET PRESENT=yes")

    def legacy_freeze_config(self):
        values = self.bindings(LEGACY)
        flag = str(values.get("PADIEM_CHAT_WRITE_FREEZE", "")).strip().lower()
        paths = str(values.get("PADIEM_CHAT_WRITE_FREEZE_PATHS", "")).replace(",", " ").split()
        require(bool(flag) and flag not in {"0", "false", "no", "off"} and
                set(paths) == set(FROZEN_PATHS), "legacy_freeze_unverified")

    def freeze_probes(self, origin):
        self.probe(origin, "/health", 200)
        # POST /health has no business handler. Prove global mutations are
        # blocked before touching the known write-effect GET routes.
        self.probe(origin, "/health", 503, method="POST", maintenance=True)
        # local_cpython wraps the edge gate with apply_write_freeze. These
        # maintenance responses are observable without the signing secret.
        self.probe(origin, "/api/auth/status", 403 if origin == ORIGIN else 200)
        for path in FROZEN_PATHS:
            self.probe(origin, path, 503, maintenance=True)

    def preflight(self):
        self.front_config()
        self.probe(ORIGIN, "/health", 200)
        self.probe(ORIGIN, "/api/auth/status", 403)
        self.rehearsal()
        owner = self.domain()["service"]
        print("DOMAIN_OWNER=" + owner)
        require(owner == LEGACY, "switch_source_not_legacy")

    def readonly(self):
        self.legacy_freeze_config()
        self.freeze_probes(PUBLIC)
        self.freeze_probes(ORIGIN)
        print("WRITE_FREEZE=VERIFIED_BOTH_ORIGINS")

    def prior_readonly(self):
        run = self.source_run(self.env.get("READONLY_RUN_ID", ""), WORKFLOW)
        require(run.get("display_title") == f"chat-com2/readonly/{self.sha}/{self.generation}", "readonly_run_required")

    def deploy(self):
        require(self.domain()["service"] == LEGACY, "switch_source_not_legacy")
        child_env = {k: v for k, v in self.env.items() if k != "GH_TOKEN"}
        run_command(["npx", "--no-install", "wrangler", "deploy", "--config",
                     "apps/padiem-chat-front/wrangler.toml", "--keep-vars",
                     "--var", "COM2_CANONICAL:writes", "--var", "FALLBACK_MODE:static",
                     "--var", "FRONT_ORIGIN:" + ORIGIN], env=child_env)
        self.front_config(deployed=True)
        require(self.domain()["service"] == LEGACY, "deployment_changed_domain")

    def move_domain(self, target):
        def read_rows():
            return self.cf("/workers/domains?hostname=" + HOST)

        def mutate(method, path, payload):
            return self.cf(path, method=method, payload=payload)

        def report(stage, owner):
            print("DOMAIN_OWNER_STATE=" + owner + " STAGE=" + stage)

        try:
            require(target in (FRONT, LEGACY), "domain_target_invalid")
            self.exact_main()
            before = self.domain()
            if before["service"] == target:
                require(target == LEGACY, "switch_source_not_legacy")
                print("DOMAIN_ALREADY_AT_TARGET=yes")
                return
            transfer(host=HOST, before=before, target=target, read_rows=read_rows,
                     mutate=mutate, report=report)
        except TransferError as error:
            raise Refused(error.stage) from None
        except Exception:
            report("preflight_failed", read_owner(read_rows, HOST))
            raise

    def execute(self):
        validate_dispatch(self.env)
        self.exact_main()
        self.account()
        if self.mode == "rollback":
            # Recover even when COM2, the front or rehearsal storage is down.
            # Keep Python frozen until the separate data handback is complete.
            self.legacy_freeze_config()
            self.move_domain(LEGACY)
            self.freeze_probes(PUBLIC)
        else:
            self.preflight()
            if self.mode in ("readonly", "switch"):
                self.readonly()
            if self.mode == "switch":
                self.prior_readonly()
                self.exact_main()
                self.deploy()
                # Recheck the write window after deployment, before the PUT.
                self.readonly()
                self.rehearsal()  # Evidence must still be fresh immediately before the PUT.
                self.move_domain(FRONT)
                self.probe(PUBLIC, "/health", 200)
                # Gate sends no proof here: only the deployed front can sign.
                self.probe(ORIGIN, "/api/auth/status", 403)
                self.probe(PUBLIC, "/api/auth/status", 200)
                # front transforms upstream 503 into static fallback HTML;
                # inspect the original COM2 JSON, not that transformed body.
                self.freeze_probes(ORIGIN)
        print("CHAT_COM2_GATE=PASS mode=" + self.mode)


def main():
    instance = Gate()
    try:
        instance.execute()
        return 0
    except Refused as error:
        print("CHAT_COM2_GATE=REFUSED reason=" + str(error))
    except Exception:
        # Never stringify exceptions containing requests, signed URLs, JSON,
        # subprocess stdout/stderr, tokens or binding values.
        print("CHAT_COM2_GATE=REFUSED reason=unexpected_failure")
    owner = read_owner(lambda: instance.cf("/workers/domains?hostname=" + HOST), HOST)
    print("DOMAIN_OWNER_STATE=" + owner + " STAGE=final")
    if os.environ.get("MODE") == "switch":
        print("ROLLBACK_GUIDANCE=wait_for_run_end_then_rollback_mode_keep_write_freeze")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
