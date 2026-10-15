"""#4139 dry-run bundle fingerprint is deterministic, sealed and negative-only."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from io import StringIO
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import connector_bundle_fingerprint as proof

SHA = "a" * 40
WORKER = "padiem-local-agent-broker-state"


class BundleFingerprintTest(unittest.TestCase):
    def _build(self, root: Path) -> Path:
        b = root / "bundle"
        (b / "pkg").mkdir(parents=True)
        (b / "main.js").write_bytes(b"synthetic-worker-code")
        (b / "pkg" / "worker.py").write_bytes(b"print('synthetic')\n")
        return b

    def test_same_bytes_have_same_fingerprint_and_no_raw_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = self._build(root)
            first = proof.fingerprint(b, worker=WORKER, source_sha=SHA)
            second = proof.fingerprint(b, worker=WORKER, source_sha=SHA)
            self.assertEqual(first, second)
            self.assertEqual(first["file_count"], 2)
            self.assertEqual(first["source_git_sha"], SHA)
            self.assertEqual(len(first["dry_run_bundle_sha256"]), 64)
            self.assertEqual(first["build_type"], "synthetic_dry_run")
            self.assertFalse(first["served_version_bound"])
            self.assertFalse(first["reviewed_source_to_served_bundle_attested"])
            self.assertEqual(first["production_mutation"], 0)
            serialized = json.dumps(first)
            for secret in ("synthetic-worker-code", "pkg/worker.py", tmp):
                self.assertNotIn(secret, serialized)
            (b / "pkg" / "worker.py").write_bytes(b"print('changed')\n")
            self.assertNotEqual(first["dry_run_bundle_sha256"], proof.fingerprint(
                b, worker=WORKER, source_sha=SHA)["dry_run_bundle_sha256"])

    def test_valid_identity_and_edge_source_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self._build(Path(tmp))
            for worker in sorted(proof._WORKERS):
                result = proof.fingerprint(b, worker=worker, source_sha="b" * 40)
                self.assertEqual(result["worker"], worker)

    def test_no_empty_or_unreviewed_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "empty"
            bundle.mkdir()
            with self.assertRaises(proof.FingerprintError):
                proof.fingerprint(bundle, worker=WORKER, source_sha=SHA)
            b = self._build(root)
            for worker, source_sha in (
                ("unreviewed-worker", SHA), (WORKER, "short"),
                (WORKER, "A" * 40), (WORKER, "g" * 40),
            ):
                with self.assertRaises(proof.FingerprintError):
                    proof.fingerprint(b, worker=worker, source_sha=source_sha)

    def test_symlink_and_credentials_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = self._build(root)
            (b / "token.env").write_bytes(b"synthetic-private-token")
            with self.assertRaises(proof.FingerprintError):
                proof.fingerprint(b, worker=WORKER, source_sha=SHA)
            (b / "token.env").unlink()
            try:
                (b / "link").symlink_to(b / "main.js")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unsupported")
            with self.assertRaises(proof.FingerprintError):
                proof.fingerprint(b, worker=WORKER, source_sha=SHA)

    def test_cli_writes_single_redacted_sealed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = self._build(root)
            output = root / "receipt.json"
            with patch.object(sys, "argv", [
                "fingerprint", "--worker", WORKER, "--source-sha", SHA,
                "--bundle-dir", str(b), "--output", str(output)
            ]):
                log = StringIO()
                with redirect_stdout(log):
                    self.assertEqual(proof.main(), 0)
                self.assertIn("CONNECTOR_DRY_RUN_BUNDLE_FINGERPRINT=PASS", log.getvalue())
                self.assertIn("SERVED_SOURCE_PARITY_ATTESTED=NO", log.getvalue())
                self.assertNotIn(tmp, log.getvalue())
                self.assertEqual(json.loads(output.read_text())["file_count"], 2)
                with redirect_stdout(log):
                    self.assertEqual(proof.main(), 1)
                self.assertEqual(json.loads(output.read_text())["file_count"], 2)
                self.assertNotIn(tmp, log.getvalue())

    def test_output_cannot_be_inside_bundle_or_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = self._build(root)
            for output in (b / "receipt.json", root / "existing.json"):
                if output.name == "existing.json":
                    output.write_text("existing")
                with patch.object(sys, "argv", [
                    "fingerprint", "--worker", WORKER, "--source-sha", SHA,
                    "--bundle-dir", str(b), "--output", str(output)
                ]):
                    with redirect_stdout(StringIO()):
                        self.assertEqual(proof.main(), 1)


if __name__ == "__main__":
    unittest.main()
