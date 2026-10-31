from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / 'packages/padiem-control-plane', ROOT / 'packages/padiem-control-plane/tests'):
    sys.path.insert(0, str(path))
