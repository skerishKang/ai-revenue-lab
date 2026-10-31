"""Offline Ed25519 evidence and COM2 publisher tests using RFC 8032 TEST 1.

No keys are generated. The sole private seed below is a published test vector.
Network and child processes are blocked unless explicitly replaced with fakes.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / ".github/scripts"))
import chat_publish_rehearsal as publisher
import chat_rehearsal_evidence as evidence

SHA = "a" * 40
GENERATION = "20261031T042000Z"
NOW = 1_800_000_000
PRIVATE_TEXT = "synthetic-private-path-and-auth-must-not-appear"
TEST1_SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
TEST2_PUBLIC = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")


@pytest.fixture(autouse=True)
def no_external_effects(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("test attempted an unstubbed network or process call")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(urllib.request, "build_opener", denied)


@pytest.fixture
def keys():
    key = Ed25519PrivateKey.from_private_bytes(TEST1_SEED)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return private, public


def timestamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def raw_report(*, finish=NOW - 60):
    return {
        "target": evidence.STAGING_TARGET, "dry_run": False, "failed_stage": None,
        "private_detail": PRIVATE_TEXT, "rollback": [],
        "stages": [
            {"stage": stage, "passed": True, "skipped": False,
             "started_utc": timestamp(finish - 8 + index),
             "ended_utc": timestamp(finish - 7 + index),
             "detail": PRIVATE_TEXT, "commands": [["read", "/private/db/" + PRIVATE_TEXT]]}
            for index, stage in enumerate(evidence.REHEARSAL_STAGES)
        ],
    }


def payload(*, now=NOW):
    return evidence.summarize(raw_report(finish=now - 60), main_sha=SHA, generation_id=GENERATION,
                              generation_sha256="b" * 64, now=now)


def verify(envelope, public, *, now=NOW, sha=SHA, generation=GENERATION):
    return evidence.verify_summary(envelope, public, expected_sha=sha, expected_generation=generation, now=now)


def test_signed_summary_roundtrip_uses_pinned_public_key(keys):
    private, public = keys
    data = payload()
    envelope = evidence.sign_summary(data, private)
    assert verify(envelope, public) == data
    assert set(envelope) == {"payload", "signature"}
    assert len(base64.b64decode(envelope["signature"])) == 64


@pytest.mark.parametrize("tamper", ["payload", "signature", "public_key"])
def test_forgery_and_mismatched_key_are_rejected(keys, tamper):
    private, public = keys
    envelope = evidence.sign_summary(payload(), private)
    if tamper == "payload":
        envelope["payload"]["generation_sha256"] = "c" * 64
    elif tamper == "signature":
        signature = bytearray(base64.b64decode(envelope["signature"]))
        signature[0] ^= 1
        envelope["signature"] = base64.b64encode(signature).decode()
    else:
        public = Ed25519PublicKey.from_public_bytes(TEST2_PUBLIC).public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    with pytest.raises(evidence.EvidenceError, match="evidence_signature_invalid"):
        verify(envelope, public)


@pytest.mark.parametrize("sha,generation,reason", [
    ("d" * 40, GENERATION, "evidence_sha_mismatch"),
    (SHA, "different-generation", "evidence_generation_mismatch"),
])
def test_signed_identity_is_bound_to_expected_sha_and_generation(keys, sha, generation, reason):
    private, public = keys
    with pytest.raises(evidence.EvidenceError, match=reason):
        verify(evidence.sign_summary(payload(), private), public, sha=sha, generation=generation)


@pytest.mark.parametrize("offset,accepted", [(-1, True), (0, False), (1, False)])
def test_24_hour_expiry_boundary_is_exact(keys, offset, accepted):
    private, public = keys
    envelope = evidence.sign_summary(payload(), private)
    clock = envelope["payload"]["finished_at"] + 86400 + offset
    if accepted:
        verify(envelope, public, now=clock)
    else:
        with pytest.raises(evidence.EvidenceError, match="evidence_expired"):
            verify(envelope, public, now=clock)


@pytest.mark.parametrize("changes,reason", [
    ({"issued_at": NOW + 1}, "evidence_timestamp_order"),
    ({"finished_at": NOW + 1, "issued_at": NOW + 1, "expires_at": NOW + 86401}, "evidence_timestamp_order"),
    ({"expires_at": NOW + 172800}, "evidence_expiry_invalid"),
    ({"issued_at": True}, "evidence_timestamp_invalid"),
    ({"result": "FAIL"}, "evidence_not_pass"),
    ({"issuer": "other-host"}, "evidence_scope_mismatch"),
    ({"generation_sha256": "invalid"}, "evidence_digest_invalid"),
])
def test_even_valid_signatures_cannot_authorize_invalid_claims(keys, changes, reason):
    private, public = keys
    data = payload()
    data.update(changes)
    with pytest.raises(evidence.EvidenceError, match=reason):
        verify(evidence.sign_summary(data, private), public)


def test_envelope_cannot_supply_its_own_trust_key(keys):
    private, public = keys
    envelope = evidence.sign_summary(payload(), private)
    envelope["public_key"] = public.decode()
    with pytest.raises(evidence.EvidenceError, match="evidence_envelope_invalid"):
        verify(envelope, public)


def test_summary_excludes_raw_report_commands_and_paths():
    source = raw_report()
    data = evidence.summarize(source, main_sha=SHA, generation_id=GENERATION,
                              generation_sha256="b" * 64, now=NOW)
    assert set(data) == evidence.PAYLOAD_FIELDS
    serialized = evidence.canonical(data)
    assert PRIVATE_TEXT.encode() not in serialized and b"/private/db/" not in serialized
    assert data["report_sha256"] == hashlib.sha256(evidence.canonical(source)).hexdigest()


@pytest.mark.parametrize("finish,reason", [(NOW - 86400, "evidence_expired"), (NOW + 1, "evidence_expired")])
def test_summarize_cannot_refresh_old_or_future_report(finish, reason):
    with pytest.raises(evidence.EvidenceError, match=reason):
        evidence.summarize(raw_report(finish=finish), main_sha=SHA, generation_id=GENERATION,
                           generation_sha256="b" * 64, now=NOW)


@pytest.mark.parametrize("text,reason", [
    ('{"a":1,"a":2}', "json_duplicate_key"),
    ('{"a":NaN}', "json_constant_invalid"),
    ('{"a":Infinity}', "json_constant_invalid"),
])
def test_noncanonical_json_is_refused(text, reason):
    with pytest.raises(evidence.EvidenceError, match=reason):
        evidence.parse_json(text)


@pytest.mark.parametrize("url", ["http://evidence.invalid/file", "https://user:password@evidence.invalid/file", "https://evidence.invalid:8443/file", "https://evidence.invalid/file#fragment"])
def test_only_https_credential_free_evidence_urls_are_accepted(url):
    with pytest.raises(evidence.EvidenceError, match="evidence_https_url_required"):
        evidence.https_url(url)


@pytest.fixture
def publishing(tmp_path, keys, monkeypatch):
    private, public = keys
    private_file, public_file = tmp_path / "test-vector-private.pem", tmp_path / "test-vector-public.pem"
    private_file.write_bytes(private)
    public_file.write_bytes(public)
    pointer = tmp_path / "current_generation.json"
    pointer.write_text(json.dumps({"generation": GENERATION}))
    generations = tmp_path / "generations"
    source = generations / GENERATION / "chat.sqlite3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic immutable generation; not a production database")
    argv = [
        "--base-url", evidence.STAGING_TARGET, "--staging-db", str(tmp_path / "staging.sqlite3"),
        "--sentinel", str(tmp_path / "MAINTENANCE"), "--generation-pointer", str(pointer),
        "--generations-dir", str(generations), "--snapshot-a", str(tmp_path / "a.sqlite3"),
        "--snapshot-b", str(tmp_path / "b.sqlite3"), "--mirror-inventory", str(tmp_path / "inventory.json"),
        "--confirm-stop-tick", "--confirm-stop-wss", "--confirm-stop-queue",
    ]
    args_file = tmp_path / "args.json"
    args_file.write_text(json.dumps(argv))
    args = SimpleNamespace(main_sha=SHA, generation_id=GENERATION, out=str(tmp_path / "evidence.json"),
                           key_file=str(private_file), public_key_file=str(public_file), args_file=str(args_file),
                           upload_url_file=None, upload_existing=None)
    events = []
    monkeypatch.setattr(publisher.rehearsal, "guard_target", lambda config: events.append("existing_target_guard"))
    state = SimpleNamespace(args=args, argv=argv, pointer=pointer, source=source, events=events,
                            child_hook=None, child_marker="REHEARSAL_SUMMARY=PASS stages=8 passed=8 skipped=0 failed=0 elapsed=1.0",
                            report=raw_report(finish=int(datetime.now(timezone.utc).timestamp()) - 5))
    def command(argv):
        if argv[:2] == ["git", "rev-parse"]:
            events.append("checkout_sha")
            return SHA
        if argv[:2] == ["git", "status"]:
            events.append("clean_tree")
            return ""
        if argv[:2] == ["git", "ls-remote"]:
            events.append("fresh_main")
            return SHA + "\trefs/heads/main"
        events.append("run_rehearsal")
        parsed = publisher.rehearsal._parser().parse_args(argv[2:])
        pinned = Path(parsed.generation_pointer)
        assert pinned != pointer
        assert json.loads(pinned.read_bytes())["generation"] == GENERATION
        if state.child_hook:
            state.child_hook(parsed)
        Path(parsed.json).write_text(json.dumps(state.report))
        return state.child_marker
    monkeypatch.setattr(publisher, "command", command)
    return state


def test_publisher_runs_child_then_rechecks_source_and_signs_minimal_summary(publishing, keys, capsys):
    state = publishing
    before = state.source.read_bytes()
    assert publisher.publish(state.args) == 0
    assert state.events == ["existing_target_guard", "checkout_sha", "clean_tree", "fresh_main",
                            "run_rehearsal", "checkout_sha", "clean_tree", "fresh_main"]
    assert state.source.read_bytes() == before
    result = evidence.parse_json(Path(state.args.out).read_bytes())
    evidence.verify_summary(result, keys[1], expected_sha=SHA, expected_generation=GENERATION)
    assert result["payload"]["generation_sha256"] == hashlib.sha256(before).hexdigest()
    assert PRIVATE_TEXT not in Path(state.args.out).read_text()
    output = capsys.readouterr().out
    assert output.strip() == "CHAT_REHEARSAL_EVIDENCE=SIGNED UPLOADED=no"
    assert str(state.pointer) not in output


def test_publisher_pins_pointer_against_a_to_b_to_a_change(publishing):
    state = publishing
    def drift(parsed):
        state.pointer.write_text(json.dumps({"generation": "generation-B"}))
        # The child still reads A from its private pointer snapshot.
        assert json.loads(Path(parsed.generation_pointer).read_bytes())["generation"] == GENERATION
        state.pointer.write_text(json.dumps({"generation": GENERATION}))
    state.child_hook = drift
    assert publisher.publish(state.args) == 0
    assert evidence.parse_json(Path(state.args.out).read_bytes())["payload"]["generation_id"] == GENERATION


def test_publisher_refuses_generation_bytes_changed_during_rehearsal(publishing):
    state = publishing
    state.child_hook = lambda parsed: state.source.write_bytes(b"changed-generation")
    with pytest.raises(evidence.EvidenceError, match="publisher_generation_changed"):
        publisher.publish(state.args)
    assert not Path(state.args.out).exists()


def test_publisher_rechecks_main_after_child_before_signing(publishing, monkeypatch):
    state = publishing
    original = publisher.command
    checkout_reads = 0
    def command(argv):
        nonlocal checkout_reads
        if argv[:2] == ["git", "rev-parse"]:
            checkout_reads += 1
            if checkout_reads == 2:
                return "d" * 40
        return original(argv)
    monkeypatch.setattr(publisher, "command", command)
    with pytest.raises(evidence.EvidenceError, match="publisher_checkout_sha_mismatch"):
        publisher.publish(state.args)
    assert "run_rehearsal" in state.events
    assert not Path(state.args.out).exists()


@pytest.mark.parametrize("flag", [
    "--generation-pointer", "--generations-dir", "--staging-db", "--sentinel",
    "--snapshot-a", "--snapshot-b", "--mirror-inventory",
])
def test_publisher_refuses_relative_paths_before_child(publishing, flag):
    state = publishing
    argv = list(state.argv)
    argv[argv.index(flag) + 1] = "relative/path"
    Path(state.args.args_file).write_text(json.dumps(argv))
    with pytest.raises(evidence.EvidenceError, match="publisher_absolute_paths_required"):
        publisher.publish(state.args)
    assert "run_rehearsal" not in state.events
    assert not Path(state.args.out).exists()


@pytest.mark.parametrize("flag", ["--dry-run", "--synthetic"])
def test_publisher_refuses_nonreal_rehearsal_before_child_or_key_read(publishing, monkeypatch, flag):
    state = publishing
    Path(state.args.args_file).write_text(json.dumps(state.argv + [flag]))
    Path(state.args.key_file).unlink()
    with pytest.raises(evidence.EvidenceError, match="publisher_real_rehearsal_required"):
        publisher.publish(state.args)
    assert state.events == []
    assert not Path(state.args.out).exists()


@pytest.mark.parametrize("extra", [["--json", "/private/old-report.json"], ["--json=/private/old-report.json"]])
def test_publisher_does_not_accept_caller_selected_old_report(publishing, extra):
    state = publishing
    Path(state.args.args_file).write_text(json.dumps(state.argv + extra))
    with pytest.raises(evidence.EvidenceError, match="publisher_json_is_managed"):
        publisher.publish(state.args)
    assert state.events == []


def test_publisher_refuses_child_pass_marker_without_real_pass_report(publishing):
    state = publishing
    state.report["stages"][4]["passed"] = False
    with pytest.raises(evidence.EvidenceError, match="rehearsal_stage_not_executed"):
        publisher.publish(state.args)
    assert not Path(state.args.out).exists()


def test_publisher_refuses_report_without_child_pass_marker(publishing):
    state = publishing
    state.child_marker = "REHEARSAL_SUMMARY=FAIL"
    with pytest.raises(evidence.EvidenceError, match="publisher_pass_marker_missing"):
        publisher.publish(state.args)
    assert not Path(state.args.out).exists()


def test_publisher_cannot_sign_stale_report_even_after_new_child_call(publishing):
    state = publishing
    state.report = raw_report(finish=int(datetime.now(timezone.utc).timestamp()) - 90000)
    with pytest.raises(evidence.EvidenceError, match="evidence_expired"):
        publisher.publish(state.args)
    assert not Path(state.args.out).exists()


def test_publisher_refuses_invalid_child_args_without_printing_them(publishing, capsys):
    state = publishing
    Path(state.args.args_file).write_text(json.dumps(state.argv + ["--unknown=" + PRIVATE_TEXT]))
    with pytest.raises(evidence.EvidenceError, match="publisher_args_invalid"):
        publisher.publish(state.args)
    assert PRIVATE_TEXT not in capsys.readouterr().err


@pytest.mark.parametrize("which,answer,reason", [
    ("rev-parse", "d" * 40, "publisher_checkout_sha_mismatch"),
    ("status", " M uncommitted", "publisher_checkout_dirty"),
    ("ls-remote", "d" * 40 + "\trefs/heads/main", "publisher_main_sha_mismatch"),
])
def test_publisher_requires_clean_exact_current_main(monkeypatch, which, answer, reason):
    def command(argv):
        return answer if argv[1] == which else ("" if argv[1] == "status" else SHA if argv[1] == "rev-parse" else SHA + "\trefs/heads/main")
    monkeypatch.setattr(publisher, "command", command)
    with pytest.raises(evidence.EvidenceError, match=reason):
        publisher.exact_source(SHA)


def test_publisher_nonzero_child_exit_cannot_be_hidden_by_pass_output(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=1,
        stdout="REHEARSAL_SUMMARY=PASS stages=8 passed=8 skipped=0 failed=0 elapsed=1",
        stderr=PRIVATE_TEXT,
    ))
    with pytest.raises(evidence.EvidenceError, match="publisher_command_failed") as error:
        publisher.command(["synthetic-child"])
    assert PRIVATE_TEXT not in str(error.value)
    assert PRIVATE_TEXT not in capsys.readouterr().out


def test_publisher_existing_output_is_never_overwritten(publishing):
    state = publishing
    Path(state.args.out).write_text("keep existing")
    with pytest.raises(evidence.EvidenceError, match="publisher_output_exists"):
        publisher.publish(state.args)
    assert Path(state.args.out).read_text() == "keep existing"


def test_upload_sends_only_signed_summary_and_never_logs_presigned_url(tmp_path, keys, monkeypatch, capsys):
    envelope = evidence.sign_summary(payload(), keys[0])
    url_file = tmp_path / "upload-url.txt"
    url = "https://storage.invalid/evidence.json?signature=" + PRIVATE_TEXT
    url_file.write_text(url)
    sent = []
    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
    def open_request(req, **kwargs):
        sent.append(req)
        return Response()
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: SimpleNamespace(open=open_request))
    publisher.upload(envelope, str(url_file))
    assert sent[0].method == "PUT" and sent[0].full_url == url
    assert sent[0].data == evidence.canonical(envelope)
    assert not sent[0].has_header("Authorization")
    assert PRIVATE_TEXT not in capsys.readouterr().out


def test_upload_error_does_not_expose_presigned_url(tmp_path, keys, monkeypatch, capsys):
    url_file = tmp_path / "upload-url.txt"
    url_file.write_text("https://storage.invalid/file?signature=" + PRIVATE_TEXT)
    def fail(*args, **kwargs):
        raise OSError(PRIVATE_TEXT)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: SimpleNamespace(open=fail))
    with pytest.raises(evidence.EvidenceError, match="publisher_upload_failed") as error:
        publisher.upload(evidence.sign_summary(payload(), keys[0]), str(url_file))
    assert PRIVATE_TEXT not in str(error.value)
    assert PRIVATE_TEXT not in capsys.readouterr().out


def test_upload_existing_verifies_without_resigning_or_rerunning(publishing, monkeypatch):
    state = publishing
    publisher.publish(state.args)
    signed_bytes = Path(state.args.out).read_bytes()
    args = copy.copy(state.args)
    args.upload_existing, args.upload_url_file = args.out, "external-upload-url"
    args.args_file = args.key_file = args.out = None
    def forbidden(*args, **kwargs):
        raise AssertionError("upload retry must not sign or rerun")
    monkeypatch.setattr(publisher, "sign_summary", forbidden)
    monkeypatch.setattr(publisher, "summarize", forbidden)
    uploads = []
    monkeypatch.setattr(publisher, "upload", lambda envelope, path: uploads.append((envelope, path)))
    state.events.clear()
    assert publisher.publish(args) == 0
    assert state.events == ["checkout_sha", "clean_tree", "fresh_main"]
    assert Path(args.upload_existing).read_bytes() == signed_bytes
    assert len(uploads) == 1


def test_upload_existing_rejects_mixed_signing_arguments(publishing):
    state = publishing
    state.args.upload_existing = "/outside/existing.json"
    state.args.upload_url_file = "/outside/url.txt"
    with pytest.raises(evidence.EvidenceError, match="publisher_upload_args_invalid"):
        publisher.publish(state.args)


def test_upload_existing_cannot_refresh_expired_evidence(publishing, keys, monkeypatch):
    state = publishing
    old = payload(now=int(datetime.now(timezone.utc).timestamp()) - 90000)
    existing = Path(state.args.out)
    existing.write_bytes(evidence.canonical(evidence.sign_summary(old, keys[0])))
    state.args.upload_existing, state.args.upload_url_file = str(existing), "external-upload-url"
    state.args.args_file = state.args.key_file = state.args.out = None
    uploads = []
    monkeypatch.setattr(publisher, "upload", lambda *a: uploads.append(a))
    with pytest.raises(evidence.EvidenceError, match="evidence_expired"):
        publisher.publish(state.args)
    assert uploads == []
    assert state.events == []
