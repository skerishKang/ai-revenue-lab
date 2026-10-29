"""Compare two read-only SQLite exports after all writers have been quiesced.

Matching snapshots do not prove delayed work has stopped. No live D1 access.
"""
import hashlib
import sqlite3
from pathlib import Path

def _ident(name): return '"'+name.replace('"','""')+'"'

def capture(path):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('BEGIN')
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        summary={}
        for name in names:
            cols=[r[1] for r in db.execute('PRAGMA table_info('+_ident(name)+')')]
            rows=db.execute('SELECT * FROM '+_ident(name)).fetchall()
            hashes=sorted(hashlib.sha256(repr(row).encode('utf-8')).digest() for row in rows)
            latest=db.execute('SELECT MAX(updated_at) FROM '+_ident(name)).fetchone()[0] if 'updated_at' in cols else None
            summary[name]={'count':len(rows),'updated_at_max':latest,'sha256':hashlib.sha256(b''.join(hashes)).hexdigest(),'columns':cols}
        db.rollback()
        return summary
    finally:db.close()

def compare(first,second):
    a,b=capture(first),capture(second)
    return {'tables':len(a),'changed':sorted(name for name in a.keys()|b.keys() if a.get(name)!=b.get(name))}
