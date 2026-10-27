"""Load the REAL static/council-app.js prompt builders for the prompt contract.

The builders are pure prompt assembly, so the Python test executes them
through the same Node VM harness with a form-recording shim. This keeps one
shipped source of truth: the file the browser will run is the file under
test.
"""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import shutil
import subprocess

APP_ROOT = Path(__file__).resolve().parents[1]
COUNCIL_JS = APP_ROOT / "static" / "council-app.js"
HARNESS_JS = APP_ROOT / "tests" / "_council_harness.js"


class _Builders:
    """Prompt builders proxied through the Node harness one call at a time."""

    def _call(self, builder, payload):
        node = shutil.which("node")
        assert node, "node runtime is required for the council prompt contract"
        completed = subprocess.run(
            [node, str(HARNESS_JS), str(COUNCIL_JS), "prompt", builder, json.dumps(payload, ensure_ascii=False)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(APP_ROOT),
            check=False,
        )
        assert completed.stdout.strip(), completed.stdout + completed.stderr
        result = json.loads(completed.stdout)
        assert result["ok"] is True, result
        return result["prompt"]

    @property
    def speech(self):
        class _Speech:
            buildPrompt = lambda _, form: self._call("speech", form)  # noqa: E731
        return _Speech()

    @property
    def sns(self):
        class _Sns:
            buildPrompt = lambda _, form, platform, photos=None: self._call(
                "sns", {**form, "platform": platform, "photos": photos or []})  # noqa: E731
        return _Sns()

    @property
    def meeting(self):
        class _Meeting:
            buildPrompt = lambda _, form: self._call("meeting", form)  # noqa: E731
            buildBookPrompt = lambda _, contents: self._call("book", {"contents": contents})  # noqa: E731
        return _Meeting()


@lru_cache(maxsize=1)
def load_council_module() -> _Builders:
    return _Builders()


SCENARIOS = ("generate", "restore", "errors", "calendar_words", "auth",
             "auth_routing", "selection", "book")


@lru_cache(maxsize=len(SCENARIOS))
def run(scenario: str) -> dict:
    """Return the observations of one behavioural harness scenario (cached)."""

    if scenario not in SCENARIOS:
        raise AssertionError(f"unknown council scenario: {scenario!r}")
    node = shutil.which("node")
    assert node, "node runtime is required for the council-app behavioural harness"
    completed = subprocess.run(
        [node, str(HARNESS_JS), str(COUNCIL_JS), scenario],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(APP_ROOT),
        check=False,
    )
    assert completed.stdout.strip(), completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["ok"] is True, result
    assert result["scenario"] == scenario, result
    return result["observation"]

