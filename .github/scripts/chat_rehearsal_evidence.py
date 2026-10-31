"""Signed COM2 rehearsal summaries. Keys are provisioned outside this module.

Ed25519 is provided by the host's existing cryptography dependency. The gate
gets only a pinned public key; no key in an artifact can establish trust.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

MAX_EVIDENCE_AGE_SECONDS = 24 * 60 * 60
SCHEMA = "padiem-chat-rehearsal/v1"
SIGNING_CONTEXT = (SCHEMA + "\x00").encode()
STAGING_TARGET = "https://chat-com2-staging.padiem.net"
REHEARSAL_STAGES = (
    "preflight", "stop_before_window", "freeze_on", "freeze_probe",
    "snapshot_pair", "reflect", "parity", "object_reference",
)
PAYLOAD_FIELDS = {
    "schema", "issuer", "target", "main_sha", "generation_id", "generation_sha256",
    "report_sha256", "started_at", "finished_at", "issued_at", "expires_at",
    "result", "stages", "skipped_stages",
}


class EvidenceError(Exception):
    """Fixed public-safe error code, never caller input or secret content."""


def require(ok, code):
    if not ok:
        raise EvidenceError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def parse_json(raw):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, "json_duplicate_key")
            out[key] = value
        return out

    def invalid(_value):
        raise EvidenceError("json_constant_invalid")

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    except (ValueError, TypeError):
        raise EvidenceError("response_json_invalid") from None


def https_url(value):
    try:
        url = urlsplit(value)
        valid = url.scheme == "https" and bool(url.hostname) and not url.username and not url.password and not url.fragment and url.port in (None, 443)
    except (ValueError, TypeError):
        valid = False
    require(valid, "evidence_https_url_required")
    return value


def identity(main_sha, generation_id):
    require(isinstance(main_sha, str) and re.fullmatch(r"[0-9a-f]{40}", main_sha), "evidence_sha_invalid")
    require(isinstance(generation_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", generation_id), "evidence_generation_invalid")


def utc_timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "rehearsal_timestamp_invalid")
        return parsed.timestamp()
    except (ValueError, TypeError, AttributeError):
        raise EvidenceError("rehearsal_timestamp_invalid") from None


def validate_rehearsal(report, *, maximum_age_hours=None):
    require(isinstance(report, dict), "rehearsal_report_invalid")
    require(report.get("target") == STAGING_TARGET, "rehearsal_target")
    require(report.get("dry_run") is False and report.get("failed_stage") is None, "rehearsal_not_pass")
    stages = report.get("stages", [])
    require(isinstance(stages, list) and all(isinstance(s, dict) for s in stages), "rehearsal_order")
    require([s.get("stage") for s in stages] == list(REHEARSAL_STAGES), "rehearsal_order")
    for stage in stages:
        require(stage.get("passed") is True and stage.get("started_utc") and stage.get("ended_utc"), "rehearsal_stage_not_executed")
        if maximum_age_hours is not None:
            start, end = utc_timestamp(stage["started_utc"]), utc_timestamp(stage["ended_utc"])
            now = datetime.now(timezone.utc).timestamp()
            require(start <= end <= now and (now - start) / 3600 <= maximum_age_hours, "rehearsal_report_stale")
        if stage.get("skipped"):
            require(stage["stage"] == "parity" and
                    stage.get("detail") == "post_apply_comparison_skipped: reflect_pre_apply_match is the evidence" and
                    stages[5].get("detail") == "exit=0 expect=STAGING_DB_FROM_GENERATION=READY+CHAT_COPY_PARITY=MATCH+STAGING_DB_PENDING_APPLIED",
                    "rehearsal_skipped")


def public_key(pem):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        key = serialization.load_pem_public_key(pem)
        require(isinstance(key, Ed25519PublicKey), "evidence_public_key_invalid")
        return key
    except (ValueError, TypeError):
        raise EvidenceError("evidence_public_key_invalid") from None


def sign_summary(payload, private_pem):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    try:
        key = serialization.load_pem_private_key(private_pem, password=None)
        require(isinstance(key, Ed25519PrivateKey), "evidence_private_key_invalid")
        signature = key.sign(SIGNING_CONTEXT + canonical(payload))
    except (ValueError, TypeError):
        raise EvidenceError("evidence_private_key_invalid") from None
    return {"payload": payload, "signature": base64.b64encode(signature).decode("ascii")}


def verify_summary(envelope, public_pem, *, expected_sha, expected_generation, now=None):
    from cryptography.exceptions import InvalidSignature
    identity(expected_sha, expected_generation)
    require(isinstance(envelope, dict) and set(envelope) == {"payload", "signature"}, "evidence_envelope_invalid")
    payload = envelope["payload"]
    require(isinstance(payload, dict) and set(payload) == PAYLOAD_FIELDS, "evidence_payload_invalid")
    try:
        signature = base64.b64decode(envelope["signature"], validate=True)
        require(len(signature) == 64, "evidence_signature_invalid")
        public_key(public_pem).verify(signature, SIGNING_CONTEXT + canonical(payload))
    except (InvalidSignature, ValueError, TypeError):
        raise EvidenceError("evidence_signature_invalid") from None
    require(payload["schema"] == SCHEMA and payload["issuer"] == "COM2" and payload["target"] == STAGING_TARGET, "evidence_scope_mismatch")
    require(payload["main_sha"] == expected_sha, "evidence_sha_mismatch")
    require(payload["generation_id"] == expected_generation, "evidence_generation_mismatch")
    require(payload["result"] == "PASS" and payload["stages"] == list(REHEARSAL_STAGES) and
            payload["skipped_stages"] in ([], ["parity"]), "evidence_not_pass")
    for field in ("generation_sha256", "report_sha256"):
        require(isinstance(payload[field], str) and re.fullmatch(r"[0-9a-f]{64}", payload[field]), "evidence_digest_invalid")
    for field in ("started_at", "finished_at", "issued_at", "expires_at"):
        require(type(payload[field]) is int, "evidence_timestamp_invalid")
    clock = datetime.now(timezone.utc).timestamp() if now is None else now
    require(0 <= payload["started_at"] <= payload["finished_at"] <= payload["issued_at"] <= clock,
            "evidence_timestamp_order")
    require(payload["expires_at"] == payload["finished_at"] + MAX_EVIDENCE_AGE_SECONDS,
            "evidence_expiry_invalid")
    require(clock < payload["expires_at"], "evidence_expired")
    return payload


def summarize(report, *, main_sha, generation_id, generation_sha256, now=None):
    identity(main_sha, generation_id)
    validate_rehearsal(report)
    times = [(utc_timestamp(s["started_utc"]), utc_timestamp(s["ended_utc"])) for s in report["stages"]]
    require(all(start <= end for start, end in times) and
            all(times[i][1] <= times[i + 1][0] for i in range(len(times) - 1)), "evidence_timestamp_order")
    clock = int(datetime.now(timezone.utc).timestamp() if now is None else now)
    start, finish = int(times[0][0]), int(times[-1][1])
    require(0 <= start <= finish <= clock < finish + MAX_EVIDENCE_AGE_SECONDS, "evidence_expired")
    return {
        "schema": SCHEMA, "issuer": "COM2", "target": STAGING_TARGET,
        "main_sha": main_sha, "generation_id": generation_id, "generation_sha256": generation_sha256,
        "report_sha256": hashlib.sha256(canonical(report)).hexdigest(),
        "started_at": start, "finished_at": finish, "issued_at": clock,
        "expires_at": finish + MAX_EVIDENCE_AGE_SECONDS, "result": "PASS",
        "stages": list(REHEARSAL_STAGES),
        "skipped_stages": [s["stage"] for s in report["stages"] if s.get("skipped")],
    }
