# -*- coding: utf-8 -*-
"""가짜 읽기 포트는 실제 MeshCentralFileReadPort 계약을 따라야 한다 (2026-10-31).

이번 주 실제 사고(#6327 수리)의 구조: 가짜 read 포트가 ``**call`` 로 모든 인자를
삼켜, 실제 포트가 거부하는 ``timeout_seconds=None`` 이 테스트에서 통과했고 운영의
모든 PC 읽기가 실패했다. 같은 구조는 #6319(가짜 insertBefore가 잘못된 기준 노드를
허용)와 큐 스키마 사고에서도 반복됐다.

이 계약 테스트는 그 재발을 모듈 단위로 차단한다. 테스트 디렉토리 전체의
``read_bytes`` 정의를 ast로 수집해 실제 프로토콜과 대조한다:

  1. ``**kwargs`` / ``**call`` (VAR_KEYWORD) 금지 — 실제 포트가 거부하는 인자를
     가짜가 삼키면 드리프트는 무음으로 통과된다.
  2. 실제 프로토콜의 필수 키워드(node_ref, file_path, timeout_seconds)를 전부
     받아야 한다.
  3. 실제 프로토콜에 없는 매개변수를 받으면 안 된다.
  4. ``timeout_seconds`` 의 기본값이 None이면 안 된다 — 그 기본값이 사고의
     표면이었다. 생략을 관찰해야 하는 기록 가짜는 센티널 기본값을 쓴다.

운영 코드는 이 테스트가 아니라 이 테스트의 대상이다. 가짜를 고치는 것만 허용된다.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from kagent.local_agent_meshcentral_private_reader import MeshCentralFileReadPort

TESTS_ROOT = Path(__file__).resolve().parent


def _real_port_contract() -> tuple[set[str], set[str]]:
    """Return (required keyword names, all accepted keyword names)."""
    signature = inspect.signature(MeshCentralFileReadPort.read_bytes)
    required: set[str] = set()
    accepted: set[str] = set()
    for name, parameter in signature.parameters.items():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD) or name == "self":
            continue
        accepted.add(name)
        if parameter.default is parameter.empty:
            required.add(name)
    return required, accepted


def _fake_read_bytes_defs() -> list[tuple[str, int, ast.FunctionDef]]:
    found: list[tuple[str, int, ast.FunctionDef]] = []
    for source_file in sorted(TESTS_ROOT.rglob("*.py")):
        tree = ast.parse(source_file.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == "read_bytes":
                        found.append((source_file.name, child.lineno, child))
    return found


def test_every_fake_read_bytes_matches_the_real_port_contract() -> None:
    required, accepted = _real_port_contract()
    fakes = _fake_read_bytes_defs()
    assert fakes, "the audit must keep seeing the read port fakes it guards"

    violations: list[str] = []
    for file_name, lineno, function in fakes:
        where = f"{file_name}:{lineno}"
        arguments = function.args
        if arguments.vararg is not None or arguments.kwarg is not None:
            violations.append(
                f"{where}: *args/**kwargs 가 실제 포트가 거부하는 인자를 삼킨다"
            )
            continue
        names = {arg.arg for arg in arguments.kwonlyargs}
        defaults = arguments.kw_defaults
        for parameter, default in zip(arguments.kwonlyargs, defaults):
            if parameter.arg == "timeout_seconds" and default is not None:
                if isinstance(default, ast.Constant) and default.value is None:
                    violations.append(
                        f"{where}: timeout_seconds 기본값 None은 #6327 사고의 표면이다"
                    )
        missing = required - names
        if missing:
            violations.append(f"{where}: 실제 포트의 필수 키워드 누락 {sorted(missing)}")
        extra = names - accepted
        if extra:
            violations.append(f"{where}: 실제 프로토콜에 없는 매개변수 {sorted(extra)}")

    assert not violations, "가짜 읽기 포트가 실제 계약과 어긋난다:\n" + "\n".join(violations)


def test_the_real_port_itself_keeps_the_documented_contract() -> None:
    required, accepted = _real_port_contract()
    assert required == {"node_ref", "file_path", "timeout_seconds"}, required
    assert accepted == {"node_ref", "file_path", "timeout_seconds", "max_bytes"}, accepted
    signature = inspect.signature(MeshCentralFileReadPort.read_bytes)
    # 사고(#6327)의 원인 값이 프로토콜 기본값으로 되돌아오면 이 테스트가 잡는다.
    assert signature.parameters["timeout_seconds"].default is inspect.Parameter.empty
