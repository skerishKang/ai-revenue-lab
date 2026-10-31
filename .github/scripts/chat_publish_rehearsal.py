#!/usr/bin/env python3
"""COM2 operator: run the existing rehearsal, attest it, optionally upload it.

No sign-an-arbitrary-old-report mode and no key generation. A private key PEM
and optional presigned upload URL file are supplied from outside the checkout.
Only the small signed summary leaves COM2, never the full report or DB.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chat_cutover_rehearsal as rehearsal
import chat_d1_digest as digest
import chat_staging_db_from_generation as staging
from chat_rehearsal_evidence import (
    EvidenceError, canonical, https_url, identity, parse_json, require,
    sign_summary, summarize, verify_summary,
)

ROOT = Path(__file__).resolve().parents[2]


def external(path):
    resolved = Path(path).resolve()
    require(not resolved.is_relative_to(ROOT), "publisher_path_must_be_outside_repo")
    return resolved


def command(argv):
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, check=False)
    require(result.returncode == 0, "publisher_command_failed")
    return result.stdout.strip()


def exact_source(sha):
    require(command(["git", "rev-parse", "HEAD"]) == sha, "publisher_checkout_sha_mismatch")
    require(command(["git", "status", "--porcelain", "--untracked-files=all"]) == "", "publisher_checkout_dirty")
    remote = command(["git", "ls-remote", "https://github.com/skerishKang/ai-revenue-lab.git", "refs/heads/main"])
    require(remote.split() == [sha, "refs/heads/main"], "publisher_main_sha_mismatch")


def generation(config, expected):
    gen, source = staging.resolve_generation(config.generation_pointer, config.generations_dir)
    require(gen == expected, "publisher_generation_mismatch")
    return digest.file_sha256(source)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def upload(envelope, url_file):
    url = https_url(external(url_file).read_text(encoding="utf-8").strip())
    req = urllib.request.Request(url, data=canonical(envelope), method="PUT", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
            require(200 <= response.status < 300, "publisher_upload_failed")
    except (OSError, ValueError):
        raise EvidenceError("publisher_upload_failed") from None


def publish(args):
    identity(args.main_sha, args.generation_id)
    if args.upload_existing:
        require(bool(args.upload_url_file) and not any((args.args_file, args.key_file, args.out)), "publisher_upload_args_invalid")
        envelope = parse_json(external(args.upload_existing).read_bytes())
        verify_summary(envelope, external(args.public_key_file).read_bytes(), expected_sha=args.main_sha, expected_generation=args.generation_id)
        exact_source(args.main_sha)
        upload(envelope, args.upload_url_file)
        print("CHAT_REHEARSAL_EVIDENCE=VERIFIED UPLOADED=yes")
        return 0
    require(all((args.args_file, args.key_file, args.out)), "publisher_run_args_missing")
    out, key_file, public_file = external(args.out), external(args.key_file), external(args.public_key_file)
    require(not out.exists(), "publisher_output_exists")
    argv = parse_json(external(args.args_file).read_bytes())
    require(isinstance(argv, list) and all(isinstance(a, str) for a in argv), "publisher_args_invalid")
    require(not any(a == "--json" or a.startswith("--json=") for a in argv), "publisher_json_is_managed")
    parser = rehearsal._parser()
    def private_args_error(_message):
        raise EvidenceError("publisher_args_invalid")
    parser.error = private_args_error
    parsed = parser.parse_args(argv)
    config = rehearsal.config_from_args(parsed)
    require(not parsed.synthetic and not parsed.dry_run, "publisher_real_rehearsal_required")
    # The child runs in ROOT, while this CLI may be invoked from elsewhere.
    # Reject relative source paths so both processes inspect exactly the same
    # generation/snapshots and a signed hash cannot attest a different file.
    paths = [getattr(config, name) for name in (
        "staging_db", "sentinel", "generation_pointer", "generations_dir",
        "snapshot_a", "snapshot_b", "migrations_dir", "plan_out",
    )] + list(config.mirror_inventories)
    require(all(Path(path).is_absolute() for path in paths if path), "publisher_absolute_paths_required")
    # No private key is opened until every existing guard and provenance check
    # passes. This does not authorize a production rehearsal.
    rehearsal.guard_target(config)
    require(config.base_url == "https://chat-com2-staging.padiem.net", "publisher_staging_origin_required")
    exact_source(args.main_sha)
    before = generation(config, args.generation_id)
    pointer = Path(config.generation_pointer).read_bytes()
    require(parse_json(pointer).get("generation") == args.generation_id, "publisher_pointer_changed")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="chat-rehearsal-", dir=out.parent) as temporary:
        pinned = Path(temporary) / "generation.json"
        pinned.write_bytes(pointer)
        report_path = Path(temporary) / "rehearsal.json"
        # argparse takes the final occurrence: even --generation-pointer=...
        # in the original args cannot make the child follow a moving pointer.
        output = command([
            sys.executable, str(ROOT / ".github/scripts/chat_cutover_rehearsal.py"), *argv,
            "--generation-pointer", str(pinned), "--json", str(report_path),
        ])
        require(re.search(r"^REHEARSAL_SUMMARY=PASS stages=8 passed=8 skipped=[01] failed=0 elapsed=", output, re.MULTILINE), "publisher_pass_marker_missing")
        report = parse_json(report_path.read_bytes())
        exact_source(args.main_sha)
        require(generation(config, args.generation_id) == before, "publisher_generation_changed")
        payload = summarize(report, main_sha=args.main_sha, generation_id=args.generation_id, generation_sha256=before)
        envelope = sign_summary(payload, key_file.read_bytes())
        verify_summary(envelope, public_file.read_bytes(), expected_sha=args.main_sha, expected_generation=args.generation_id)
        # Exclusive creation: an existing evidence file is never overwritten.
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(canonical(envelope) + b"\n")
    if args.upload_url_file:
        upload(envelope, args.upload_url_file)
    print("CHAT_REHEARSAL_EVIDENCE=SIGNED" + (" UPLOADED=yes" if args.upload_url_file else " UPLOADED=no"))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("main-sha", "generation-id", "public-key-file"):
        parser.add_argument("--" + name, required=True)
    for name in ("args-file", "key-file", "out"):
        parser.add_argument("--" + name)
    parser.add_argument("--upload-existing", help="retry upload of an already signed, still-valid summary; no signing or rehearsal")
    parser.add_argument("--upload-url-file", help="external file holding a provisioned presigned HTTPS PUT URL")
    args = parser.parse_args(argv)
    try:
        return publish(args)
    except EvidenceError as error:
        print("CHAT_REHEARSAL_EVIDENCE=REFUSED reason=" + str(error))
    except Exception:
        print("CHAT_REHEARSAL_EVIDENCE=REFUSED reason=publisher_failed")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
