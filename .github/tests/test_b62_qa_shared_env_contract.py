"""The self-hosted browser QA cache holds external tools only, never repo code."""
from __future__ import annotations

from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PREPARE = ROOT / '.github/scripts/b62_qa_prepare.sh'
WORKFLOW = ROOT / '.github/workflows/b62-browser-qa-unified.yml'


class SharedEnvContract(unittest.TestCase):
    def test_prepare_script_keeps_repository_packages_out_of_shared_cache(self):
        text = PREPARE.read_text(encoding='utf-8')
        self.assertNotIn('UV_PROJECT_ENVIRONMENT', text)
        self.assertNotIn('UV_NO_SYNC', text)
        self.assertNotIn('uv sync', text)
        self.assertIn('PLAYWRIGHT_BROWSERS_PATH', text)
        self.assertIn("version='1.55.0'", text)
        self.assertIn('playwright==${version}', text)

    def test_prepare_script_creates_cache_dir_before_opening_lock(self):
        lines = [line.strip() for line in PREPARE.read_text(encoding='utf-8').splitlines()]
        mkdir = next(i for i, line in enumerate(lines) if line.startswith('mkdir -p'))
        lock = next(i for i, line in enumerate(lines) if line.startswith('exec 9>'))
        self.assertLess(mkdir, lock)

    def test_every_self_hosted_job_proves_packages_come_from_its_own_checkout(self):
        doc = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
        for name, job in doc['jobs'].items():
            if name == 'plan' or 'fromJSON(\'["self-hosted","padiem-com2-ci"]\')' not in str(job.get('runs-on')):
                continue
            steps = job['steps']
            names = [step.get('name', '') for step in steps]
            self.assertIn('Prove repository packages come from this checkout', names, name)
            uv_step = next(s for s in steps if s.get('name') == 'Prepare isolated B62 uv environment')
            self.assertNotIn('if', uv_step, name)
            self.assertEqual(uv_step['uses'], './.github/actions/b62-uv')
            proof = next(s for s in steps if s.get('name') == 'Prove repository packages come from this checkout')
            self.assertIn("runner.environment == 'self-hosted'", proof['if'])
            self.assertIn('padiem_ai_core', proof['run'])
            self.assertIn('padiem_control_plane', proof['run'])
            self.assertIn('GITHUB_WORKSPACE', proof['run'])


if __name__ == '__main__':
    unittest.main()
