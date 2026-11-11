import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from padiem_auth_client_delta import fingerprints, verify_delta


def dump(obj):
    return json.dumps(obj, sort_keys=True)


class ClientDelta(unittest.TestCase):
    def test_reviewed_edit_passes_and_everything_else_refuses(self):
        live = {"alpha": {"redirect": ["old"], "public": "original"},
                "beta": {"public": "other"},
                "b62-staging": {"id": "b62-staging", "public": "migrated"}}
        reviewed_edit = {"alpha": {"redirect": ["old"], "public": "edited"},
                         "beta": {"public": "other"},
                         "b62-staging": {"id": "b62-staging", "public": "migrated"}}
        self.assertTrue(verify_delta(fingerprints(dump(live)), dump(reviewed_edit), dump(reviewed_edit)))
        for bad in (
            # a client addition or removal changes the set
            {**reviewed_edit, "extra": {}},
            {"alpha": reviewed_edit["alpha"], "beta": reviewed_edit["beta"]},
            # a changed client that does not match the reviewed target
            {**reviewed_edit, "alpha": {"redirect": ["other"], "public": "edited"}},
            # the reviewed staging client is never touched
            {**reviewed_edit, "b62-staging": {"id": "b62-staging", "public": "changed"}},
        ):
            with self.subTest(case=list(bad)), self.assertRaises(ValueError):
                verify_delta(fingerprints(dump(live)), dump(bad), dump(reviewed_edit))
        # an unchanged candidate always passes
        self.assertTrue(verify_delta(fingerprints(dump(live)), dump(live), dump(reviewed_edit)))
        with self.assertRaises(ValueError):
            verify_delta({}, dump(live), dump(reviewed_edit))

    def test_duplicate_json_key_refused(self):
        with self.assertRaises(ValueError):
            fingerprints('{"a":{},"a":{}}')


if __name__ == "__main__":
    unittest.main()
