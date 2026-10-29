import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'scripts/padiem_auth_binding_check.py'
spec = importlib.util.spec_from_file_location('binding_check', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class BindingCheck(unittest.TestCase):
    def test_exact_names_types_and_no_values_needed(self):
        settings = {'success': True, 'result': {'bindings': [{'name': 'AUTH_STATE', 'type': 'durable_object_namespace'}, {'name': 'SECRET', 'type': 'secret_text', 'text': 'synthetic'}]}}
        baseline = {'status': 'approved', 'bindings': [{'name': 'SECRET', 'type': 'secret_text'}, {'name': 'AUTH_STATE', 'type': 'durable_object_namespace'}]}
        self.assertTrue(m.verify(settings, baseline))
        for mutate in ({'status': 'pending', 'bindings': baseline['bindings']}, {'status': 'approved', 'bindings': baseline['bindings'][:1]}, {'status': 'approved', 'bindings': baseline['bindings'] + baseline['bindings'][:1]}):
            with self.assertRaises(ValueError):
                m.verify(settings, mutate)

    def test_incomplete_settings_and_duplicate_names_rejected(self):
        baseline = {'status': 'approved', 'bindings': [{'name': 'x', 'type': 'secret_text'}]}
        for settings in ({'success': False}, {'success': True, 'result': {'bindings': [{'name': 'x', 'type': 'secret_text'}, {'name': 'x', 'type': 'plain_text'}]}}):
            with self.assertRaises(ValueError):
                m.verify(settings, baseline)


if __name__ == '__main__':
    unittest.main()
