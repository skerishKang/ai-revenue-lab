"""The COM2-side PC adopt tool: dry-run writes nothing, apply writes one link.

The tool never prints the account id, mesh node id or tag. These tests use fake
stores and fake values only.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))

import adopt_pc_link as tool  # noqa: E402

NODE = "node/meshdomain/pc2-test"
LABEL = "K_lipvoice · 컴2"
QA_EMAIL = "qa@example.test"
QA_ACCOUNT_ID = "usr_" + "q" * 32
OWNER_ID = "usr_" + "o" * 32


class FakeStmt:
    def __init__(self, db, sql):
        self.db = db
        self.sql = sql
        self.values = ()

    def bind(self, *values):
        self.values = values
        return self

    async def all(self):
        if "DISTINCT mesh_node_id" in self.sql:
            label = self.values[0]
            return [{"mesh_node_id": node}
                    for node, name in self.db.labels.items() if name == label]
        return []

    async def first(self):
        if "COUNT(DISTINCT user_id)" in self.sql:
            node = self.values[0]
            return {"n": len(self.db.accounts.get(node, set()))}
        return None


class FakeDB:
    def __init__(self, labels, accounts):
        self.labels = dict(labels)
        self.accounts = {node: set(ids) for node, ids in accounts.items()}

    def prepare(self, sql):
        return FakeStmt(self, sql)


class FakeStore:
    def __init__(self, *, labels=None, accounts=None, existing=None):
        self.db = FakeDB(labels or {}, accounts or {})
        self.existing = existing
        self.adopted = []
        self.link_reads = []
        self.resolve_targets = []

    async def resolve_account_ref(self, *, target):
        self.resolve_targets.append(target)
        return QA_ACCOUNT_ID if target == QA_EMAIL else None

    async def link_for(self, *, user_id, mesh_node_id):
        self.link_reads.append((user_id, mesh_node_id))
        if (self.existing
                and self.existing["user_id"] == user_id
                and self.existing["mesh_node_id"] == mesh_node_id):
            return self.existing
        return None

    async def drive_roots_for_node(self, *, mesh_node_id):
        return ["C:"]

    # The store methods the tool uses on both the D1 and the queue-backed store.
    async def list_active_device_ids(self):
        return sorted(node for node, ids in self.db.accounts.items() if ids)

    async def device_scope(self, *, device_id):
        refs = sorted(self.db.accounts.get(device_id, set()))
        return {"device_id": device_id, "account_refs": refs} if refs else None

    async def links_for_owner(self, *, user_id):
        return [
            {"mesh_node_id": node, "label": self.db.labels.get(node), "user_id": user_id}
            for node, ids in self.db.accounts.items() if user_id in ids
        ]

    async def adopt_link(self, **kwargs):
        self.adopted.append(kwargs)
        node = kwargs["mesh_node_id"]
        self.db.accounts.setdefault(node, set()).add(kwargs["user_id"])
        self.existing = {
            "link_id": "pclink_new",
            "user_id": kwargs["user_id"],
            "mesh_node_id": node,
            "label": LABEL,
            "state": "active",
            "roots": [],
        }
        return self.existing


class FakePresence:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = 0

    async def load(self, *, device_id):
        self.calls += 1
        if not self.ok:
            return None
        return {"device_id": device_id, "connected": 1, "source": "mesh"}


def _run(store, presence, *, apply=False):
    return asyncio.run(tool.run_adopt(
        store, presence, pc_label=LABEL, target_username=QA_EMAIL, apply=apply,
    ))


class PcTokenToolTest(unittest.TestCase):
    def test_dry_run_writes_nothing(self):
        store = FakeStore(labels={NODE: LABEL}, accounts={NODE: {OWNER_ID}})
        result = _run(store, FakePresence(True), apply=False)
        lines = result["lines"]
        self.assertIn("PC_FOUND=yes", lines)
        self.assertIn("PRESENCE=ok", lines)
        self.assertIn("TARGET_ACCOUNT=found", lines)
        self.assertIn("EXISTING_LINK=no", lines)
        self.assertIn("OTHER_ACCOUNTS_KEPT=1", lines)
        self.assertNotIn("ALREADY_LINKED", lines)
        self.assertEqual(store.adopted, [])
        self.assertIsNone(result["error"])

    def test_apply_adopts_once_and_keeps_other_accounts(self):
        store = FakeStore(labels={NODE: LABEL}, accounts={NODE: {OWNER_ID}})
        result = _run(store, FakePresence(True), apply=True)
        lines = result["lines"]
        self.assertIn("ADOPTED=1", lines)
        self.assertIn("OTHER_ACCOUNTS_KEPT=1", lines)
        self.assertEqual(len(store.adopted), 1)
        self.assertEqual(store.adopted[0]["user_id"], QA_ACCOUNT_ID)
        self.assertEqual(store.adopted[0]["mesh_node_id"], NODE)
        self.assertEqual(store.db.accounts[NODE], {OWNER_ID, QA_ACCOUNT_ID})

    def test_already_linked_is_a_noop(self):
        existing = {"user_id": QA_ACCOUNT_ID, "mesh_node_id": NODE,
                    "label": LABEL, "state": "active", "roots": []}
        store = FakeStore(labels={NODE: LABEL},
                          accounts={NODE: {OWNER_ID, QA_ACCOUNT_ID}},
                          existing=existing)
        result = _run(store, FakePresence(True), apply=True)
        lines = result["lines"]
        self.assertIn("EXISTING_LINK=yes", lines)
        self.assertIn("ALREADY_LINKED", lines)
        self.assertNotIn("ADOPTED=1", lines)
        self.assertEqual(store.adopted, [])

    def test_output_has_no_identifiers(self):
        store = FakeStore(labels={NODE: LABEL}, accounts={NODE: {OWNER_ID}})
        result = _run(store, FakePresence(True), apply=True)
        text = "\n".join(result["lines"])
        self.assertNotIn(QA_EMAIL, text)
        self.assertNotIn(QA_ACCOUNT_ID, text)
        self.assertNotIn(NODE, text)
        self.assertNotIn(LABEL, text)

    def test_pc_not_found_stops(self):
        store = FakeStore()
        result = _run(store, FakePresence(True), apply=False)
        self.assertEqual(result["lines"], ["PC_FOUND=no"])
        self.assertEqual(result["error"], "PC_NOT_FOUND")

    def test_presence_none_stops(self):
        store = FakeStore(labels={NODE: LABEL}, accounts={NODE: {OWNER_ID}})
        result = _run(store, FakePresence(False), apply=False)
        self.assertIn("PC_FOUND=yes", result["lines"])
        self.assertIn("PRESENCE=none", result["lines"])
        self.assertEqual(result["error"], "PC_NOT_PRESENT")

    def test_two_runs_create_one_link(self):
        store = FakeStore(labels={NODE: LABEL}, accounts={NODE: {OWNER_ID}})
        first = _run(store, FakePresence(True), apply=True)
        second = _run(store, FakePresence(True), apply=True)
        self.assertIn("ADOPTED=1", first["lines"])
        self.assertIn("ALREADY_LINKED", second["lines"])
        self.assertEqual(len(store.adopted), 1)

    def test_env_metadata_checks(self):
        with self.assertRaises(tool.ToolError) as mode:
            tool._assert_env_metadata(0o644, 0, 10)
        self.assertEqual(mode.exception.code, "QA_ENV_MODE_NOT_600")
        with self.assertRaises(tool.ToolError) as owner:
            tool._assert_env_metadata(0o600, 1000, 10)
        self.assertEqual(owner.exception.code, "QA_ENV_OWNER_NOT_ROOT")
        with self.assertRaises(tool.ToolError) as size:
            tool._assert_env_metadata(0o600, 0, 0)
        self.assertEqual(size.exception.code, "QA_ENV_EMPTY")
        tool._assert_env_metadata(0o600, 0, 10)

    def test_chat_env_loader_reads_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.env"
            path.write_text("FOO='bar'\n# comment\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                tool._load_env_file(path)
            self.assertEqual(os.environ.get("FOO"), "bar")
            self.assertEqual(out.getvalue(), "")
            os.environ.pop("FOO", None)
            with self.assertRaises(tool.ToolError) as ctx:
                tool._load_env_file(Path(tmp) / "missing")
            self.assertEqual(ctx.exception.code, "CHAT_ENV_MISSING")

    def test_root_required(self):
        saved = getattr(tool.os, "geteuid", None)
        tool.os.geteuid = lambda: 1000
        try:
            with self.assertRaises(tool.ToolError) as ctx:
                tool._assert_root()
            self.assertEqual(ctx.exception.code, "ROOT_REQUIRED")
        finally:
            if saved is None:
                del tool.os.geteuid
            else:
                tool.os.geteuid = saved


if __name__ == "__main__":
    unittest.main()

def test_deployed_tree_is_used_only_when_present(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "adopt_tool_for_tree", TOOL_PATH if "TOOL_PATH" in globals() else
        __import__("pathlib").Path(__file__).resolve().parents[1] / "tools" / "adopt_pc_link.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    import os, sys
    cwd = os.getcwd()
    saved = list(sys.path)
    # _use_deployed_tree drops the imported ``app`` modules on purpose (the tool
    # must re-import from the deployed tree). In the test process that would
    # leave later tests holding classes from a second import, so restore the
    # exact module objects afterwards.
    saved_modules = {name: mod for name, mod in sys.modules.items()
                     if name == "app" or name.startswith("app.")}
    try:
        assert tool._use_deployed_tree(tmp_path) is False
        (tmp_path / "app").mkdir()
        assert tool._use_deployed_tree(tmp_path) is True
        assert sys.path[0] == str(tmp_path)
        assert os.getcwd() == str(tmp_path)
    finally:
        os.chdir(cwd)
        sys.path[:] = saved
        for name in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
            del sys.modules[name]
        sys.modules.update(saved_modules)


def test_root_is_dropped_before_the_database_opens():
    source = (__import__("pathlib").Path(__file__).resolve().parents[1]
              / "tools" / "adopt_pc_link.py").read_text(encoding="utf-8")
    main = source[source.index("def main("):]
    assert main.index("_become_service_user()") < main.index("_load_state()")
    assert main.index("_read_qa_username(") < main.index("_become_service_user()")


def test_state_is_found_through_wrapping_middleware(monkeypatch):
    import importlib.util, sys, types
    spec = importlib.util.spec_from_file_location(
        "adopt_tool_for_wrap",
        __import__("pathlib").Path(__file__).resolve().parents[1] / "tools" / "adopt_pc_link.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    class Inner:
        pass

    inner = Inner()
    inner.state = types.SimpleNamespace(pc_device_pairing_store="S", mesh_device_presence_store="P")

    class Freeze:
        def __init__(self, app):
            self._app = app

    fake = types.ModuleType("app.local_cpython")
    fake.build_app = lambda: Freeze(Freeze(inner))
    monkeypatch.setitem(sys.modules, "app.local_cpython", fake)
    assert tool._load_state() == ("S", "P")


def test_tool_reads_the_directory_only_through_store_methods():
    # Production serves the pairing store through the queue (no local DB), so the
    # tool must not issue raw SQL; every read is a method the queue also serves.
    source = (Path(__file__).resolve().parents[1] / "tools" / "adopt_pc_link.py").read_text(encoding="utf-8")
    assert "prepare(" not in source
    assert ".db" not in source
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.queue_store_proxy import QUEUE_PAIRING_METHODS
    for name in ("list_active_device_ids", "device_scope", "links_for_owner",
                 "resolve_account_ref", "link_for", "drive_roots_for_node", "adopt_link"):
        assert name in QUEUE_PAIRING_METHODS
