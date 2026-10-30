import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / ".github/scripts/padiem_auth_update_key_guard.py"
spec = importlib.util.spec_from_file_location("key_guard", PATH)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class KeyPreservation(unittest.TestCase):
    def test_key_change_and_missing_kid_are_rejected(self):
        original = {"keys": [{"kid": guard.EXPECTED_KID, "kty": "EC", "x": "x1", "y": "y1"}]}
        self.assertTrue(guard.verify_jwks(original, original))
        for changed in (
            {"keys": [{"kid": guard.EXPECTED_KID, "kty": "EC", "x": "x2", "y": "y1"}]},
            {"keys": [{"kid": "other", "kty": "EC", "x": "x1", "y": "y1"}]},
            {"keys": []},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                guard.verify_jwks(original, changed)

    def test_real_command_builder_requires_keep_vars(self):
        args = guard.deploy_command("apps/padiem-auth/wrangler.toml", keep_vars=True)
        self.assertIn("--keep-vars", args)
        self.assertNotIn("--secrets-file", args)
        with self.assertRaises(ValueError):
            guard.deploy_command("apps/padiem-auth/wrangler.toml", keep_vars=False)
        # The executable entry point must refuse before invoking wrangler.
        result = subprocess.run([sys.executable, str(PATH), "deploy"], capture_output=True,
                                text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("guard refused", result.stderr)


if __name__ == "__main__":
    unittest.main()
