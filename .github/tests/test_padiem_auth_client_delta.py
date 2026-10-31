import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from padiem_auth_client_delta import fingerprints, verify_delta


def dump(obj):
    return json.dumps(obj, sort_keys=True)


class ClientDelta(unittest.TestCase):
    def test_only_reviewed_addition_preserves_existing(self):
        old = {"alpha": {"redirect": ["old"], "public": "original"},
               "beta": {"public": "other"}}
        staging = {"id": "b62-staging", "public": "synthetic"}
        candidate = {**old, "b62-staging": staging}
        self.assertTrue(verify_delta(fingerprints(dump(old)), dump(candidate), dump(candidate)))
        for bad in (
            {**candidate, "alpha": {"redirect": ["new"], "public": "original"}},
            {**candidate, "extra": {}},
            {"alpha": old["alpha"], "b62-staging": staging},
            {**old, "b62-staging": {"id": "b62-staging", "public": "changed"}},
        ):
            with self.subTest(case=list(bad)), self.assertRaises(ValueError):
                verify_delta(fingerprints(dump(old)), dump(bad), dump(candidate))
        with self.assertRaises(ValueError):
            verify_delta(fingerprints(dump(candidate)), dump(candidate), dump(candidate))

    def test_duplicate_json_key_refused(self):
        with self.assertRaises(ValueError):
            fingerprints('{"a":{},"a":{}}')


if __name__ == "__main__":
    unittest.main()
