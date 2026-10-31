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

    def test_workflow_wires_exact_target_and_existing_secret_check(self):
        workflow = (Path(__file__).resolve().parents[1] / 'workflows/b54-control-plane-identity-production-redeploy.yml').read_text(encoding='utf-8')
        job = workflow[workflow.index('  rollback-identity-worker:'):]
        self.assertIn('wrangler versions view "$ROLLBACK_VERSION"', job)
        self.assertIn('wrangler deployments list --name "$IDENTITY_WORKER"', job)
        self.assertIn('wrangler rollback "$ROLLBACK_VERSION" --name "$IDENTITY_WORKER"', job)
        self.assertIn('target["resources"]["bindings"]', job)
        self.assertIn('validate_post(', job)
        self.assertIn('CONTROL_PLANE_IDENTITY_LOOKUP_KEY', job)
        self.assertIn('GOOGLE_CONNECT_TICKET_KEY', job)
        self.assertIn('IDENTITY_ROLLBACK_POSTCHECK=FAIL', job)

if __name__ == '__main__': unittest.main()
