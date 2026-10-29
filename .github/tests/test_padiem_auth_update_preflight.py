import importlib.util
import sys
import unittest
from pathlib import Path
root = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location('preflight', root / 'padiem_auth_update_preflight.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
version = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
base = {'status': 'approved', 'bindings': [{'name': 'IDENTITY_AUTHORITY', 'type': 'service', 'service': 'padiem-control-plane-identity'}, {'name': 'AUTH_STATE', 'type': 'durable_object_namespace', 'class_name': 'AuthStateObject'}]}
config = {'name': 'padiem-auth', 'services': [{'binding': 'IDENTITY_AUTHORITY', 'service': 'padiem-control-plane-identity'}], 'durable_objects': {'bindings': [{'name': 'AUTH_STATE', 'class_name': 'AuthStateObject'}]}, 'migrations': [{'tag': 'v1', 'new_sqlite_classes': ['AuthStateObject']}]}
class Check(unittest.TestCase):
    def test_config_rejects_target_change_and_vars(self):
        m.validate_config(config, base)
        with self.assertRaises(ValueError): m.validate_config({**config, 'vars': {'X': 'bad'}}, base)
        with self.assertRaises(ValueError): m.validate_config({**config, 'services': []}, base)
    def test_split_or_changed_active_version_is_rejected(self):
        m.verify_deployment([{'created_on': '2026-01-01', 'versions': [{'version_id': version, 'percentage': 100}]}], version)
        with self.assertRaises(ValueError): m.verify_deployment([{'versions': [{'version_id': version, 'percentage': 50}]}], version)
        with self.assertRaises(ValueError): m.verify_deployment([], version)
if __name__ == '__main__': unittest.main()
