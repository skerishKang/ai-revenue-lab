import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('chat_ledger', Path(__file__).parents[1] / 'check_chat_migration_ledger.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class LedgerTest(unittest.TestCase):
    def test_missing_and_extra_are_reported_and_database_is_not_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '076_a.sql').touch()
            (root / '078_b.sql').touch()
            db = root / 'db.sqlite'
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE d1_migrations(name TEXT)')
                conn.executemany('INSERT INTO d1_migrations VALUES (?)', [('076_a.sql',), ('079_extra.sql',)])
            before = db.read_bytes()
            self.assertEqual(mod.check(db, root, 'd1_migrations'), (['078_b.sql'], ['079_extra.sql']))
            self.assertEqual(before, db.read_bytes())
    def test_absent_db_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '078_b.sql').touch()
            with self.assertRaises(sqlite3.OperationalError):
                mod.check(root / 'missing.sqlite', root, 'd1_migrations')
            self.assertFalse((root / 'missing.sqlite').exists())
