"""Owner decision 2026-11-25: Chat D1 is archive-only, COM2 is canonical.

D1 apply jobs fail before any mutation, readonly stays available, table-drop
rebuild migrations can never be executed, and the COM2 ledger check is owned
by the existing deploy script and surfaced in the gate summary.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / '.github' / 'scripts'
WORKFLOWS = ROOT / '.github' / 'workflows'
SPEC = importlib.util.spec_from_file_location(
    'b62_d1_gate_archive', SCRIPTS / 'b62_d1_migrate_gate.py'
)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)

APPLY_JOBS = {
    'b54-claw-history-014-015-apply-gate.yml': 'production-additive-repair',
    'b62-auth-d1-migration-012-gate.yml': 'apply-migration-012',
    'b62-claw-d1-migration-008-gate.yml': 'apply-migration-008',
    'b62-claw-d1-migration-040-gate.yml': 'apply-migration-040',
    'b62-claw-d1-migration-054-gate.yml': 'apply-migration-054',
    'b62-claw-mesh-d1-migration-048-gate.yml': 'apply-migration-048',
    'b62-claw-mesh-d1-migration-049-gate.yml': 'apply-migration-049',
    'b62-d1-migrate-gate.yml': 'apply',
    'b62-d1-migration-062-gate.yml': 'apply-migration-062',
    'b62-d1-migration-081-gate.yml': 'apply-migration-081',
}
MESSAGE = 'Chat 정본은 컴2, D1은 보관용입니다.'


def repo_drop_migrations() -> set[str]:
    found = set()
    for path in (ROOT / 'apps/padiem-chat/migrations').glob('*.sql'):
        if not re.match(r'^(0[89][0-9]|1[0-4][0-9])[a-z]?_', path.name):
            continue
        if re.search(r'DROP\s+TABLE', path.read_text(encoding='utf-8'), re.I):
            found.add(path.name)
    return found


class D1ArchiveOnlyTests(unittest.TestCase):
    def test_every_legacy_and_general_apply_job_fails_before_mutation(self):
        for name, job in APPLY_JOBS.items():
            with self.subTest(workflow=name):
                document = yaml.safe_load((WORKFLOWS / name).read_text(encoding='utf-8'))
                steps = document['jobs'][job]['steps']
                guard = steps[0]
                self.assertIn('Chat D1 apply disabled', guard['name'])
                self.assertIn(MESSAGE, guard['run'])
                self.assertIn('CHAT_D1_ARCHIVE_ONLY=REFUSED', guard['run'])
                self.assertIn('exit 1', guard['run'])

    def test_readonly_jobs_are_kept(self):
        for name, job in (
            ('b62-d1-migrate-gate.yml', 'readonly'),
            ('b62-auth-d1-migration-012-gate.yml', 'cloudflare-readonly'),
            ('b62-d1-migration-081-gate.yml', 'cloudflare-readonly'),
        ):
            with self.subTest(workflow=name):
                document = yaml.safe_load((WORKFLOWS / name).read_text(encoding='utf-8'))
                self.assertIn(job, document['jobs'])
                self.assertNotIn(
                    'CHAT_D1_ARCHIVE_ONLY=REFUSED',
                    str(document['jobs'][job].get('steps', '')),
                )

    def test_table_drop_set_matches_repo_and_refuse_rejects_even_when_allowed(self):
        self.assertEqual(gate.ARCHIVE_ONLY_DROP_MIGRATIONS, repo_drop_migrations())
        name = sorted(gate.ARCHIVE_ONLY_DROP_MIGRATIONS)[0]
        plan = {
            'drift': [],
            'refused_drop_guard': [],
            'apply': [name],
            'window': [name],
        }
        with self.assertRaisesRegex(gate.GateError, 'B62_D1_ARCHIVE_ONLY_DROP_REFUSED'):
            gate.refuse(plan)

    def test_com2_ledger_check_is_surfaced_not_reimplemented(self):
        text = (WORKFLOWS / 'b62-d1-migrate-gate.yml').read_text(encoding='utf-8')
        self.assertIn('Surface the COM2 migration ledger check in the gate summary', text)
        self.assertIn('COM2_LEDGER_CHECK_OWNER=deploy_from_main.sh', text)
        self.assertIn('PENDING_MIGRATIONS', text)
        self.assertIn('COM2_DEPLOY_CHAT_MIGRATION_APPLIED', text)
        script = (ROOT / 'deploy/host-com2/deploy_from_main.sh').read_text(encoding='utf-8')
        self.assertIn('pending_migrations()', script)
        self.assertIn('padiem_local_migration_ledger', script)

    def test_canonical_move_is_recorded_in_operations_doc(self):
        text = (ROOT / 'docs/operations/CHAT_PADIEM_NET_REQUEST_TOPOLOGY_20261108.md').read_text(encoding='utf-8')
        self.assertIn('D1은 2026-11-08부터 보관용이며', text)
        self.assertIn('컴2 배포 경로', text)


if __name__ == '__main__':
    unittest.main()
