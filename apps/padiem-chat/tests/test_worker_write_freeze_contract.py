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
    def test_absent_off_and_invalid(self):
        for value in (None, '', 'off', 'false', '0'):
            self.assertFalse(freeze.freeze_active(value))
        self.assertTrue(freeze.freeze_active('unexpected'))
        self.assertTrue(freeze.freeze_active('true'))
