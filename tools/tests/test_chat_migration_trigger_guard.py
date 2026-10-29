import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('chat_migration', Path(__file__).parents[1] / 'chat_d1_migration.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

class TriggerGuardTest(unittest.TestCase):
    def test_trigger_drift_rolls_back_everything(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp) / 'source', Path(temp) / 'target'
            for path in (source, target):
                with sqlite3.connect(path) as db:
                    db.executescript('CREATE TABLE a_outbox(id TEXT PRIMARY KEY); CREATE TABLE z_users(id TEXT PRIMARY KEY); CREATE TRIGGER signup AFTER INSERT ON z_users BEGIN INSERT INTO a_outbox VALUES (new.id); END;')
            with sqlite3.connect(source) as db:
                db.execute("INSERT INTO z_users VALUES ('user')")
                db.execute('DELETE FROM a_outbox')
            with self.assertRaisesRegex(tool.MigrationRefused, 'final_content_mismatch:a_outbox'):
                tool.load_state(str(source), str(target))
            with sqlite3.connect(target) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM z_users').fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='chat_migration_runs'").fetchone()[0], 0)
