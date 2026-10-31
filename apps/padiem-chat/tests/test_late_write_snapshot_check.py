import importlib.util
import sqlite3
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'late_write_snapshot_check.py'
spec = importlib.util.spec_from_file_location('late_write_snapshot_check', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_db(path, value):
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE records (id INTEGER PRIMARY KEY, payload TEXT)')
    conn.execute('INSERT INTO records VALUES (?, ?)', (1, value))
    conn.commit()
    conn.close()


def test_same_rows_match(tmp_path):
    a, b = tmp_path / 'a.db', tmp_path / 'b.db'
    make_db(a, 'same')
    make_db(b, 'same')
    assert module.snapshot(a) == module.snapshot(b)


def test_equal_row_count_changed_content_is_detected(tmp_path):
    a, b = tmp_path / 'a.db', tmp_path / 'b.db'
    make_db(a, 'before')
    make_db(b, 'late write')
    left, right = module.snapshot(a), module.snapshot(b)
    assert left['tables']['records']['rows'] == right['tables']['records']['rows'] == 1
    assert left['tables']['records']['sha256'] != right['tables']['records']['sha256']
