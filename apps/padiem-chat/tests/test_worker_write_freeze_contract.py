import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('freeze', Path(__file__).parents[1] / 'app' / 'worker_write_freeze.py')
freeze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freeze)

class FreezeContract(unittest.TestCase):
    def test_mutations_and_websockets_are_refused_and_reads_continue(self):
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            self.assertTrue(freeze.reject_request('true', method))
        for method in ('GET', 'HEAD', 'OPTIONS'):
            self.assertFalse(freeze.reject_request('true', method))
        self.assertTrue(freeze.reject_request('true', 'GET', 'websocket'))
        for path in ('/auth/google/callback', '/auth/lovetree/start'):
            self.assertTrue(freeze.reject_request('true', 'GET', path=path))
            self.assertFalse(freeze.reject_request('off', 'GET', path=path))
    def test_absent_off_and_invalid(self):
        for value in (None, '', 'off', 'false', '0'):
            self.assertFalse(freeze.freeze_active(value))
        self.assertTrue(freeze.freeze_active('unexpected'))
        self.assertTrue(freeze.freeze_active('true'))

class RegisteredGetMutationCoverage(unittest.TestCase):
    def test_known_writing_get_handlers_are_in_freeze_set(self):
        import ast
        source = (Path(__file__).parents[1] / 'app' / 'app_factory.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        writing_handlers = {'google_callback', 'lovetree_handoff_start'}
        found = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'Route' or len(node.args) < 2:
                continue
            path, handler = node.args[:2]
            if isinstance(path, ast.Constant) and isinstance(handler, ast.Name) and handler.id in writing_handlers:
                found[handler.id] = path.value
        self.assertEqual(set(found), writing_handlers)
        self.assertTrue(set(found.values()).issubset(freeze.WRITE_ON_GET))

    def test_registered_mutation_methods_are_refused(self):
        import ast
        source = (Path(__file__).parents[1] / 'app' / 'app_factory.py').read_text(encoding='utf-8')
        count = 0
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'Route': continue
            for kw in node.keywords:
                if kw.arg != 'methods' or not isinstance(kw.value, (ast.List, ast.Tuple)): continue
                for method in kw.value.elts:
                    if isinstance(method, ast.Constant) and method.value in {'POST','PUT','PATCH','DELETE'}:
                        self.assertTrue(freeze.reject_request('true', method.value)); count += 1
        self.assertGreater(count, 0)
