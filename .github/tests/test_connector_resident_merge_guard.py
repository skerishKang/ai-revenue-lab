"""Unit regressions for the #4139 Windows Resident integration guard."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

FILE = Path(__file__).resolve().parents[1] / "scripts/connector_resident_merge_guard.py"
spec = importlib.util.spec_from_file_location("connector_resident_merge_guard", FILE)
assert spec is not None and spec.loader is not None
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

SUPERVISOR = """
class ResidentLaunchRefused(RuntimeError): pass
class ResidentSupervisor:
    def start(self):
        if self._env is None:
            return self._popen('child')
        env = self._resolved_env()
        if env is None:
            raise ResidentLaunchRefused()
        return self._popen('child', env=env)
"""
RUNTIME = """
class ConnectApp:
    def __init__(self):
        self._supervisor = ResidentSupervisor(['child'], env=self._resident_environment)
    def start_registered_resident(self):
        try: self._supervisor.start()
        except ResidentLaunchRefused: return False
    def reconnect(self):
        try: self._supervisor.restart()
        except ResidentLaunchRefused: return
    def toggle_pause(self):
        try: self._supervisor.start()
        except ResidentLaunchRefused: return
"""
RESIDENT = """
def resume_registered_binding():
    return ProtectedDeviceBindingStore()
def main():
    return resume_registered_binding()
"""


def fixture(root: Path) -> None:
    paths = {
        guard.WIN / "resident_launch.py": "# feature enabled\n",
        guard.WIN / "resident_supervisor.py": SUPERVISOR,
        guard.WIN / "runtime.py": RUNTIME,
        guard.KAGENT / "local_agent_resident_process.py": RESIDENT,
        guard.KAGENT / "local_agent_device_binding_store.py": "# protected store\n",
    }
    for name, source in paths.items():
        full = root / name
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(source, encoding="utf-8")


class ResidentMergeSafetyTest(unittest.TestCase):
    def test_unintegrated_main_is_not_rejected(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(guard.audit(Path(tmp)), ("NOT_INTEGRATED", []))

    def test_reviewed_contract_passes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            self.assertEqual(guard.audit(root), ("PASS", []))

    def test_4463_style_overwrite_drops_environment_wiring(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            p = root / guard.WIN / "runtime.py"
            p.write_text(RUNTIME.replace(", env=self._resident_environment", ""), encoding="utf-8")
            state, issues = guard.audit(root)
            self.assertEqual(state, "FAIL")
            self.assertIn("connect_app_supervisor_requires_env_provider", issues)

    def test_declining_provider_cannot_fall_back_to_parent_environment(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            p = root / guard.WIN / "resident_supervisor.py"
            p.write_text(SUPERVISOR.replace("raise ResidentLaunchRefused()", "return self._popen('child')"), encoding="utf-8")
            state, issues = guard.audit(root)
            self.assertEqual(state, "FAIL")
            self.assertIn("supervisor_provider_none_must_refuse_before_spawn", issues)

    def test_runtime_refusal_handlers_survive_integration(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            p = root / guard.WIN / "runtime.py"
            p.write_text(RUNTIME.replace("except ResidentLaunchRefused: return False", "except ValueError: return False"), encoding="utf-8")
            state, issues = guard.audit(root)
            self.assertEqual(state, "FAIL")
            self.assertIn("start_registered_resident_must_handle_spawn_refusal", issues)

    def test_dpapi_restart_path_survives_integration(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            p = root / guard.KAGENT / "local_agent_resident_process.py"
            p.write_text(RESIDENT.replace("return resume_registered_binding()", "return None"), encoding="utf-8")
            state, issues = guard.audit(root)
            self.assertEqual(state, "FAIL")
            self.assertIn("resident_must_restore_canonical_protected_binding", issues)


if __name__ == "__main__":
    unittest.main()
