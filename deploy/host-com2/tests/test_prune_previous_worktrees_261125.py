"""Rollback-history pruning stays bounded and never removes the live rollback."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "prune_previous_worktrees.py"
SPEC = importlib.util.spec_from_file_location("prune_previous_worktrees", SCRIPT)
prune_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prune_mod)


class PrunePreviousWorktrees(unittest.TestCase):
    def test_keeps_ten_and_always_keeps_the_protected_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            protected = "a" * 40
            for name in [protected] + [f"old-{i:02d}" for i in range(12)]:
                path = root / name
                path.mkdir()
                (path / "apps").mkdir()
            removed = prune_mod.prune(root, protected, 10)
            self.assertEqual(removed, 3)
            self.assertTrue((root / protected / "apps").is_dir())
            self.assertEqual(len([p for p in root.iterdir() if p.is_dir()]), 10)

    def test_without_a_protected_release_it_keeps_the_newest_ten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(12):
                path = root / f"old-{i:02d}"
                path.mkdir()
                import os
                os.utime(path, (1_700_000_000 + i, 1_700_000_000 + i))
            removed = prune_mod.prune(root, "", 10)
            self.assertEqual(removed, 2)
            self.assertEqual(len(list(root.iterdir())), 10)
            self.assertTrue((root / "old-11").is_dir())

    def test_prune_never_touches_paths_outside_the_previous_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "previous"
            root.mkdir()
            outside = Path(tmp) / "keep-me"
            outside.mkdir()
            prune_mod.prune(root, "", 1)
            self.assertTrue(outside.is_dir())


if __name__ == "__main__":
    unittest.main()
