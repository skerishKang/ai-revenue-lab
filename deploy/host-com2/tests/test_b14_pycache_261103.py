"""Root import checks in the COM2 deploy scripts must not write bytecode.

The 2026-11-03 B14 rollout rolled back because a root-run import check left
`padiem_ai_core/__pycache__` in the staged tree and padiem-b14 could not read
it. Both scripts export the interpreter switch that prevents this.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEPLOY = HERE.parent


def test_the_deploy_and_b14_installers_disable_bytecode_writes():
    for name in ("deploy_from_main.sh", "b14/install.sh"):
        text = (DEPLOY / name).read_text(encoding="utf-8")
        assert "export PYTHONDONTWRITEBYTECODE=1" in text, name
