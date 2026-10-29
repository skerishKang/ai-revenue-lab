"""Offline SQLite-only handback rehearsal. This tool cannot access Cloudflare/D1."""
import sqlite3
import hashlib
from pathlib import Path

class Refused(RuntimeError): pass

def _open(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)

def _tables(db):
    return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]

def _quote(name): return '"' + name.replace('"','""') + '"'

def _snapshot(db, table):
    info=db.execute('PRAGMA table_info('+_quote(table)+')').fetchall()
    columns=[r[1] for r in info]; keys=[r[1] for r in sorted((r for r in info if r[5]),key=lambda r:r[5])]
    if not keys: raise Refused('primary_key_required:'+table)
    indices=[columns.index(k) for k in keys]; rows={}
    for row in db.execute('SELECT * FROM '+_quote(table)):
        key=tuple(row[i] for i in indices)
        if any(x is None for x in key) or key in rows: raise Refused('invalid_primary_key:'+table)
        rows[key]=tuple(row)
    return columns,keys,rows

def _digest(rows):
    parts=sorted(hashlib.sha256(repr(row).encode("utf-8")).digest() for row in rows.values())
    return hashlib.sha256(b"".join(parts)).hexdigest()

def _schema(db):
    return list(db.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','index','trigger','view') AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type,name"))

def _triggers(db):
    return list(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"))

def plan(base_path, current_path, d1_path, excluded=()):
    if len({Path(p).resolve() for p in (base_path,current_path,d1_path)})!=3: raise Refused('paths_must_differ')
    with _open(base_path) as base, _open(current_path) as current, _open(d1_path) as d1:
        names=[n for n in _tables(base) if n not in excluded]
        if set(names)!=(set(_tables(current))-set(excluded)) or set(names)!=(set(_tables(d1))-set(excluded)):
            raise Refused('table_mismatch')
        if _triggers(base)!=_triggers(current) or _triggers(base)!=_triggers(d1): raise Refused('trigger_mismatch')
        if _schema(base)!=_schema(current) or _schema(base)!=_schema(d1): raise Refused('schema_mismatch')
        reports={}
        for name in names:
            cols,keys,old=_snapshot(base,name); ccols,ckeys,new=_snapshot(current,name); dcols,dkeys,live=_snapshot(d1,name)
            if (cols,keys)!=(ccols,ckeys) or (cols,keys)!=(dcols,dkeys): raise Refused('schema_mismatch:'+name)
            if _digest(old)!=_digest(live) or old!=live: raise Refused('d1_baseline_drift:'+name)
            reports[name]={'insert':len(new.keys()-old.keys()),'delete':len(old.keys()-new.keys()),'update':sum(old[k]!=new[k] for k in old.keys()&new.keys())}
        return reports

def apply_local(base_path,current_path,d1_path,excluded=()):
    # Demo only: filesystem SQLite. Online D1 atomic apply is NOT implemented.
    plan(base_path,current_path,d1_path,excluded)
    with _open(base_path) as base, _open(current_path) as current:
        target=sqlite3.connect(d1_path,isolation_level=None)
        try:
            target.execute('BEGIN IMMEDIATE')
            names=[n for n in _tables(base) if n not in excluded]
            triggers=_triggers(target)
            if triggers!=_triggers(base) or triggers!=_triggers(current): raise Refused('trigger_mismatch')
            if _schema(target)!=_schema(base) or _schema(target)!=_schema(current): raise Refused('schema_mismatch')
            for name in names:
                if _snapshot(base,name)!=_snapshot(target,name):raise Refused('d1_baseline_drift:'+name)
            for name,sql in triggers:target.execute('DROP TRIGGER '+_quote(name))
            for name in names:
                cols,keys,old=_snapshot(base,name); _,_,new=_snapshot(current,name)
                where=' AND '.join(_quote(k)+'=?' for k in keys)
                for key in old.keys()-new.keys():target.execute('DELETE FROM '+_quote(name)+' WHERE '+where,key)
                for key in old.keys()&new.keys():
                    if old[key]!=new[key]: target.execute('UPDATE '+_quote(name)+' SET '+','.join(_quote(c)+'=?' for c in cols)+' WHERE '+where,new[key]+key)
                for key in new.keys()-old.keys():target.execute('INSERT INTO '+_quote(name)+' ('+','.join(map(_quote,cols))+') VALUES ('+','.join('?' for _ in cols)+')',new[key])
            for name,sql in triggers: target.execute(sql)
            for name in names:
                if _digest(_snapshot(current,name)[2])!=_digest(_snapshot(target,name)[2]) or _snapshot(current,name)!=_snapshot(target,name):raise Refused('post_apply_mismatch:'+name)
            if _triggers(target)!=_triggers(current):raise Refused('trigger_mismatch')
            target.execute('COMMIT')
        except BaseException:
            if target.in_transaction:target.execute('ROLLBACK')
            raise
        finally:target.close()
