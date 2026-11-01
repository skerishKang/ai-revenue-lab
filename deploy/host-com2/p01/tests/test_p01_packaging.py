"""Offline P01 packaging checks; never install/start/enable a host service."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
SECRET = "p01-host-caller-secret-0123456789abcdef"
HEALTH_BODY = {
    "status": "ok",
    "service": "padiem-ai-engine",
    "completed_run": True,
    "streaming_run": True,
    "service_identity": "required_for_all_non_health_routes",
}


def _execute(name: str, location: Path):
    spec = importlib.util.spec_from_file_location(name, location)
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses resolve their own module by name.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load(name: str):
    return _execute(name, HERE / (name + ".py"))


def load_path(name: str, path: Path):
    return _execute(name, path)


check_config = load("check_config")
health = load("health")


def _env(**overrides) -> dict[str, str]:
    base = {
        "P01_HOST": "127.0.0.1",
        "P01_PORT": "8811",
        "PADIEM_ENGINE_CALLER_ID": "b62-chat-host",
        "PADIEM_ENGINE_CALLER_SECRET": SECRET,
    }
    base.update(overrides)
    return base


def _app_root(root: Path, *, asgi: bool = True) -> Path:
    entry = root / "app" / "asgi.py"
    (root / "app").mkdir(parents=True, exist_ok=True)
    if asgi:
        entry.write_text("# stub\n", encoding="utf-8")
    else:
        entry.unlink(missing_ok=True)
    return root


class P01Packaging(unittest.TestCase):
    def test_scripts_are_bash_valid_and_install_is_read_only_by_default(self):
        for script in ("install.sh", "start.sh", "stop.sh", "status.sh"):
            subprocess.run(["bash", "-n", script], cwd=HERE, check=True)
        for arguments in ([], ["--dry-run"]):
            result = subprocess.run(
                ["bash", "install.sh", *arguments],
                cwd=HERE, check=True, text=True, capture_output=True, encoding="utf-8",
            )
            self.assertIn("P01_COM2_INSTALL=DRY_RUN", result.stdout)
            self.assertIn("START_SERVICE=NO", result.stdout)
            self.assertIn("ENABLE_SERVICE=NO", result.stdout)
            self.assertIn("TUNNEL_CHANGE=NO", result.stdout)
            self.assertIn("CHAT_ENV_CHANGE=NO", result.stdout)
            self.assertIn("PORT=8811", result.stdout)
        install = (HERE / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("systemctl start", install)
        self.assertNotIn("systemctl enable", install)
        self.assertIn("ASGI_ENTRY_MISSING", install)
        self.assertIn("FOREIGN_UNIT_TARGET", install)

    def test_no_script_enables_or_writes_chat_configuration(self):
        for script in ("install.sh", "start.sh", "stop.sh", "status.sh"):
            text = (HERE / script).read_text(encoding="utf-8")
            self.assertNotIn("systemctl enable", text, script)
            self.assertNotIn("chat-com2", text, script)
        status = (HERE / "status.sh").read_text(encoding="utf-8")
        self.assertNotIn("systemctl start", status)
        self.assertNotIn("systemctl restart", status)

    def test_unit_binds_loopback_8811_and_never_names_the_windows_release(self):
        unit = (HERE / "padiem-p01.service.example").read_text(encoding="utf-8")
        self.assertIn("--host 127.0.0.1", unit)
        self.assertIn("--port 8811", unit)
        self.assertIn("Environment=P01_HOST=127.0.0.1", unit)
        self.assertIn("Environment=P01_PORT=8811", unit)
        self.assertIn("WorkingDirectory=/opt/padiem/p01/app", unit)
        self.assertIn("EnvironmentFile=-/opt/padiem/p01/env/p01.env", unit)
        self.assertIn("ConditionPathExists=/opt/padiem/p01/app/asgi.py", unit)
        self.assertIn("ExecCondition=/opt/padiem/p01/venv/bin/python", unit)
        self.assertIn("ReadWritePaths=/opt/padiem/p01/data /opt/padiem/p01/logs", unit)
        self.assertNotIn("0.0.0.0", unit)
        self.assertNotIn("18731", unit)
        self.assertNotIn("User=root", unit)

    def test_env_example_carries_names_only(self):
        text = (HERE / "p01.env.example").read_text(encoding="utf-8")
        values: dict[str, str] = {}
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            name, _, value = line.partition("=")
            values[name] = value
        self.assertEqual(values["P01_HOST"], "127.0.0.1")
        self.assertEqual(values["P01_PORT"], "8811")
        for name, value in values.items():
            self.assertIn(name, {
                "P01_HOST", "P01_PORT", "PADIEM_ENGINE_CALLER_ID",
                "PADIEM_ENGINE_CALLER_SECRET",
                "PADIEM_ENGINE_AUTHORITY_DIAGNOSTIC_TOKEN",
                "PADIEM_ENGINE_LOCAL_IDENTITY_ORIGIN",
                "PADIEM_ENGINE_LOCAL_IDENTITY_SECRET",
                "PADIEM_ENGINE_LOCAL_ADMISSION_ORIGIN",
                "PADIEM_ENGINE_LOCAL_ADMISSION_SECRET",
            })
            if name not in {"P01_HOST", "P01_PORT"}:
                self.assertEqual(value, "", name)
            self.assertFalse(name.startswith("PADIEM_CHAT_"), name)
        # The Chat-side origin is documented here and owned by the chat package.
        self.assertIn("PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN=http://127.0.0.1:8811", text)

    def test_gitattributes_pins_the_unit_and_env_example_to_lf(self):
        attributes = (REPO / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("deploy/host-com2/p01/*.service.example text eol=lf", attributes)
        self.assertIn("deploy/host-com2/p01/p01.env.example text eol=lf", attributes)

    def test_ready_configuration_passes(self):
        with _TempRoot() as root:
            self.assertIsNone(check_config.check(_env(), _app_root(root)))

    def test_a_routable_bind_is_refused(self):
        with _TempRoot() as root:
            for host in ("0.0.0.0", "192.168.0.2", "::", "localhost"):
                self.assertEqual(
                    check_config.check(_env(P01_HOST=host), _app_root(root)),
                    "p01_bind_not_loopback",
                )

    def test_any_other_port_is_refused(self):
        with _TempRoot() as root:
            for port in ("18731", "8810", ""):
                self.assertEqual(
                    check_config.check(_env(P01_PORT=port), _app_root(root)),
                    "p01_port_mismatch",
                )

    def test_the_dev_flag_and_a_missing_entrypoint_are_refused(self):
        with _TempRoot() as root:
            self.assertEqual(
                check_config.check(_env(PADIEM_LOCAL_DEV="1"), _app_root(root)),
                "p01_local_dev_forbidden",
            )
            self.assertEqual(
                check_config.check(_env(), _app_root(root, asgi=False)),
                "p01_asgi_entry_missing",
            )

    def test_caller_identity_shape_is_checked_without_echoing_values(self):
        with _TempRoot() as root:
            self.assertEqual(
                check_config.check(_env(PADIEM_ENGINE_CALLER_ID=" "), _app_root(root)),
                "p01_caller_id_invalid",
            )
            self.assertEqual(
                check_config.check(_env(PADIEM_ENGINE_CALLER_SECRET="short"), _app_root(root)),
                "p01_caller_secret_invalid",
            )
            stdout = io.StringIO()
            with unittest.mock.patch.dict(os.environ, _env(PADIEM_ENGINE_CALLER_SECRET="short"), clear=True):
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(check_config.main(["--app-root", str(root)]), 2)
            printed = stdout.getvalue()
            self.assertIn("P01_CONFIG=REFUSED reason=p01_caller_secret_invalid", printed)
            self.assertNotIn("short", printed)

    def test_health_probe_matches_the_existing_supervisor_contract(self):
        runtime = load_path("com2_runtime", REPO / "scripts" / "ops" / "com2_runtime.py")
        self.assertTrue(runtime.CONTRACTS["p01"](HEALTH_BODY))
        with _HealthServer(HEALTH_BODY) as url:
            code, issues, observed = health.probe(url, 5.0)
        self.assertEqual((code, issues), (0, []))
        self.assertEqual(observed["service"], "padiem-ai-engine")

    def test_health_probe_names_each_contract_violation(self):
        broken = dict(HEALTH_BODY, status="degraded", streaming_run=False)
        with _HealthServer(broken) as url:
            code, issues, _ = health.probe(url, 5.0)
        self.assertEqual(code, 1)
        self.assertIn("status_not_ok", issues)
        self.assertIn("streaming_run_not_true", issues)


class _TempRoot:
    """tempfile.TemporaryDirectory with a short alias for readability."""

    def __init__(self) -> None:
        import tempfile

        self._dir = tempfile.TemporaryDirectory()

    def __enter__(self) -> Path:
        return Path(self._dir.name)

    def __exit__(self, *exc_info) -> None:
        self._dir.cleanup()


class _HealthServer:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.url = ""

    def __enter__(self) -> str:
        body = self._body

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                del args

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}/internal/v1/health"
        return self.url

    def __exit__(self, *exc_info) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()


def _stage_shared_stubs(checkout: Path):
    for relative in (
        "packages/padiem-ai-core/padiem_ai_core",
        "packages/padiem-control-plane/padiem_control_plane",
        "apps/korean-ai-code-agent/src/kagent",
    ):
        package = checkout / relative
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("# stub\n", encoding="utf-8")


class P01CodeStage(unittest.TestCase):
    def test_stage_reinstall_and_missing_entry(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "checkout" / "apps" / "padiem-ai-engine"
            _stage_shared_stubs(root / "checkout")
            target = root / "p01"
            target.mkdir()
            for name in ("app", "clients", "ingress", "migrations"):
                (source / name).mkdir(parents=True)
            for name in ("asgi.py", "worker.py", "worker_identity.py"):
                (source / name).write_text("# entry\n", encoding="utf-8")
            file = source / "app" / "local_admission_binding.py"
            file.write_text("revision = 1\n", encoding="utf-8")
            command = ["bash", str(HERE / "stage_code.sh"), str(root / "checkout"), str(target)]
            subprocess.run(command, check=True, capture_output=True)
            installed = target / "app" / "app" / "local_admission_binding.py"
            self.assertEqual(installed.read_text(encoding="utf-8"), "revision = 1\n")
            file.write_text("revision = 2\n", encoding="utf-8")
            subprocess.run(command, check=True, capture_output=True)
            self.assertEqual(installed.read_text(encoding="utf-8"), "revision = 2\n")
            snapshots = list((target / "rollback").glob("*/app/local_admission_binding.py"))
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].read_text(encoding="utf-8"), "revision = 1\n")
            (source / "asgi.py").unlink()
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ASGI_ENTRY_MISSING", result.stderr)
            self.assertEqual(installed.read_text(encoding="utf-8"), "revision = 2\n")

    def test_checkout_symlink_is_snapshotted_before_switch(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "checkout" / "apps" / "padiem-ai-engine"
            _stage_shared_stubs(root / "checkout")
            target = root / "p01"
            target.mkdir()
            for name in ("app", "clients", "ingress", "migrations"):
                (source / name).mkdir(parents=True)
            for name in ("asgi.py", "worker.py", "worker_identity.py"):
                (source / name).write_text("# entry\n", encoding="utf-8")
            old = root / "old-checkout"
            old.mkdir()
            (old / "asgi.py").write_text("original\n", encoding="utf-8")
            (target / "app").symlink_to(old, target_is_directory=True)
            subprocess.run(["bash", str(HERE / "stage_code.sh"),
                            str(root / "checkout"), str(target)], check=True, capture_output=True)
            (old / "asgi.py").write_text("changed\n", encoding="utf-8")
            snapshots = list((target / "rollback").glob("*/asgi.py"))
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].read_text(encoding="utf-8"), "original\n")


    def test_real_app_with_cycle_is_snapshotted_and_switched(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "checkout" / "apps" / "padiem-ai-engine"
            _stage_shared_stubs(root / "checkout")
            target = root / "p01"
            for name in ("app", "clients", "ingress", "migrations"):
                (source / name).mkdir(parents=True)
            for name in ("asgi.py", "worker.py", "worker_identity.py"):
                (source / name).write_text("new", encoding="utf-8")
            old = target / "app"
            old.mkdir(parents=True)
            (old / "asgi.py").write_text("old", encoding="utf-8")
            (old / "cycle").symlink_to(".", target_is_directory=True)
            subprocess.run(["bash", str(HERE / "stage_code.sh"),
                            str(root / "checkout"), str(target)],
                           check=True, capture_output=True, timeout=15)
            self.assertTrue((target / "app").is_symlink())
            self.assertEqual((target / "app" / "asgi.py").read_text(), "new")
            snapshot = next((target / "rollback").glob("p01.*"))
            self.assertEqual((snapshot / "asgi.py").read_text(), "old")
            self.assertFalse((snapshot / "cycle").exists())


    def test_shared_packages_are_copied_readable_and_detached(self):
        import tempfile
        import shutil
        import stat
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkout = root / "checkout"
            _stage_shared_stubs(checkout)
            source = checkout / "apps/padiem-ai-engine"
            for name in ("app", "clients", "ingress", "migrations"):
                (source / name).mkdir(parents=True)
            for name in ("asgi.py", "worker.py", "worker_identity.py"):
                (source / name).write_text("# entry\n", encoding="utf-8")
            for path in checkout.rglob("__init__.py"):
                path.chmod(0o600)
            target = root / "p01"
            target.mkdir()
            result = subprocess.run(
                ["bash", str(HERE / "stage_code.sh"), str(checkout), str(target)],
                capture_output=True, text=True, preexec_fn=lambda: os.umask(0o077),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            release = (target / "app").resolve()
            for name in ("padiem_ai_core", "padiem_control_plane", "kagent"):
                package = release / name / "__init__.py"
                self.assertTrue(package.is_file())
                self.assertTrue(package.stat().st_mode & stat.S_IROTH)
                self.assertFalse(package.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH))
            shutil.rmtree(checkout)
            for name in ("padiem_ai_core", "padiem_control_plane", "kagent"):
                self.assertTrue((release / name / "__init__.py").is_file())



    def test_real_release_import_as_service_user(self):
        import pwd
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o755)
            target = root / "p01"
            target.mkdir()
            result = subprocess.run(
                ["bash", str(HERE / "stage_code.sh"), str(REPO), str(target)],
                capture_output=True, text=True, preexec_fn=lambda: os.umask(0o077),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            release = (target / "app").resolve()
            env = {"PADIEM_LOCAL_DEV": "1", "PATH": os.environ.get("PATH", "")}
            drop = None
            if os.geteuid() == 0:
                try:
                    user = pwd.getpwnam("padiem-p01")
                except KeyError:
                    user = pwd.getpwnam("nobody")
                def drop():
                    os.setgroups([])
                    os.setgid(user.pw_gid)
                    os.setuid(user.pw_uid)
            probe = subprocess.run(
                [sys.executable, "-I", "-c",
                 "import os,sys; sys.path.insert(0, os.getcwd()); "
                 "import asgi,padiem_ai_core,padiem_control_plane,kagent; "
                 "root=os.path.realpath(os.getcwd()); "
                 "assert all(os.path.realpath(m.__file__).startswith(root+os.sep) "
                 "for m in (asgi,padiem_ai_core,padiem_control_plane,kagent))"],
                cwd=release, env=env, preexec_fn=drop, capture_output=True, text=True,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)
