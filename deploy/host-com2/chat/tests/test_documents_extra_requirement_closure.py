"""#8052 — COM2 Chat 런타임이 Core documents extra 폐쇄를 갖는지.

컴2 Chat venv에는 로컬 체크아웃의 ``padiem_ai_core``가 심볼릭 링크로 들어오고
제3자 의존성만 ``requirements.txt``로 설치한다. 문서(XLSX) 경로가 쓰는
``openpyxl``과 그 의존 ``et-xmlfile``이 빠지면 유틸 Excel 열기가
``document_dependency_unavailable``(422)로 실패한다.

이 시험은 ``packages/padiem-ai-core/pyproject.toml``의 ``documents`` extra를
기준으로, 그 extra의 패키지와 전이 의존(``apps/padiem-chat/uv.lock``에서 해석)이
``deploy/host-com2/chat/requirements.txt``에 모두 고정돼 있는지 확인한다.
버전과 해시가 잠금 파일과 어긋나도 실패한다 — 목록 존재만 보는 약한 검사가 아니다.
"""
from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
REQUIREMENTS = HERE / "requirements.txt"
CORE_PROJECT = ROOT / "packages" / "padiem-ai-core" / "pyproject.toml"
CHAT_LOCK = ROOT / "apps" / "padiem-chat" / "uv.lock"

PIN_RX = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)")
HASH_RX = re.compile(r"--hash=sha256:([0-9a-f]{64})")
LOCK_HASH_RX = re.compile(r"sha256:([0-9a-f]{64})")


def _canonical(name: str) -> str:
    return name.lower().replace("_", "-")


def _requirement_closure() -> tuple[dict[str, dict], set[str]]:
    project = tomllib.loads(CORE_PROJECT.read_text(encoding="utf-8"))
    extra = project["project"]["optional-dependencies"]["documents"]
    roots = {
        _canonical(re.split(r"[<>=!~;\[ ]", requirement.strip())[0])
        for requirement in extra
        if requirement.strip()
    }

    lock = tomllib.loads(CHAT_LOCK.read_text(encoding="utf-8"))
    packages: dict[str, dict] = {}
    for package in lock.get("package", []):
        name = _canonical(package["name"])
        hashes = set()
        sdist = package.get("sdist")
        if isinstance(sdist, dict):
            hashes.update(LOCK_HASH_RX.findall(str(sdist.get("hash", ""))))
        for wheel in package.get("wheels", []):
            hashes.update(LOCK_HASH_RX.findall(str(wheel.get("hash", ""))))
        packages[name] = {
            "version": package["version"],
            "dependencies": {
                _canonical(dep["name"])
                for dep in package.get("dependencies", [])
                if isinstance(dep, dict) and "name" in dep
            },
            "hashes": hashes,
        }

    closure: set[str] = set()
    pending = sorted(roots)
    while pending:
        name = pending.pop()
        if name in closure or name not in packages:
            continue
        closure.add(name)
        pending.extend(sorted(packages[name]["dependencies"] - closure))
    return packages, closure


def _pins() -> dict[str, dict]:
    pins: dict[str, dict] = {}
    current: str | None = None
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        pin = PIN_RX.match(line)
        if pin:
            current = _canonical(pin.group(1))
            pins[current] = {
                "version": pin.group(2),
                "hashes": set(HASH_RX.findall(line)),
            }
        elif current and line.startswith((" ", "\t")):
            pins[current]["hashes"].update(HASH_RX.findall(line))
    return pins


class DocumentsExtraClosure(unittest.TestCase):
    def test_documents_extra_roots_are_declared_and_locked(self):
        packages, closure = _requirement_closure()
        self.assertIn("openpyxl", closure)
        self.assertIn("et-xmlfile", closure)
        for name in closure:
            self.assertIn(name, packages, name)

    def test_every_closure_package_is_pinned_in_chat_requirements(self):
        _packages, closure = _requirement_closure()
        pins = _pins()
        missing = sorted(closure - set(pins))
        self.assertEqual(missing, [], "COM2 Chat requirements.txt에서 빠진 패키지")

    def test_pins_match_the_chat_lock_version_and_hash(self):
        packages, closure = _requirement_closure()
        pins = _pins()
        for name in sorted(closure):
            with self.subTest(package=name):
                self.assertEqual(pins[name]["version"], packages[name]["version"])
                self.assertTrue(
                    pins[name]["hashes"] & packages[name]["hashes"],
                    f"{name}: requirements hash does not match uv.lock",
                )

    def test_xlsx_dependency_pair_stays_together(self):
        # openpyxl이 XLSX를 읽을 때 et-xmlfile을 import한다. 하나만 빠져도
        # 컴2 Chat의 유틸 Excel 열기가 422로 되돌아간다(#8052).
        pins = _pins()
        self.assertIn("openpyxl", pins)
        self.assertIn("et-xmlfile", pins)
        self.assertEqual(pins["openpyxl"]["version"], "3.1.5")
        self.assertEqual(pins["et-xmlfile"]["version"], "2.0.0")


class PageRenderRequirement(unittest.TestCase):
    """#7955: the compare-view renderer is declared in all three places."""

    def test_pypdfium2_is_declared_locked_and_pinned(self):
        chat_project = ROOT / "apps" / "padiem-chat" / "pyproject.toml"
        project = tomllib.loads(chat_project.read_bytes().decode("utf-8"))
        extras = project["project"]["optional-dependencies"]
        declared = extras.get("dev", []) + extras.get("page-render", [])
        self.assertTrue(
            any(r.strip() == "pypdfium2==5.13.0" for r in declared),
            "chat pyproject must declare the pinned renderer",
        )

        lock = tomllib.loads(CHAT_LOCK.read_bytes().decode("utf-8"))
        package = next((p for p in lock["package"] if p["name"] == "pypdfium2"), None)
        self.assertIsNotNone(package, "uv.lock must carry the renderer")
        self.assertEqual(package["version"], "5.13.0")

        pins = _pins()
        self.assertIn("pypdfium2", pins)
        self.assertEqual(pins["pypdfium2"]["version"], package["version"])
        lock_hashes = set()
        sdist = package.get("sdist")
        if isinstance(sdist, dict):
            lock_hashes.update(LOCK_HASH_RX.findall(str(sdist.get("hash", ""))))
        for wheel in package.get("wheels", []):
            lock_hashes.update(LOCK_HASH_RX.findall(str(wheel.get("hash", ""))))
        self.assertTrue(pins["pypdfium2"]["hashes"] & lock_hashes)


if __name__ == "__main__":
    unittest.main()
