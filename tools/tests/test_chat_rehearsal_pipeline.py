import importlib.util,sqlite3,sys,tempfile,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'tools'))
spec=importlib.util.spec_from_file_location('pipeline',root/'tools/chat_rehearsal_pipeline.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class PipelineTests(unittest.TestCase):
 def test_pipeline_keeps_rows_and_applies_only_pending(self):
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp);directory=base/'apps/padiem-chat/migrations';directory.mkdir(parents=True)
   (directory/'001_first.sql').write_text('CREATE TABLE item(id TEXT PRIMARY KEY, value TEXT); CREATE TRIGGER t AFTER INSERT ON item BEGIN SELECT 1; END;')
   (directory/'002_next.sql').write_text('ALTER TABLE item ADD COLUMN extra TEXT;')
   source=base/'source.sqlite';target=base/'target.sqlite'
   with sqlite3.connect(source) as db:
    db.executescript((directory/'001_first.sql').read_text());db.execute('CREATE TABLE d1_migrations(id INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)');db.execute("INSERT INTO d1_migrations VALUES(1,'001_first.sql','t')");db.execute("INSERT INTO item VALUES('a','b')")
   old=p.ROOT;p.ROOT=base
   try:r=p.run(source,target)
   finally:p.ROOT=old
   self.assertEqual((r['tables'],r['rows'],r['applied']),(1,1,1))
   with sqlite3.connect(target) as db:self.assertEqual(db.execute('select count(*) from padiem_local_migration_ledger').fetchone()[0],2)
   with self.assertRaisesRegex(ValueError,'target_must_be_new'):p.run(source,target)
