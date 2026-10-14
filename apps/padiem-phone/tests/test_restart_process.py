"""Real loopback subprocess smoke: mock records survive a Python server restart.

Uses a temp LOCALAPPDATA; does not touch customer files, SIP, or public networks.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


class RestartSmoke(unittest.TestCase):
    def test_unfinished_task_is_interrupted_and_scripts_survive_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            env = dict(os.environ)
            env["LOCALAPPDATA"] = temp
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            base = f"http://127.0.0.1:{port}"

            def call(path, payload=None):
                req = Request(
                    base + path,
                    data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
                    headers={"Content-Type": "application/json"} if payload is not None else {},
                    method="POST" if payload is not None else "GET",
                )
                with urlopen(req, timeout=2) as res:
                    return json.loads(res.read())

            def start_server():
                proc = subprocess.Popen(
                    [sys.executable, str(ROOT / "server.py"), str(port)],
                    cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                for _ in range(80):
                    if proc.poll() is not None:
                        self.fail("preview subprocess terminated unexpectedly")
                    try:
                        call("/api/usage")
                        return proc
                    except (OSError, URLError):
                        time.sleep(.07)
                proc.terminate()
                proc.wait(timeout=5)
                self.fail("loopback preview failed to start")

            def stop_server(proc):
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

            proc = start_server()
            try:
                script = call("/api/scripts", {
                    "title": "재시작 테스트", "destination": "가상 대상",
                    "goal": "재시작 후 남는지 확인해 줘", "questions": "확인 문항",
                    "notes": "실제 전화 불가",
                })
                task = call("/api/tasks", {
                    "request_id": "restart_mocks_1", "destination": script["destination"],
                    "goal": script["goal"], "source": "claw", "scenario": "extended",
                    "script_id": script["script_id"],
                })
                self.assertEqual(task["state"], "DIALING")
                task_id = task["task_id"]
            finally:
                stop_server(proc)
            proc = start_server()
            try:
                later = call("/api/tasks/" + task_id)
                self.assertEqual(later["state"], "INTERRUPTED")
                self.assertTrue(later["terminal"])
                self.assertEqual(later["network_calls"], 0)
                self.assertEqual(later["real_charges"], 0)
                scripts = call("/api/scripts")["scripts"]
                self.assertEqual(scripts[-1]["script_id"], script["script_id"])
                usage = call("/api/usage")
                self.assertEqual(usage["active"], 0)
                self.assertEqual(usage["real_calls"], 0)
                self.assertEqual(usage["real_charges"], 0)
                self.assertTrue((temp_dir / "PadiemPhonePreview" / "mock_tasks.json").exists())
                self.assertTrue((temp_dir / "PadiemPhonePreview" / "scripts.json").exists())
            finally:
                stop_server(proc)


if __name__ == "__main__":
    unittest.main()
