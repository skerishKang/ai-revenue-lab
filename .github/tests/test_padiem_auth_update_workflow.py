import unittest
from pathlib import Path
class Workflow(unittest.TestCase):
    def test_key_generation_not_invoked_and_preflight_is_required(self):
        text = (Path(__file__).resolve().parents[1] / 'workflows/padiem-auth-update-gate.yml').read_text()
        self.assertNotIn('bootstrap-deploy', text)
        self.assertNotIn('secret put', text)
        self.assertIn('wrangler deploy --config apps/padiem-auth/wrangler.toml --keep-vars', text)
        self.assertIn('wrangler rollback "$ROLLBACK_VERSION"', text)
        self.assertIn('Require previous exact-SHA readonly', text)
        self.assertIn('padiem_auth_update_preflight.py', text)
        self.assertIn('padiem_auth_update_rollback_check.py', text)
        self.assertIn('padiem_auth_update_served.py', text)
if __name__ == '__main__': unittest.main()
