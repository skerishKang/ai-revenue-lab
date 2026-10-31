# -*- coding: utf-8 -*-
"""가짜 스트림 트랜스포트는 실제 stream_request 계약을 따라야 한다 (2026-10-31).

#6327 사고의 구조(가짜 포트가 ``**call`` 로 실제 포트가 거부하는 인자를 삼켜
테스트만 통과)가 Engine 스트림 트랜스포트에서도 재발하지 않게 하는 계약 테스트.
테스트 디렉토리 전체의 ``stream_request`` 정의를 ast로 수집해 실제
``CloudflareEngineServiceTransport.stream_request`` 프로토콜과 대조한다:

  1. ``**kwargs`` (VAR_KEYWORD) 금지 — 실제가 거부할 인자를 가짜가 삼키면
     드리프트는 무음으로 통과된다.
  2. 키워드 전용 매개변수 집합이 실제(method, url, headers, body)와 정확히
     같아야 한다 — 누락과 초과 모두 어긋남.
  3. 기본값이 있으면 안 된다 — 실제 프로토콜은 네 인자를 전부 필수로 요구하고
     호출자가 항상 넘긴다.

운영 코드는 변경하지 않는다. 어긋나는 것은 가짜 쪽을 고친다.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.worker_orchestration import CloudflareEngineServiceTransport

TESTS_ROOT = Path(__file__).resolve().parent


def _real_stream_contract() -> tuple[set[str], set[str]]:
    """Return (required keyword names, all accepted keyword names)."""
    signature = inspect.signature(CloudflareEngineServiceTransport.stream_request)
    required: set[str] = set()
    accepted: set[str] = set()
    for name, parameter in signature.parameters.items():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD) or name == "self":
            continue
        accepted.add(name)
        if parameter.default is parameter.empty:
            required.add(name)
    return required, accepted


def _stream_request_defs() -> list[tuple[str, int, ast.AsyncFunctionDef]]:
    found: list[tuple[str, int, ast.AsyncFunctionDef]] = []
    for source_file in sorted(TESTS_ROOT.rglob("*.py")):
        # utf-8-sig: some shipped test files carry a BOM that ast.parse refuses.
        tree = ast.parse(source_file.read_text(encoding="utf-8-sig", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                for child in node.body:
                    if isinstance(child, ast.AsyncFunctionDef) and child.name == "stream_request":
                        found.append((source_file.name, child.lineno, child))
    return found


def test_every_fake_stream_request_matches_the_real_protocol() -> None:
    required, accepted = _real_stream_contract()
    fakes = _stream_request_defs()
    assert fakes, "the audit must keep seeing the stream transport fakes it guards"

    violations: list[str] = []
    for file_name, lineno, function in fakes:
        where = f"{file_name}:{lineno}"
        arguments = function.args
        if arguments.vararg is not None or arguments.kwarg is not None:
            violations.append(
                f"{where}: **kwargs가 실제 트랜스포트가 거부할 인자를 삼킨다"
            )
            continue
        names = {arg.arg for arg in arguments.kwonlyargs}
        if names != accepted:
            violations.append(
                f"{where}: 키워드 집합이 실제 {sorted(accepted)}와 어긋난다: {sorted(names)}"
            )
        for parameter, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
            if default is not None:
                violations.append(f"{where}: {parameter.arg}에 기본값이 생겼다 — 실제는 전부 필수")
    assert not violations, "가짜 스트림 트랜스포트가 실제 계약과 어긋난다:\n" + "\n".join(violations)


def test_the_real_stream_protocol_keeps_the_documented_contract() -> None:
    required, accepted = _real_stream_contract()
    assert required == {"method", "url", "headers", "body"}, required
    assert accepted == {"method", "url", "headers", "body"}, accepted
