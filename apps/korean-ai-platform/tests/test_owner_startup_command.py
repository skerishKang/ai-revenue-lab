from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = PROJECT_ROOT / "README.md"
DOCUMENTED_COMMAND = (
    "python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_documented_owner_command_uses_dependency_free_bootstrap() -> None:
    text = README.read_text(encoding="utf-8")
    assert DOCUMENTED_COMMAND in text
    assert "python3 -m uvicorn app.main:app --env-file .env" not in text
    assert "app.main` loads working-directory `.env`" in text


def test_documented_owner_startup_loads_dotenv_end_to_end(tmp_path: Path) -> None:
    """Start the app the same way the README tells the owner to start it.

    The subprocess runs from a clean temporary working directory whose only
    configuration is a non-secret .env file. PYTHONPATH points at the checked
    out application source, so app.main must load the working-directory .env
    before the factory is created. No external network request is made.

    The surrounding test suite may run with PYTHONWARNINGS=error. That variable
    is deliberately not part of the documented owner startup command, so it is
    removed from the child environment instead of turning third-party
    deprecation warnings into a false startup failure.
    """

    python3 = shutil.which("python3")
    assert python3, "python3 must be available for the documented owner command"

    (tmp_path / ".env").write_text(
        "B14_PROVIDER_MODE=live\n",
        encoding="utf-8",
    )

    port = _free_port()
    env = os.environ.copy()
    env.pop("B14_PROVIDER_MODE", None)
    env.pop("OPENROUTER_API_KEY", None)
    env.pop("PYTHONWARNINGS", None)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT)
        if not existing_pythonpath
        else str(PROJECT_ROOT) + os.pathsep + existing_pythonpath
    )

    command = [
        python3,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    process = subprocess.Popen(
        command,
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    output = ""
    try:
        deadline = time.monotonic() + 15
        payload = None
        last_error: Exception | None = None
        url = f"http://127.0.0.1:{port}/api/pilot/health"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                with urllib.request.urlopen(url, timeout=0.5) as response:
                    assert response.status == 200
                    payload = json.loads(response.read().decode("utf-8"))
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = exc
                time.sleep(0.1)

        if payload is None:
            if process.stdout is not None:
                output = process.stdout.read()
            raise AssertionError(
                f"documented owner startup did not reach health; "
                f"returncode={process.poll()} last_error={last_error!r} output={output!r}"
            )

        assert payload["business14"]["provider_mode"] == "live"
        assert payload["business14"]["has_key"] is False
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stdout is not None:
            output += process.stdout.read()
            process.stdout.close()

    assert "OPENROUTER_API_KEY" not in output
    assert "sk-or-v1" not in output
