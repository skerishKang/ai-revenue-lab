"""Compare two local SQLite snapshots without exposing row contents.

This is offline evidence only; identical snapshots do not prove that no
transient write was reverted between snapshots or that producers were drained.
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def snapshot(path):
    path = Path(path).resolve(strict=True)
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        conn.execute('BEGIN')
        objects = conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        tables = [r[1] for r in objects if r[0] == 'table']
        result = {}
        for name in tables:
            identifier = '"' + name.replace('"', '""') + '"'
            # Sort individual typed row hashes so row order does not affect the digest.
            row_hashes = []
            for row in conn.execute('SELECT * FROM ' + identifier):
                def encode(value):
                    if isinstance(value, bytes): return ['blob', value.hex()]
                    if value is None: return ['null', None]
                    return [type(value).__name__, value]
                encoded = json.dumps([encode(v) for v in row], ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()
                row_hashes.append(hashlib.sha256(encoded).digest())
            digest = hashlib.sha256(b''.join(sorted(row_hashes))).hexdigest()
            result[name] = {'rows': len(row_hashes), 'sha256': digest}
        schema = hashlib.sha256(json.dumps(objects, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
        return {'schema_sha256': schema, 'tables': result}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first', help='first local SQLite snapshot')
    parser.add_argument('second', help='later local SQLite snapshot')
    args = parser.parse_args()
    if Path(args.first).resolve() == Path(args.second).resolve():
        parser.error('two distinct snapshots required')
    a, b = snapshot(args.first), snapshot(args.second)
    changed = sorted(k for k in set(a['tables']) | set(b['tables']) if a['tables'].get(k) != b['tables'].get(k))
    schema_changed = a['schema_sha256'] != b['schema_sha256']
    print(json.dumps({'snapshot_match': not changed and not schema_changed, 'schema_changed': schema_changed, 'changed_tables': changed, 'table_count': len(a['tables']), 'drain_verified': False, 'transient_writes_excluded': False}))
    return 1 if changed or schema_changed else 0


if __name__ == '__main__':
    raise SystemExit(main())
