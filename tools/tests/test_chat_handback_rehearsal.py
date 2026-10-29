import importlib.util,sqlite3,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('handback',Path(__file__).parents[1]/'chat_handback_rehearsal.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
class Tests(unittest.TestCase):
 def setupdb(self,p):
  with sqlite3.connect(p) as c:c.executescript("CREATE TABLE item(id TEXT PRIMARY KEY,val TEXT); INSERT INTO item VALUES('a','old'),('b','gone');")
 def test_mixed_changes_and_stale_baseline(self):
  with tempfile.TemporaryDirectory() as d:
   a,b,c=[Path(d)/n for n in ('base','current','d1')]
   for p in (a,b,c):self.setupdb(p)
   with sqlite3.connect(b) as db:db.executescript("UPDATE item SET val='new' WHERE id='a'; DELETE FROM item WHERE id='b'; INSERT INTO item VALUES('c','added');")
   self.assertEqual(h.plan(a,b,c)['item'],{'insert':1,'update':1,'delete':1})
   h.apply_local(a,b,c)
   with sqlite3.connect(b) as x,sqlite3.connect(c) as y:self.assertEqual(x.execute('select * from item order by id').fetchall(),y.execute('select * from item order by id').fetchall())
   before=c.read_bytes()
   with self.assertRaisesRegex(h.Refused,'d1_baseline_drift'):h.apply_local(a,b,c)
   self.assertEqual(before,c.read_bytes())
 def test_trigger_mismatch_rejects_before_writes(self):
  with tempfile.TemporaryDirectory() as d:
   a,b,c=[Path(d)/n for n in ('base','current','d1')]
   for p in (a,b,c):self.setupdb(p)
   with sqlite3.connect(c) as db:db.execute('CREATE TRIGGER t AFTER INSERT ON item BEGIN SELECT 1; END')
   with self.assertRaisesRegex(h.Refused,'trigger_mismatch'):h.plan(a,b,c)
 def test_apply_failure_rolls_back_prior_changes(self):
  with tempfile.TemporaryDirectory() as d:
   a,b,c=[Path(d)/n for n in ('base','current','d1')]
   for p in (a,b,c):
    with sqlite3.connect(p) as db:db.executescript("CREATE TABLE item(id TEXT PRIMARY KEY,val TEXT UNIQUE); INSERT INTO item VALUES('a','one'),('b','two');")
   with sqlite3.connect(b) as db:db.executescript("UPDATE item SET val='temp' WHERE id='a'; UPDATE item SET val='one' WHERE id='b'; UPDATE item SET val='two' WHERE id='a';")
   with self.assertRaises(sqlite3.IntegrityError):h.apply_local(a,b,c)
   with sqlite3.connect(a) as x,sqlite3.connect(c) as y:self.assertEqual(x.execute('select * from item order by id').fetchall(),y.execute('select * from item order by id').fetchall())
