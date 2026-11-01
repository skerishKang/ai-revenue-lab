"""Exercise util streaming and failure handling with the real browser transport."""
import shutil
import subprocess
from pathlib import Path


def test_util_stream_empty_interruption_and_error():
    node = shutil.which("node")
    assert node, "Node.js is required for the browser transport check"
    script = Path(__file__).with_name("util_empty_result_261101.cjs")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout
