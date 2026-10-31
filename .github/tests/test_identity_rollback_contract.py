import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from identity_rollback_contract import validate_confirmation, validate_post, FAIL

class RollbackContract(unittest.TestCase):
    def test_valid_and_invalid_confirmation(self):
        sha = 'a'*40
        cur = '11111111-1111-4111-8111-111111111111'
        target = '22222222-2222-4222-8222-222222222222'
        phrase = f'ROLLBACK_PADIEM_CONTROL_PLANE_IDENTITY_rollback_identity_worker_{sha}_{cur}_{target}'
        self.assertTrue(validate_confirmation('rollback_identity_worker', sha, cur, target, phrase))
        with self.assertRaises(ValueError):
            validate_confirmation('rollback_identity_worker', sha, cur, target, phrase+'x')
    def test_post_success_and_version_or_binding_mismatch(self):
        target = '22222222-2222-4222-8222-222222222222'
        bindings = [{'name':'A','type':'secret_text'},{'name':'B','type':'durable_object_namespace','class_name':'X'}]
        good = [{'versions':[{'version_id':target,'percentage':100}]}]
        self.assertTrue(validate_post(good,target,bindings,bindings))
        for deployments, after in (([{'versions':[{'version_id':target,'percentage':50}]}], bindings), (good,bindings[:1])):
            with self.assertRaisesRegex(ValueError,FAIL):
                validate_post(deployments,target,bindings,after)

if __name__ == '__main__': unittest.main()
