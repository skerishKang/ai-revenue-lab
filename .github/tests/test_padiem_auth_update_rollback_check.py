import importlib.util
import sys
import unittest
from pathlib import Path
root = Path(__file__).resolve().parents[1] / 'scripts'; sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location('rollback', root / 'padiem_auth_update_rollback_check.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class Check(unittest.TestCase):
    def test_approved_baseline_and_exact_version_required(self):
        baseline = {'status': 'approved', 'bindings': [{'name': 'SECRET', 'type': 'secret_text'}]}
        version = {'id': 'v1', 'resources': {'bindings': [{'name': 'SECRET', 'type': 'secret_text'}]}}
        self.assertTrue(m.verify_rollback(baseline, version, 'v1'))
        for invalid in ({**baseline, 'status': 'pending'}, {**baseline, 'bindings': []}):
            with self.assertRaises(ValueError): m.verify_rollback(invalid, version, 'v1')
        with self.assertRaises(ValueError): m.verify_rollback(baseline, {'id': 'v2', 'resources': {'bindings': []}}, 'v1')
if __name__ == '__main__': unittest.main()
