"""Guard direct Wrangler deploy commands in production-environment jobs."""
from pathlib import Path
import re
import unittest

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / 'workflows'
DEPLOY = re.compile(r'\b(?:py)?wrangler\s+deploy\b')


def missing_keep_vars(text):
    document = yaml.safe_load(text) or {}
    errors = []
    for name, job in (document.get('jobs') or {}).items():
        if not isinstance(job, dict):
            continue
        environment = job.get('environment')
        if isinstance(environment, dict):
            environment = environment.get('name')
        if environment != 'production':
            continue
        for step in job.get('steps', []):
            run = step.get('run', '')
            if not isinstance(run, str):
                continue
            # Join shell continuation lines so options can be on later lines.
            run = re.sub(r'\\\s*\n\s*', ' ', run)
            for line in run.splitlines():
                line = line.strip()
                if not line or line.startswith('#') or not DEPLOY.search(line):
                    continue
                # A trailing comment cannot provide an actual command option.
                command = line.split(' #', 1)[0]
                if not re.search(r'(?:^|\s)--keep-vars(?:\s|$|[;|&>])', command):
                    errors.append(f'{name}: {line}')
    return errors


class ProductionKeepVarsTest(unittest.TestCase):
    def test_repository_workflows(self):
        files = sorted(WORKFLOWS.glob('*.yml')) + sorted(WORKFLOWS.glob('*.yaml'))
        self.assertTrue(files)
        failures = []
        for path in files:
            failures += [f'{path.name}: {error}' for error in missing_keep_vars(path.read_text(encoding='utf-8'))]
        self.assertEqual([], failures, '\n'.join(failures))

    def test_production_detection_and_multiline(self):
        fixture = '''jobs:
  production_job:
    environment: {name: production}
    steps:
      - run: |
          npx wrangler deploy --keep-vars
          uv run pywrangler deploy \\
            --keep-vars --config x
          pywrangler deploy --strict # --keep-vars
  staging_job:
    environment: staging
    steps:
      - run: wrangler deploy
'''
        errors = missing_keep_vars(fixture)
        self.assertEqual(len(errors), 1)
        self.assertIn('production_job', errors[0])

    def test_production_option_missing(self):
        self.assertEqual(len(missing_keep_vars('''jobs:
  x:
    environment: production
    steps:
      - run: npx wrangler deploy --strict
''')), 1)


if __name__ == '__main__':
    unittest.main()
