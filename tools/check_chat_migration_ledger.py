#!/usr/bin/env python3
"""Compare an offline SQLite migration ledger with this checkout's migrations."""
import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def check(db_path, migrations, ledger):
    expected = {p.name for p in Path(migrations).glob('[0-9][0-9][0-9]_*.sql')}
    if not expected or ledger not in ('d1_migrations', 'padiem_local_migration_ledger'):
        raise ValueError('invalid migration directory or ledger')
    with sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        actual = {r[0] for r in db.execute(f'SELECT name FROM {ledger}')}
    return sorted(expected - actual), sorted(actual - expected)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', required=True)
    p.add_argument('--migrations', default=ROOT / 'apps/padiem-chat/migrations')
    p.add_argument('--ledger', choices=('d1_migrations', 'padiem_local_migration_ledger'), default='d1_migrations')
    a = p.parse_args()
    try:
        missing, extra = check(a.db, a.migrations, a.ledger)
    except (sqlite3.Error, OSError, ValueError) as exc:
        print('MIGRATION_LEDGER=ERROR', type(exc).__name__)
        return 2
    print('MIGRATION_LEDGER=' + ('MISMATCH' if missing or extra else 'PASS'))
    print('MISSING=' + ','.join(missing))
    print('EXTRA=' + ','.join(extra))
    return int(bool(missing or extra))

if __name__ == '__main__':
    raise SystemExit(main())
