import importlib.util,sqlite3,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('snapshot',Path(__file__).parents[1]/'chat_freeze_snapshot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
 def test_same_count_same_timestamp_but_content_change_is_detected(self):
  with tempfile.TemporaryDirectory() as temp:
   a,b=Path(temp)/'one',Path(temp)/'two'
   for path in (a,b):
    with sqlite3.connect(path) as db:db.executescript("CREATE TABLE item(id TEXT PRIMARY KEY,updated_at TEXT,value TEXT); INSERT INTO item VALUES('a','t','x'); CREATE TABLE no_clock(id TEXT PRIMARY KEY);")
   self.assertEqual(m.compare(a,b)['changed'],[])
   with sqlite3.connect(b) as db:db.execute("UPDATE item SET value='y'")
   self.assertEqual(m.compare(a,b)['changed'],['item'])
 def test_missing_table_is_detected(self):
  with tempfile.TemporaryDirectory() as temp:
   a,b=Path(temp)/'one',Path(temp)/'two'
   with sqlite3.connect(a) as db:db.execute('CREATE TABLE item(id TEXT PRIMARY KEY)')
   with sqlite3.connect(b):pass
   self.assertEqual(m.compare(a,b)['changed'],['item'])
