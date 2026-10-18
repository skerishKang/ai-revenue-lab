from __future__ import annotations

import asyncio
import hashlib

import pytest

import backup_contract as contract

PAYLOAD = b"fixture-archive-bytes"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
FILE_BYTES = b"fixture file content\n"
FILE_SHA = hashlib.sha256(FILE_BYTES).hexdigest()


def manifest(**overrides):
    data = {
        "kind": contract.MANIFEST_KIND,
        "contract_version": contract.CONTRACT_VERSION,
        "machine": "com2",
        "backup_id": "20261019t120000z",
        "created_at": "2026-10-19T12:00:00Z",
        "payload_file": "payload.tar.gz",
        "payload_bytes": len(PAYLOAD),
        "payload_sha256": PAYLOAD_SHA,
        "file_count": 1,
        "total_bytes": len(FILE_BYTES),
        "files": [
            {"path": "root-1/state/state.txt", "bytes": len(FILE_BYTES), "sha256": FILE_SHA}
        ],
        "exclusions": {"secret_paths": 2, "secret_content": 0},
    }
    data.update(overrides)
    return data


def test_parse_route_accepts_payload_manifest_verify_and_capabilities():
    base = "https://backup.internal/internal/v1/com2-backup"
    assert contract.parse_route(base + "/capabilities") == contract.BackupRoute("capabilities")
    for action in ("payload", "manifest", "verify"):
        route = contract.parse_route(f"{base}/com2/20261019t120000z/{action}")
        assert route == contract.BackupRoute(action, "com2", "20261019t120000z")


@pytest.mark.parametrize(
    "url",
    [
        "https://backup.internal/internal/v1/com2-backup/COM2/20261019t120000z/payload",
        "https://backup.internal/internal/v1/com2-backup/com2/../payload",
    ],
)
def test_parse_route_rejects_invalid_names(url):
    with pytest.raises(contract.BackupError):
        contract.parse_route(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://backup.internal/internal/v1/com2-backup/com2/20261019t120000z/delete",
        "https://backup.internal/internal/v1/com2-backup/com2/20261019t120000z",
        "https://backup.internal/other",
    ],
)
def test_parse_route_returns_none_for_unknown_paths(url):
    assert contract.parse_route(url) is None


def test_object_keys_are_isolated_by_machine_and_backup():
    assert (
        contract.object_key("com2", "20261019t120000z", "payload")
        == "com2-backup/v1/com2/20261019t120000z/payload.tar.gz"
    )
    assert (
        contract.object_key("com2", "20261019t120000z", "manifest")
        == "com2-backup/v1/com2/20261019t120000z/manifest.json"
    )
    with pytest.raises(contract.BackupError):
        contract.object_key("com2", "20261019t120000z", "verify")


@pytest.mark.parametrize(
    "header, expected",
    [
        ("Bearer fixture-token-value", "fixture-token-value"),
        ("bearer abc", "abc"),
        (None, None),
        ("Basic abc", None),
        ("Bearer ", None),
        ("Bearer two words", None),
    ],
)
def test_parse_bearer(header, expected):
    assert contract.parse_bearer(header) == expected


def test_token_comparison_rejects_empty_and_different_values():
    assert contract.token_matches("fixture-token-value", "fixture-token-value")
    assert not contract.token_matches("fixture-token-value", "other-value")
    assert not contract.token_matches("", "")
    assert not contract.token_matches("anything", "")


def test_gate_is_literal_true_only():
    assert contract.gate_is_open("true") is True
    for value in ("True", "1", True, None, " true"):
        assert contract.gate_is_open(value) is False


def test_validate_manifest_accepts_the_documented_shape():
    result = contract.validate_manifest(manifest(), "com2", "20261019t120000z")
    assert result["file_count"] == 1
    assert result["payload_sha256"] == PAYLOAD_SHA


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "OTHER"},
        {"machine": "com3"},
        {"payload_file": "other.tar.gz"},
        {"payload_bytes": contract.MAX_PAYLOAD_BYTES + 1},
        {"payload_sha256": "not-a-digest"},
        {"file_count": 2},
        {"total_bytes": 999},
        {"files": [{"path": "../escape", "bytes": 1, "sha256": FILE_SHA}]},
        {"files": [{"path": "/absolute", "bytes": 1, "sha256": FILE_SHA}]},
        {"files": [{"path": "root-1/a\\b", "bytes": 1, "sha256": FILE_SHA}]},
        {"unknown": "field"},
    ],
)
def test_validate_manifest_rejects_invalid_shapes(overrides):
    with pytest.raises(contract.BackupError) as exc:
        contract.validate_manifest(manifest(**overrides), "com2", "20261019t120000z")
    assert exc.value.code == "invalid_manifest"


def test_validate_manifest_rejects_duplicate_paths():
    entry = {"path": "root-1/a.txt", "bytes": 1, "sha256": FILE_SHA}
    with pytest.raises(contract.BackupError):
        contract.validate_manifest(
            manifest(files=[entry, dict(entry)], file_count=2, total_bytes=2),
            "com2",
            "20261019t120000z",
        )


def test_integrity_result_matches_and_detects_tampering():
    valid = contract.validate_manifest(manifest(), "com2", "20261019t120000z")
    result = contract.integrity_result(valid, PAYLOAD)
    assert result == {
        "bytes": len(PAYLOAD),
        "sha256": PAYLOAD_SHA,
        "file_count": 1,
        "total_bytes": len(FILE_BYTES),
    }
    with pytest.raises(contract.BackupError) as exc:
        contract.integrity_result(valid, PAYLOAD + b"tampered")
    assert exc.value.code == "integrity_mismatch"


def test_read_bounded_body_rejects_oversize_without_full_buffering():
    chunks = [b"a" * 10, b"b" * 10]

    async def run():
        async def read(_limit):
            return chunks.pop(0) if chunks else None

        return await contract.read_bounded_body(read, 15)

    with pytest.raises(contract.BackupError) as exc:
        asyncio.run(run())
    assert exc.value.code == "request_too_large"


def test_declared_content_length_rejects_negative_and_malformed():
    assert contract.declared_content_length(None) is None
    assert contract.declared_content_length("12") == 12
    for value in ("-1", "abc", True):
        with pytest.raises(contract.BackupError):
            contract.declared_content_length(value)
