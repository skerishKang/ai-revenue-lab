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

    def test_every_browser_job_is_hosted_and_self_hosted_only_steps_are_guarded(self):
        doc = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
        browser_jobs = [name for name in doc['jobs'] if name != 'plan']
        self.assertEqual(len(browser_jobs), 17)
        for name in browser_jobs:
            job = doc['jobs'][name]
            self.assertEqual(job['runs-on'], 'ubuntu-24.04', name)
            steps = job['steps']
            names = [step.get('name', '') for step in steps]
            for step_name in ('Resolve B62', 'Install pinned Playwright'):
                step = next(s for s in steps if s.get('name') == step_name)
                self.assertNotIn('if', step, f'{name}/{step_name}')
            # Jobs that carry COM2-only steps must prove checkout purity, and
            # that proof must skip on hosted runners. Other lanes own no shared cache.
            proofs = [s for s in steps if s.get('name') == 'Prove repository packages come from this checkout']
            self.assertLessEqual(len(proofs), 1, name)
            if 'Prepare reusable QA environment (self-hosted)' in names:
                self.assertEqual(len(proofs), 1, name)
                proof = proofs[0]
                self.assertEqual(proof.get('if'), "runner.environment == 'self-hosted'", name)
                self.assertIn('padiem_ai_core', proof['run'])
                self.assertIn('padiem_control_plane', proof['run'])
                self.assertIn('GITHUB_WORKSPACE', proof['run'])
            else:
                self.assertEqual(proofs, [], name)


if __name__ == '__main__':
    unittest.main()
