#!/usr/bin/env python3
"""Render and offline-validate a Cloudflare Tunnel ingress for COM2 (issue #5115).

The tunnel is the only public ingress planned for the COM2 runtime. Business
logic stays in the existing services; the edge only routes traffic. This tool
deliberately stops before activation:

* ``render`` writes a config with explicit ``SERVICE=HOSTNAME`` mappings whose
  origins are fixed loopback URLs from the known COM2 service table.
* ``validate`` runs ``cloudflared tunnel --config <file> ingress validate``,
  which is offline and does not contact Cloudflare.
* No tunnel token, credentials file, DNS record, route or running tunnel is
  created or modified here. Activation remains an operator action with the
  existing Cloudflare credentials.

Only products with an actual local HTTP listener are mappable. B66 currently
runs as source/library on COM2 (no HTTP route), so it cannot be mapped until a
local server exists.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

KIND = "PADIEM_COM2_TUNNEL_V1"
GENERATED_MARKER = "# generated-by: scripts/ops/com2_tunnel.py"
PUBLIC_SERVICES: dict[str, str] = {
    "chat": "http://127.0.0.1:18764",
    "claw": "http://127.0.0.1:18764",
}
# Internal services are intentionally not mappable to a public hostname.
INTERNAL_SERVICES: dict[str, str] = {
    "b14": "http://127.0.0.1:18717",
    "p01": "http://127.0.0.1:18731",
}
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_TUNNEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class TunnelError(Exception):
    """Stable failure code; never carries secret or credential values."""


class CloudflaredUnavailable(TunnelError):
    def __init__(self) -> None:
        super().__init__("cloudflared_unavailable")


def validate_hostname(hostname: str) -> str:
    value = hostname.strip()
    if value != hostname or not value:
        raise TunnelError("invalid_hostname")
    if value.lower() != value:
        raise TunnelError("invalid_hostname")
    try:
        import ipaddress

        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise TunnelError("invalid_hostname")
    if len(value) > 253 or value.endswith(".") or "*" in value:
        raise TunnelError("invalid_hostname")
    labels = value.split(".")
    if len(labels) < 2:
        raise TunnelError("invalid_hostname")
    if any(not _HOST_LABEL.match(label) for label in labels):
        raise TunnelError("invalid_hostname")
    if labels[-1].isdigit():
        raise TunnelError("invalid_hostname")
    return value


def parse_mappings(mappings: Sequence[str]) -> list[tuple[str, str]]:
    if not mappings:
        raise TunnelError("no_mappings")
    resolved: list[tuple[str, str]] = []
    seen_hosts: set[str] = set()
    seen_services: set[str] = set()
    for mapping in mappings:
        name, separator, hostname = mapping.partition("=")
        if separator != "=" or not name or not hostname:
            raise TunnelError("invalid_mapping")
        if name not in PUBLIC_SERVICES:
            if name in INTERNAL_SERVICES:
                raise TunnelError("internal_service_not_public")
            raise TunnelError("unknown_service")
        if name in seen_services:
            raise TunnelError("duplicate_service")
        host = validate_hostname(hostname)
        if host in seen_hosts:
            raise TunnelError("duplicate_hostname")
        seen_hosts.add(host)
        seen_services.add(name)
        resolved.append((name, host))
    return resolved


def render_ingress(
    mappings: Sequence[str],
    *,
    tunnel_name: str | None = None,
) -> str:
    resolved = parse_mappings(mappings)
    if tunnel_name is not None and not _TUNNEL_NAME.match(tunnel_name):
        raise TunnelError("invalid_tunnel_name")
    lines = [
        GENERATED_MARKER,
        "# Loopback origins only; no business logic at the edge.",
        "# SSE/NDJSON responses stream through with chunked encoding enabled.",
    ]
    if tunnel_name:
        lines.append(f"tunnel: {tunnel_name}")
    lines.append("ingress:")
    for name, host in resolved:
        lines.extend(
            [
                f"  - hostname: {host}",
                f"    service: {PUBLIC_SERVICES[name]}",
                "    originRequest:",
                "      connectTimeout: 30s",
                "      tcpKeepAlive: 30s",
                "      disableChunkedEncoding: false",
                "      noTLSVerify: false",
            ]
        )
    lines.extend(["  - service: http_status:404", ""])
    return "\n".join(lines)


def write_ingress(
    output: Path,
    mappings: Sequence[str],
    *,
    tunnel_name: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    content = render_ingress(mappings, tunnel_name=tunnel_name)
    path = Path(output)
    if path.exists() and not force:
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            raise TunnelError("output_unreadable")
        if GENERATED_MARKER not in existing:
            raise TunnelError("refusing_to_overwrite_non_generated_config")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    resolved = parse_mappings(mappings)
    return {
        "kind": KIND,
        "output": str(path),
        "tunnel_name": tunnel_name,
        "routes": [
            {"service": name, "hostname": host, "origin": PUBLIC_SERVICES[name]}
            for name, host in resolved
        ],
        "catch_all": "http_status:404",
        "activated": False,
    }


def find_cloudflared(explicit: str | None = None) -> str:
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return str(candidate)
        raise CloudflaredUnavailable()
    found = shutil.which("cloudflared")
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if packages.is_dir():
            for candidate in sorted(packages.glob("Cloudflare.cloudflared*/cloudflared.exe")):
                if candidate.is_file():
                    return str(candidate)
    raise CloudflaredUnavailable()


def validate_ingress(
    config: Path,
    *,
    cloudflared: str | None = None,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    path = Path(config)
    if not path.is_file():
        raise TunnelError("config_missing")
    binary = find_cloudflared(cloudflared)
    command = [binary, "tunnel", "--config", str(path), "ingress", "validate"]
    execute = runner or (
        lambda argv: subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    )
    try:
        completed = execute(command)
    except (OSError, subprocess.TimeoutExpired):
        raise CloudflaredUnavailable()
    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    return {
        "kind": KIND,
        "config": str(path),
        "command": command,
        "exit": int(completed.returncode),
        "valid": completed.returncode == 0,
        "output_tail": output.splitlines()[-5:],
        "network_used": False,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    render_parser = subparsers.add_parser("render", help="write a loopback ingress config")
    render_parser.add_argument(
        "--map",
        action="append",
        default=[],
        metavar="SERVICE=HOSTNAME",
        help="repeatable; services: chat, claw",
    )
    render_parser.add_argument("--output", required=True)
    render_parser.add_argument("--tunnel-name")
    render_parser.add_argument("--force", action="store_true")

    validate_parser = subparsers.add_parser("validate", help="offline cloudflared validation")
    validate_parser.add_argument("--config", required=True)
    validate_parser.add_argument("--cloudflared")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "render":
            report = write_ingress(
                Path(args.output),
                args.map,
                tunnel_name=args.tunnel_name,
                force=args.force,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        if args.command == "validate":
            report = validate_ingress(Path(args.config), cloudflared=args.cloudflared)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["valid"] else 1
    except TunnelError as error:
        print(json.dumps({"kind": KIND, "status": "error", "error": str(error)}))
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
