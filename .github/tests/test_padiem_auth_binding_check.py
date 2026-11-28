import contextlib
import importlib.util
import io
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'scripts/padiem_auth_binding_check.py'
spec = importlib.util.spec_from_file_location('binding_check', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class BindingCheck(unittest.TestCase):
    def test_exact_names_types_and_no_values_needed(self):
        settings = {'success': True, 'result': {'bindings': [{'name': 'AUTH_STATE', 'type': 'durable_object_namespace', 'class_name': 'AuthStateObject'}, {'name': 'SECRET', 'type': 'secret_text', 'text': 'synthetic'}]}}
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

    def test_baseline_rejects_empty_duplicate_unknown_and_value_fields(self):
        settings = {'success': True, 'result': {'bindings': [{'name': 'X', 'type': 'plain_text'}]}}
        for entry in ({'name':'', 'type':'plain_text'}, {'name':' ', 'type':'plain_text'},
                      {'name':'X', 'type':'unknown'}, {'name':'X', 'type':'plain_text', 'text':'synthetic'},
                      {'name':'X', 'type':'plain_text', 'sha256':'synthetic'}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                m.verify(settings, {'status':'approved', 'bindings':[entry]})
        with self.assertRaises(ValueError):
            m.verify(settings, {'status':'approved', 'bindings':[{'name':'X','type':'plain_text'}]*2})

    def test_mismatch_reports_only_names_and_kinds_never_values(self):
        settings = {'success': True, 'result': {'bindings': [
            {'name': 'AUTH_STATE', 'type': 'durable_object_namespace', 'class_name': 'AuthStateObject', 'namespace_id': 'synthetic-namespace-id'},
            {'name': 'NEW_ON_LIVE', 'type': 'secret_text', 'text': 'synthetic-secret-value'},
            {'name': 'CHANGED_TYPE', 'type': 'plain_text', 'text': 'synthetic-live-var-value'},
        ]}}
        baseline = {'status': 'approved', 'bindings': [
            {'name': 'AUTH_STATE', 'type': 'durable_object_namespace'},
            {'name': 'CHANGED_TYPE', 'type': 'secret_text'},
            {'name': 'ONLY_IN_BASELINE', 'type': 'service'},
        ]}
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(ValueError) as caught:
            m.verify(settings, baseline)
        self.assertEqual(str(caught.exception), 'binding metadata mismatch')
        out = stderr.getvalue()
        # 이름·종류 차이만 나온다: 운영에만 있는 것, 기준에만 있는 것, 종류가 바뀐 것 양쪽.
        self.assertIn('binding only in live: NEW_ON_LIVE (secret_text)', out)
        self.assertIn('binding only in live: CHANGED_TYPE (plain_text)', out)
        self.assertIn('binding only in baseline: CHANGED_TYPE (secret_text)', out)
        self.assertIn('binding only in baseline: ONLY_IN_BASELINE (service)', out)
        # 일치하는 바인딩은 출력하지 않는다.
        self.assertNotIn('AUTH_STATE', out)
        # 값·목적지·식별자는 가짜 값을 넣어도 출력에 없다.
        for secret in ('synthetic-secret-value', 'synthetic-live-var-value', 'synthetic-namespace-id', 'AuthStateObject'):
            self.assertNotIn(secret, out)
        self.assertNotIn('binding metadata matches approved baseline', out)

    def test_mismatch_live_only_and_baseline_only_sets(self):
        baseline = {'status': 'approved', 'bindings': [{'name': 'GONE', 'type': 'plain_text'}]}
        settings = {'success': True, 'result': {'bindings': [{'name': 'ADDED', 'type': 'secret_text'}]}}
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(ValueError):
            m.verify(settings, baseline)
        out = stderr.getvalue()
        self.assertIn('binding only in live: ADDED (secret_text)', out)
        self.assertIn('binding only in baseline: GONE (plain_text)', out)

    def test_runtime_value_and_service_target_changes_are_detected(self):
        a = [{'name':'AUTH','type':'service','service':'identity'}, {'name':'VAR','type':'plain_text','text':'original'}]
        b = [{'name':'AUTH','type':'service','service':'wrong'}, {'name':'VAR','type':'plain_text','text':'original'}]
        c = [{'name':'AUTH','type':'service','service':'identity'}, {'name':'VAR','type':'plain_text','text':'changed'}]
        self.assertNotEqual(m.binding_pairs(a), m.binding_pairs(b))
        self.assertNotEqual(m.binding_pairs(a), m.binding_pairs(c))


if __name__ == '__main__':
    unittest.main()
