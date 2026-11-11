"""R5 0단계-A — 큰 파일 크기 상한 시험 (#7216).

상한은 "커지는 것을 알리는 장치"다. 기존 큰 파일을 억제로 쪼개는 것이 아니라,
새 기능이 기존 거대 파일에 계속 쌓이는 것을 감지해 실패/경고로 알린다.
실제 분해는 R5 후속 단계에서 기능별 모듈 파일로 진행한다(코드 이동 없음).

상한 값은 이 시험이 작성된 시점의 줄 수 + 100 으로 고정한다. 상한 상향 금지.
줄 수는 빈 마지막 줄을 제외한 실제 줄 수(splitlines)로 센다.
"""
from pathlib import Path
import warnings

ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "apps" / "padiem-chat" / "static"
APP_JS = STATIC / "app.js"

# R5 A2단계 이동 후 app.js 4841 줄 + 100 (기억·실행 기록 구역 보강 4가지 방식으로 이동).
# (직전 값: A1단계 이동 후 5765 + 100 = 5865; B1 시범 후 실측은 5439였음)
APP_JS_CAP = 4941

FAIL_MSG = ("상한은 커지는 것을 알리는 장치다. 억지로 쪼개지 말고 새 기능은 새 모듈 파일로 만든다. "
            "상한 상향 금지(#7216).")

# app.js 이외 정적 JS 중 이미 1,000 줄을 넘는 파일의 개별 상한(작성 시점 줄 수 + 100).
# 예외를 추가하려면 반드시 해당 파일 맨 위에 이유 주석을 남긴다. 예외 없는 파일은
# 500 초과 경고, 1,000 초과 실패다.
EXCEPTIONS = {
    "b66-quote-runtime.js": 1850,      # 1750 + 100
    "calendar.js": 1632,               # 1532 + 100
    "claw-web-xlsx-sources.js": 1518,  # 1418 + 100
    "locale.js": 1217,                 # 1117 + 100
    "message-lifecycle.js": 1325,      # 1225 + 100
    "product-capabilities.js": 2318,   # 2218 + 100
    "util-pdfmd.js": 1399,             # 1299 + 100
}

# 백엔드/실행기 거대 파일 개별 상한(작성 시점 줄 수 + 100).
PYTHON_CAPS = {
    "apps/korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py": 3533,  # 3433 + 100
    "apps/korean-ai-code-agent/src/kagent/local_agent_meshcentral_command_port.py": 2110,  # 2010 + 100
    "apps/padiem-chat/app/chat_routes.py": 1848,  # 1748 + 100
}


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_app_js_stays_under_its_cap() -> None:
    n = _lines(APP_JS)
    assert n <= APP_JS_CAP, f"app.js {n} > {APP_JS_CAP}. {FAIL_MSG}"


def test_other_static_js_warn_over_500_fail_over_cap() -> None:
    for path in sorted(STATIC.rglob("*.js")):
        if path.name == "app.js":
            continue
        n = _lines(path)
        cap = EXCEPTIONS.get(path.name, 1000)
        if n > cap:
            raise AssertionError(f"{path.name} {n} > {cap}. {FAIL_MSG}")
        if n > 500:
            warnings.warn(f"{path.name} {n} lines (>500). 새 기능은 새 모듈 파일로. {FAIL_MSG}")


def test_python_giant_modules_stay_under_cap() -> None:
    for rel, cap in PYTHON_CAPS.items():
        n = _lines(ROOT / rel)
        assert n <= cap, f"{rel} {n} > {cap}. {FAIL_MSG}"
