import unittest
from pathlib import Path
class Workflow(unittest.TestCase):
    def test_key_generation_not_invoked_and_preflight_is_required(self):
        text = (Path(__file__).resolve().parents[1] / 'workflows/padiem-auth-update-gate.yml').read_text()
        self.assertNotIn('bootstrap-deploy', text)
        self.assertNotIn('secret put', text)
        self.assertIn('padiem_auth_update_key_guard.py deploy --keep-vars', text)
        from importlib.util import spec_from_file_location, module_from_spec
        path = Path(__file__).resolve().parents[1] / 'scripts/padiem_auth_update_key_guard.py'
        spec = spec_from_file_location('real_key_guard', path)
        guard = module_from_spec(spec)
        spec.loader.exec_module(guard)
        self.assertEqual(guard.deploy_command('apps/padiem-auth/wrangler.toml', keep_vars=True),
                         ['npx', '--no-install', 'wrangler', 'deploy', '--config',
                          'apps/padiem-auth/wrangler.toml', '--keep-vars'])
        with self.assertRaises(ValueError):
            guard.deploy_command('apps/padiem-auth/wrangler.toml', keep_vars=False)
        self.assertIn('wrangler rollback "$ROLLBACK_VERSION"', text)
        self.assertIn('Require previous exact-SHA readonly', text)
        self.assertIn('padiem_auth_update_preflight.py', text)
        self.assertIn('padiem_auth_update_rollback_check.py', text)
        self.assertIn('padiem_auth_update_served.py', text)
if __name__ == '__main__': unittest.main()
