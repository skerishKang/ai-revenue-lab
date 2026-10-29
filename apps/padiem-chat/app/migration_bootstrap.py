"""Adopt a D1 migration ledger only after checking its schema against source."""
import re
import sqlite3
from datetime import datetime, timezone

LOCAL = 'padiem_local_migration_ledger'


def _normal(sql):
    # Remove SQL comments without changing quoted literals or identifiers.
    parts = re.findall(r"'(?:(?:'')|[^'])*'|\"(?:(?:\"\")|[^\"])*\"|--[^\n]*|/\*[\s\S]*?\*/|\s+|[^\s'\"-]+|-", sql)
    out = []
    for part in parts:
        if part.isspace() or part.startswith('--') or part.startswith('/*'):
            if out and out[-1] != ' ': out.append(' ')
        else: out.append(part)
    return ''.join(out).strip()


def _schema(db):
    return {(kind,name): _normal(sql) for kind,name,sql in db.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','index','trigger','view') AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")
        if name not in ('d1_migrations', LOCAL, 'chat_copy_snapshot', 'chat_migration_runs', 'chat_migration_summary', 'chat_migration_snapshot')}


def apply_checked_migrations(connection, migrations_dir):
    paths = sorted(migrations_dir.glob('*.sql'))
    if not paths: raise ValueError('migration_files_missing')
    if connection.in_transaction: raise ValueError('migration_connection_has_transaction')
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if LOCAL in tables:
        applied = {r[0] for r in connection.execute(f'SELECT name FROM {LOCAL}')}
    elif 'd1_migrations' in tables:
        applied = {r[0] for r in connection.execute('SELECT name FROM d1_migrations')}
        if not applied: raise ValueError('d1_ledger_empty')
    elif tables:
        raise ValueError('migration_ledger_missing')
    else:
        applied = set()
    if not applied.issubset({p.name for p in paths}): raise ValueError('unknown_migration_in_ledger')
    if applied != {p.name for p in paths[:len(applied)]}: raise ValueError('local_ledger_not_contiguous')
    if applied:
        expected = sqlite3.connect(':memory:')
        try:
            for path in paths[:len(applied)]: expected.executescript(path.read_text(encoding='utf-8'))
            if _schema(connection) != _schema(expected): raise ValueError('d1_schema_ledger_mismatch')
        finally: expected.close()
    pending = [p for p in paths if p.name not in applied]
    ts = datetime.now(timezone.utc).isoformat().replace("'", "''")
    statements = ['BEGIN IMMEDIATE;', f'CREATE TABLE IF NOT EXISTS {LOCAL} (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL);']
    if LOCAL not in tables:
        statements += [f"INSERT INTO {LOCAL} VALUES ('{name.replace(chr(39), chr(39)*2)}', '{ts}');" for name in sorted(applied)]
    for path in pending:
        statements.append(path.read_text(encoding='utf-8'))
        statements.append(f"INSERT INTO {LOCAL} VALUES ('{path.name.replace(chr(39), chr(39)*2)}', '{ts}');")
    statements.append('COMMIT;')
    try: connection.executescript('\n'.join(statements))
    except BaseException:
        if connection.in_transaction: connection.rollback()
        raise
    return len(pending)
