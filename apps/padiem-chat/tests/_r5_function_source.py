"""R5 0단계(0-1/R-01) — app.js와 분리 모듈을 같은 방법으로 읽는 시험 전용 도우미.

위험 R-01: 시험 54개 파일이 ``function 이름(`` 글자로 app.js를 잘라 함수 본문을
읽는다. 함수가 단계(A1~A10)마다 chat-*.js 모듈로 옮겨지면 같은 식이 app.js에
남은 한 줄 전달 함수만 잘라 읽거나 찾기 자체가 실패한다.

이 도우미는 함수 이름만으로 (1) 실제 정의(전달 함수 제외)가 있는 파일을
찾고, (2) 그 파일의 소스와 정의 위치를 내주며, (3) 정의 개수를 세고,
(4) ``_function_body`` 계열이 쓰던 것과 같은 절단 규칙으로 본문을 잘라 준다.
``combined_source()``는 index.html이 로드하는 순서(모듈 → app.js)로 합친
소스라서 ``.index("function 이름(")``·``.split(...)`` 계열이 이동 뒤에도 실제
본문을 먼저 찾는다.

제품 코드를 읽기만 한다. 단정 내용은 시험 파일이 그대로 갖고 있다.
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
STATIC = TESTS_DIR.parent / "static"
APP_JS = STATIC / "app.js"
INDEX_HTML = STATIC / "index.html"

# app.js가 남기는 한 줄 전달 함수:
#   [async] function 이름(...a) { return 어느모듈Module().이름(...a); }
_FORWARDER_LINE = re.compile(
    r"^(?:async\s+)?function\s+(?P<name>\w+)\s*\([^)]*\)\s*\{\s*return\s+"
    r"\w+Module\(\)\.(?P=name)\("
)
_MODULE_SCRIPT = re.compile(r'<script\s+src="\./([^"]+\.js)"')
# 실제 정의(전달 함수 제외) 찾기용
_DECLARATION = re.compile(r"(?:async\s+)?function\s+(?P<name>\w+)\s*\(")

_CACHE: dict[str, str] = {}


def _read_cached(path: Path) -> str:
    key = str(path)
    if key not in _CACHE:
        _CACHE[key] = path.read_text(encoding="utf-8")
    return _CACHE[key]


def app_source() -> str:
    """static/app.js 원문."""
    return _read_cached(APP_JS)


def module_files() -> tuple[Path, ...]:
    """index.html에서 app.js보다 먼저 로드하는 chat-*-module.js를 로드 순서대로."""
    index = _read_cached(INDEX_HTML)
    scripts = [(m.group(1), m.start()) for m in _MODULE_SCRIPT.finditer(index)]
    app_pos = next(pos for name, pos in scripts if name == "app.js")
    names = [n for n, pos in scripts if pos < app_pos and re.fullmatch(r"chat-[\w-]+-module\.js", n)]
    if not names:
        raise RuntimeError(
            "index.html에서 app.js 앞의 chat-*-module.js를 찾지 못했다: "
            f"{INDEX_HTML}"
        )
    return tuple(STATIC / n for n in names)


def module_sources() -> tuple[tuple[str, str], ...]:
    """((파일명, 원문), ...) — index.html 로드 순서."""
    return tuple((p.name, _read_cached(p)) for p in module_files())


def combined_source() -> str:
    """모듈 원문을 app.js 앞에 붙인 소스(index.html 로드 순서와 같다).

    preload(_node_appjs_modules_preload.js)가 Node vm에 넣어 주는 것과 같은
    텍스트라서 ``.index("function 이름(")`` 계열 식이 이동 뒤에도 실제 본문을
    먼저 가리킨다.
    """
    parts = [text for _, text in module_sources()]
    parts.append(app_source())
    return "\n".join(parts)


def _is_forwarder(source: str, occurrence: int) -> bool:
    """``occurrence`` 위치의 선언이 한 줄 전달 함수인지."""
    line_end = source.find("\n", occurrence)
    line = source[occurrence: line_end if line_end != -1 else len(source)]
    return bool(_FORWARDER_LINE.match(line))


def _occurrences(source: str, prefix: str, name: str) -> list[int]:
    needle = f"{prefix}{name}("
    return [m.start() for m in re.finditer(re.escape(needle), source)]


def _real_occurrences(source: str, prefix: str, name: str) -> list[int]:
    return [i for i in _occurrences(source, prefix, name) if not _is_forwarder(source, i)]


def definition_file(name: str, *, prefix: str = "function ") -> Path:
    """함수 ``name``의 실제 정의가 있는 파일(app.js 먼저, 그 뒤 모듈 로드 순서)."""
    if _real_occurrences(app_source(), prefix, name):
        return APP_JS
    for path in module_files():
        if _real_occurrences(_read_cached(path), prefix, name):
            return path
    raise LookupError(
        f"function {name!r} 의 실제 정의를 app.js와 chat-* 모듈에서 찾지 못했다 "
        f"(prefix={prefix!r})"
    )


def definition_source(name: str, *, prefix: str = "function ") -> str:
    """함수 ``name`` 실제 정의가 있는 파일의 소스 전체."""
    return _read_cached(definition_file(name, prefix=prefix))


def definition_index(name: str, *, prefix: str = "function ", source: str | None = None) -> int:
    """실제 정의(전달 함수 제외)의 위치. ``source``가 없으면 정의 파일 소스."""
    text = source if source is not None else definition_source(name, prefix=prefix)
    found = _real_occurrences(text, prefix, name)
    if not found:
        raise LookupError(
            f"function {name!r} 의 실제 정의가 주어진 소스에 없다 (prefix={prefix!r})"
        )
    return found[0]


def definition_count(name: str) -> int:
    """app.js + 모듈 전체에서의 실제 정의 개수(전달 함수는 세지 않는다)."""
    total = 0
    for text in [app_source()] + [text for _, text in module_sources()]:
        for m in _DECLARATION.finditer(text):
            if m.group("name") == name and not _is_forwarder(text, m.start()):
                total += 1
    return total


def function_body(name: str, *, prefix: str = "function ", end: str = "\n  }") -> str:
    """정의 위치부터 ``end``(기본 닫는 중괄호 앞 줄)까지 — 시험의
    ``_function_body(source, name)``와 같은 절단 규칙."""
    source = definition_source(name, prefix=prefix)
    start = definition_index(name, prefix=prefix, source=source)
    stop = source.index(end, start)
    return source[start:stop]


def from_definition(name: str, *, prefix: str = "function ") -> str:
    """정의 위치부터 정의 파일 끝까지 — ``source[source.index(...):]`` 계열."""
    source = definition_source(name, prefix=prefix)
    return source[definition_index(name, prefix=prefix, source=source):]
