"""Create an isolated SQLite rehearsal; never targets an existing database."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import sqlite3
import time
from pathlib import Path
import chat_d1_migration as migration
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('migration_bootstrap', ROOT / 'apps/padiem-chat/app/migration_bootstrap.py')
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)

def _digest(db, table, cols):
    quoted=lambda x:'"'+x.replace('"','""')+'"'
    rows=db.execute('SELECT '+','.join(map(quoted,cols))+' FROM '+quoted(table))
    return sorted(hashlib.sha256(repr(tuple(row)).encode('utf-8')).digest() for row in rows)

def run(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or target.exists(): raise ValueError('target_must_be_new')
    started = time.monotonic(); source_db = sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    try:
        if source_db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('source_integrity_failure')
        # Exclusive creation ensures the tool never overwrites a preexisting DB.
        with target.open('xb'): pass
        with sqlite3.connect(target) as dest:
            for typ,name,sql in source_db.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','index') AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END,name"):
                dest.execute(sql)
        schema_s=time.monotonic()-started
        t=time.monotonic(); result=migration.load_state(str(source),str(target)); load_s=time.monotonic()-t
        t=time.monotonic(); verified=migration.verify_state(str(target),source_path=str(source))
        if any(x!='OK' for x in verified['tables'].values()): raise ValueError('pre_migration_verify_failed')
        pre_s=time.monotonic()-t
        t=time.monotonic(); dest=sqlite3.connect(target,isolation_level=None)
        try:
            # The original D1 ledger is explicitly copied to this new target.
            rows=source_db.execute('SELECT * FROM d1_migrations').fetchall()
            columns=migration._columns(source_db,'d1_migrations')
            if columns!=migration._columns(dest,'d1_migrations'): raise ValueError('ledger_schema_mismatch')
            dest.executemany('INSERT INTO d1_migrations VALUES ('+','.join('?' for _ in columns)+')',rows)
            applied=bootstrap.apply_checked_migrations(dest,ROOT/'apps/padiem-chat/migrations')
            migration_s=time.monotonic()-t; t=time.monotonic()
            names=[n for n in migration._tables(source_db) if n not in migration.SKIP_TABLES]
            mismatches=[]
            for name in names:
                cols=migration._columns(source_db,name)
                if not set(cols).issubset(set(migration._columns(dest,name))) or _digest(source_db,name,cols)!=_digest(dest,name,cols): mismatches.append(name)
            triggers=lambda db:list(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"))
            if mismatches or triggers(source_db)!=triggers(dest): raise ValueError('independent_verification_failed')
            return {'tables':result['tables'],'rows':result['rows'],'applied':applied,'schema_seconds':schema_s,'load_seconds':load_s,'pre_verify_seconds':pre_s,'migration_seconds':migration_s,'independent_seconds':time.monotonic()-t,'total_seconds':time.monotonic()-started}
        finally: dest.close()
    finally: source_db.close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--new-target',required=True);a=p.parse_args()
    try: print('REHEARSAL_PASS',run(a.source,a.new_target));return 0
    except Exception as exc: print('REHEARSAL_FAIL',type(exc).__name__,str(exc));return 1
if __name__=='__main__':raise SystemExit(main())
