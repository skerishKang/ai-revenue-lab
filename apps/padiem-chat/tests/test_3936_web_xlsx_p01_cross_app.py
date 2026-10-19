"""#3936: the real B62 P01 route against the real Engine ToolExecution service.

The harness runs in a subprocess because it loads two ``app`` packages (the
Engine's and B62's) in one interpreter; see
``web_xlsx_p01_cross_app_pause_harness.py``. Nothing here touches Cloudflare, a
model, R2, Drive or Telegram: it is synthetic bytes, in-memory sqlite D1 and the
repository's own Engine caller-registry overlay payload.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
HARNESS = HERE / "web_xlsx_p01_cross_app_pause_harness.py"

PASS_MARKERS = (
    "CROSS_APP_ENGINE_CALLER_AUTH=PASS",
    "CROSS_APP_FOREIGN_APP_REFUSED=PASS",
    "CROSS_APP_OWNER_UPLOAD=PASS",
    "CROSS_APP_ORIGINAL_SHA_PRESERVED=PASS",
    "CROSS_APP_OWNER_SELECTION=PASS",
    "CROSS_APP_ENGINE_PAUSE_ISSUED=PASS",
    "CROSS_APP_B62_REQUEST_COMMITTED=PASS",
    "CROSS_APP_ENGINE_CONTINUATION_DURABLE=PASS",
    "CROSS_APP_DIAGNOSTIC_NO_LEAK=PASS",
    "READ_IS_NOT_WRITE=PASS",
    "WEB_XLSX_P01_CROSS_APP_PAUSE=PASS",
)

# The harness's own output must stay free of identifiers and credentials.
LEAK_SENTINELS = ("usr_web_xlsx_owner", "cross-app-harness-credential")


def test_real_b62_route_and_real_engine_agree_on_the_p01_pause():
    result = subprocess.run(
        [sys.executable, str(HARNESS)],
        capture_output=True, text=True, timeout=120, check=False,
        cwd=str(HERE),
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    for marker in PASS_MARKERS:
        assert marker in result.stdout, marker
    for sentinel in LEAK_SENTINELS:
        assert sentinel not in output, sentinel
