import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('bootstrap',Path(__file__).parents[2]/'apps/padiem-chat/app/migration_bootstrap.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
 def test_adopt_and_only_apply_missing(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'001_first.sql').write_text('CREATE TABLE x(id INTEGER PRIMARY KEY);');(p/'002_next.sql').write_text('ALTER TABLE x ADD COLUMN value TEXT;')
   c=sqlite3.connect(':memory:');c.executescript('CREATE TABLE x(id INTEGER PRIMARY KEY); CREATE TABLE d1_migrations(name TEXT); INSERT INTO d1_migrations VALUES (\'001_first.sql\');')
   self.assertEqual(m.apply_checked_migrations(c,p),1);self.assertEqual(m.apply_checked_migrations(c,p),0)
   self.assertEqual(c.execute('SELECT count(*) FROM padiem_local_migration_ledger').fetchone()[0],2)
 def test_bad_schema_or_missing_ledger_refuses_before_writes(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'001_first.sql').write_text('CREATE TABLE x(id INTEGER PRIMARY KEY);')
   c=sqlite3.connect(':memory:');c.executescript('CREATE TABLE x(id TEXT); CREATE TABLE d1_migrations(name TEXT); INSERT INTO d1_migrations VALUES (\'001_first.sql\');')
   with self.assertRaisesRegex(ValueError,'schema_ledger_mismatch'): m.apply_checked_migrations(c,p)
   self.assertEqual(c.execute("SELECT count(*) FROM sqlite_master WHERE name='padiem_local_migration_ledger'").fetchone()[0],0)
   c=sqlite3.connect(':memory:');c.execute('CREATE TABLE x(id INTEGER)')
   with self.assertRaisesRegex(ValueError,'ledger_missing'):m.apply_checked_migrations(c,p)
 def test_pending_error_rolls_back_all(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'001_first.sql').write_text('CREATE TABLE x(id INTEGER PRIMARY KEY);');(p/'002_fail.sql').write_text('ALTER TABLE x ADD COLUMN a TEXT; ALTER TABLE absent ADD COLUMN b TEXT;')
   c=sqlite3.connect(':memory:');c.executescript('CREATE TABLE x(id INTEGER PRIMARY KEY); CREATE TABLE d1_migrations(name TEXT); INSERT INTO d1_migrations VALUES (\'001_first.sql\');')
   with self.assertRaises(sqlite3.OperationalError):m.apply_checked_migrations(c,p)
   self.assertEqual(len(c.execute('PRAGMA table_info(x)').fetchall()),1)
   self.assertEqual(c.execute("SELECT count(*) FROM sqlite_master WHERE name='padiem_local_migration_ledger'").fetchone()[0],0)
