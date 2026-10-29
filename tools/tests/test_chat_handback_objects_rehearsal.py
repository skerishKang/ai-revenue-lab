import importlib.util,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('objects',Path(__file__).parents[1]/'chat_handback_objects_rehearsal.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class TestObjects(unittest.TestCase):
 def test_added_changed_deleted_and_exact_copy(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);base=p/'base';cur=p/'cur';base.mkdir();cur.mkdir()
   (base/'old').write_bytes(b'old');(base/'samekey').write_bytes(b'one');(cur/'samekey').write_bytes(b'two');(cur/'new').write_bytes(b'new')
   self.assertEqual(m.plan(base,cur),{'added':1,'deleted':1,'changed':1})
   self.assertEqual(m.stage(cur,p/'target')['objects'],2);self.assertEqual(m.manifest(cur),m.manifest(p/'target'))
   with self.assertRaises(m.Refused):m.stage(cur,p/'target')
 def test_symlinks_are_refused(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'outside').write_bytes(b'x');(p/'root').mkdir();(p/'root'/'link').symlink_to(p/'outside')
   with self.assertRaises(m.Refused):m.manifest(p/'root')
