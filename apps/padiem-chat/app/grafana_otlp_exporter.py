"""Grafana Cloud OTLP log exporter, externally hosted (not Cloudflare Logs).

Opt-in, fail-closed. No event payload text/user IDs/cookies/headers/secrets.
Only the bounded projections from request_telemetry are accepted.
"""
from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from . import httpx_compat as httpx

_EVENT_KEYS = frozenset({
    "event", "service", "ts", "request_id", "request_id_source",
    "method", "route", "product", "status", "duration_ms", "outcome",
    "stage", "code", "model", "provider", "b14_request_id",
})
_SECRET_PATTERN = re.compile(r"(?:Bearer|Basic|token|secret|cookie|authorization|password)", re.I)

def validated_otlp_endpoint(raw: str) -> str:
    if not isinstance(raw, str) or len(raw) > 220:
        raise ValueError("INVALID_OTLP_ENDPOINT")
    parts = urlsplit(raw)
    if (parts.scheme != "https" or parts.username or parts.password
            or parts.query or parts.fragment
            or not parts.hostname or not parts.hostname.endswith(".grafana.net")
            or parts.path not in ("/otlp/v1/logs", "/otlp/v1/logs/")):
        raise ValueError("INVALID_OTLP_ENDPOINT")
    return raw

def safe_otlp_payload(events: list[dict[str, object]]) -> dict:
    if not 1 <= len(events) <= 12:
        raise ValueError("INVALID_EVENT_BATCH")
    rows = []
    timestamp_ns = str(time.time_ns())
    for event in events:
        if not isinstance(event, dict) or not set(event).issubset(_EVENT_KEYS):
            raise ValueError("UNSAFE_EVENT_FIELDS")
        if event.get("event") not in ("http_request", "ai_stage"):
            raise ValueError("UNSAFE_EVENT_TYPE")
        for key, value in event.items():
            if key in ("model", "provider"):
                # These internal routing attributes never leave our Worker.
                continue
            if isinstance(value, (list, dict)):
                raise ValueError("UNSAFE_COMPLEX_LOG_VALUE")
            if isinstance(value, str) and _SECRET_PATTERN.search(value):
                # Only allow metadata fields known to have this vocabulary,
                # never accidentally ingest token-like arbitrary response data.
                if value not in ("client_error", "server_error"):
                    raise ValueError("SUSPECT_SECRET_IN_EVENT")
        # Internal provider/model routing metadata is excluded from external
        # Grafana Cloud even if present in the in-process diagnostic event.
        safe = {key: value for key, value in event.items()
                if key not in ("model", "provider")}
        rows.append({
            "timeUnixNano": timestamp_ns,
            "severityText": "ERROR" if event.get("outcome") in ("error", "server_error") else "INFO",
            "body": {"stringValue": json.dumps(safe, separators=(",", ":"), sort_keys=True)},
        })
    return {"resourceLogs":[{"resource":{"attributes":[
      {"key":"service.name","value":{"stringValue":"padiem-chat"}},
      {"key":"deployment.environment","value":{"stringValue":"production"}},
    ]},"scopeLogs":[{"scope":{"name":"padiem.request.telemetry"}, "logRecords":rows}]}]}

@dataclass(frozen=True)
class GrafanaOtlpExporter:
    endpoint: str
    username: str
    token: str

    def __post_init__(self) -> None:
        validated_otlp_endpoint(self.endpoint)
        if not re.fullmatch(r"[0-9]{2,20}", self.username):
            raise ValueError("INVALID_OTLP_USERNAME")
        if not isinstance(self.token, str) or not (20 <= len(self.token) <= 4096):
            raise ValueError("INVALID_OTLP_TOKEN")

    async def __call__(self, events: list[dict[str, object]]) -> None:
        payload = safe_otlp_payload(events)
        secret_pair = (self.username + ":" + self.token).encode("utf-8")
        authorization = "Basic " + base64.b64encode(secret_pair).decode("ascii")
        # B62's Worker-safe httpx shim uses global JS fetch, with timeout
        # and redirects disabled. Caller also caps the entire export deadline.
        async with httpx.AsyncClient(timeout=0.8, follow_redirects=False) as client:
            async with client.stream("POST", self.endpoint,
                 headers={"Authorization":authorization,"Content-Type":"application/json"},
                 content=json.dumps(payload, separators=(",", ":")).encode("utf-8")) as response:
                if response.status_code not in (200, 202, 204):
                    raise ValueError("OTLP_INGEST_REJECTED")
