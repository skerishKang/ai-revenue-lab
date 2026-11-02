"""로컬 venv에는 pytest가 없어 전역 Python의 pytest로 돌고, 그 환경에는
다른 레인 작업대의 korean-ai-code-agent가 editable로 걸려 있다. 저장소 src를
sys.path 맨 앞에 놓아 kagent가 항상 이 저장소에서 읽히게 고정한다."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[3]
for _p in (
    str(_root / "apps" / "korean-ai-code-agent" / "src"),
    str(_root / "packages" / "padiem-ai-core"),
    str(_root / "packages" / "padiem-control-plane"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)
