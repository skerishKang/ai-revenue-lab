"""#3652 frozen-source pin / checkout-byte attribute contract guard.

The Engine canaries hash working-copy files against ``PINNED_SHA256``. Those hashes only hold across
a checkout if Git materializes each pinned file with exactly the tracked bytes, which on Windows
requires an autocrlf-proof attribute in ``.gitattributes`` (#3648). Pins and attributes live in
different files, so nothing stopped them from driving apart: a new pin with no matching rule passes
on ``ubuntu-latest`` and fails only on a Windows checkout.

This guard closes that coupling statically and platform-independently.

    collect -> every module-level ``PINNED_SHA256`` target in the Engine test tree, resolved from
               source rather than copied into a list here
    check   -> the effective checkout attribute of each target is autocrlf-proof, and the tracked
               blob is CR-free
    fail    -> any target without such a policy, any malformed pin, any unresolvable expression

It verifies *policy*, not platform behaviour, so it is meaningful on a Linux runner where
``core.autocrlf`` is already off, and it accepts any rule shape that yields byte-identical
materialization (``text eol=lf``, or the ``binary``/``-text`` family) from any ancestor directory.
It never reads the canaries' hashing code, so the raw-byte semantics proven in #3648 stay as they
are.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable


REPO = Path(__file__).resolve().parents[2]
PIN_DICT = "PINNED_SHA256"
DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class PinnedSource:
    module: str
    key: str
    relative_path: str
    digest: str


@dataclass(frozen=True)
class CheckoutPolicy:
    """The effective Git answer for one tracked path."""

    tracked: bool
    text: str
    eol: str
    cr_in_blob: bool


class UnresolvablePinExpression(Exception):
    """A pin key this guard cannot prove a repository path for.

    Raised instead of skipped: dropping a target silently would let exactly the pin this guard was
    written to catch land unprotected.
    """


# --------------------------------------------------------------------------- #
# collection
# --------------------------------------------------------------------------- #


def _relative_parts(root: Path, path: Path) -> tuple[str, ...]:
    return tuple(PurePosixPath(Path(path).relative_to(root).as_posix()).parts)


def _ascend(parts: tuple[str, ...], levels: int) -> tuple[str, ...]:
    """Mirror ``Path(...).parents[levels]``, clipped at the repository root."""

    keep = len(parts) - 1 - levels
    return parts[:keep] if keep > 0 else ()


class _Resolver:
    """Evaluates the small path algebra this repository uses for module-level anchors.

    Supported, recursively: ``Path(__file__)``, ``.resolve()``, ``.parent``, ``.parents[N]``,
    ``<value> / "segment"``, a previously defined ``<Name>``, and a ``"a/b"`` literal taken relative
    to the repository root. Anything else raises, because an expression that resolved to nothing
    would make the guard blind to the pin it exists to check.
    """

    def __init__(self, module: Path, root: Path) -> None:
        self._file = _relative_parts(root, module)
        self._symbols: dict[str, tuple[str, ...]] = {}

    def define(self, name: str, parts: tuple[str, ...]) -> None:
        self._symbols[name] = parts

    def evaluate(self, node: ast.expr) -> tuple[str, ...]:
        if isinstance(node, ast.Name):
            if node.id in self._symbols:
                return self._symbols[node.id]
            raise UnresolvablePinExpression(f"unknown anchor {node.id!r}")

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "Path" and len(node.args) == 1:
                arg = node.args[0]
                if isinstance(arg, ast.Name) and arg.id == "__file__":
                    return self._file
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    return self._from_literal(arg.value)
            # `X.resolve()` / `X.absolute()` are no-ops for a path already held relative to the root.
            if isinstance(func, ast.Attribute) and func.attr in ("resolve", "absolute") and not node.args:
                return self.evaluate(func.value)
            raise UnresolvablePinExpression(
                "only Path(__file__), Path('a/b'), X.resolve() and X.absolute() calls resolve"
            )

        if isinstance(node, ast.Attribute):
            if node.attr == "resolve":
                return self.evaluate(node.value)
            if node.attr == "parent":
                return self.evaluate(node.value)[:-1]
            raise UnresolvablePinExpression(f"unsupported attribute {node.attr!r}")

        if isinstance(node, ast.Subscript):
            inner = node.value
            if isinstance(inner, ast.Attribute) and inner.attr == "parents":
                parts = self.evaluate(inner.value)
                index = node.slice
                if isinstance(index, ast.Constant) and isinstance(index.value, int):
                    return _ascend(parts, index.value)
            raise UnresolvablePinExpression("only .parents[<int>] subscripts resolve")

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return self.evaluate(node.left) + self._segment(node.right)

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return self._from_literal(node.value)

        raise UnresolvablePinExpression(f"unsupported expression {type(node).__name__}")

    def _segment(self, node: ast.expr) -> tuple[str, ...]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in ("", "."):
                return ()
            return tuple(PurePosixPath(node.value).parts)
        raise UnresolvablePinExpression("path segments must be string literals")

    def _from_literal(self, value: str) -> tuple[str, ...]:
        if "/" not in value:
            raise UnresolvablePinExpression(
                f"bare literal {value!r} is ambiguous; pin keys must be anchored expressions"
            )
        return tuple(PurePosixPath(value).parts)


def collect_module_pins(module: Path, root: Path) -> list[PinnedSource]:
    """Every ``PINNED_SHA256`` target defined at module level in one file."""

    # utf-8-sig: some Engine test modules carry a leading BOM, which CPython accepts and plain
    # utf-8 reading would hand to the parser as U+FEFF.
    tree = ast.parse(Path(module).read_text(encoding="utf-8-sig"), filename=str(module))
    resolver = _Resolver(Path(module), root)
    pins: list[PinnedSource] = []

    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue

        if target.id == PIN_DICT:
            if not isinstance(node.value, ast.Dict):
                raise UnresolvablePinExpression(f"{module.name}: {PIN_DICT} is not a dict literal")
            for key, value in zip(node.value.keys, node.value.values):
                if key is None or value is None:
                    raise UnresolvablePinExpression(f"{module.name}: {PIN_DICT} has a spread entry")
                digest = value.value if isinstance(value, ast.Constant) else None
                pins.append(
                    PinnedSource(
                        module=Path(module).relative_to(root).as_posix(),
                        key=ast.unparse(key),
                        relative_path="/".join(resolver.evaluate(key)),
                        digest=digest if isinstance(digest, str) else "",
                    )
                )
            continue

        # Module-level anchors such as REPO_ROOT / CORE_PACKAGE / ENGINE_APP. A name that is not a
        # path is normal here, so an unresolvable anchor is simply not registered.
        try:
            resolver.define(target.id, resolver.evaluate(node.value))
        except UnresolvablePinExpression:
            continue

    return pins


def collect_pins(engine_tests_dir: Path, root: Path) -> list[PinnedSource]:
    """Every pinned target across the Engine test tree, de-duplicated by path."""

    found: dict[str, PinnedSource] = {}
    for module in sorted(Path(engine_tests_dir).glob("*.py")):
        for pin in collect_module_pins(module, root):
            found.setdefault(pin.relative_path, pin)
    return list(found.values())


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #


def git_policy(path: str, root: Path) -> CheckoutPolicy:
    """Ask Git what it will actually do to this path on checkout."""

    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", path],
        capture_output=True,
    ).returncode == 0
    if not tracked:
        return CheckoutPolicy(tracked=False, text="unspecified", eol="unspecified", cr_in_blob=False)

    proc = subprocess.run(
        ["git", "-C", str(root), "check-attr", "text", "eol", "--", path],
        capture_output=True,
        text=True,
        check=True,
    )
    attrs: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        _, _, remainder = line.partition(": ")
        name, _, value = remainder.partition(": ")
        attrs[name] = value.strip()

    blob = subprocess.run(
        ["git", "-C", str(root), "cat-file", "blob", f"HEAD:{path}"],
        capture_output=True,
        check=True,
    ).stdout

    return CheckoutPolicy(
        tracked=True,
        text=attrs.get("text", "unspecified"),
        eol=attrs.get("eol", "unspecified"),
        cr_in_blob=b"\r" in blob,
    )


def is_autocrlf_proof(policy: CheckoutPolicy) -> bool:
    """Whether materialization is byte-identical to the blob whatever core.autocrlf says."""

    if not policy.tracked:
        return False
    if policy.text == "unset":  # the `binary` macro, or an explicit `-text`
        return True
    return (policy.text, policy.eol) == ("set", "lf")


def find_offenders(pins: list[PinnedSource], policy_of: Callable[[str], CheckoutPolicy]) -> list[str]:
    offenders: list[str] = []
    for pin in pins:
        if not DIGEST.match(pin.digest):
            offenders.append(f"{pin.relative_path}: pin digest is not 64-hex ({pin.module})")
            continue

        policy = policy_of(pin.relative_path)
        if not policy.tracked:
            offenders.append(f"{pin.relative_path}: pinned target is not tracked by Git")
            continue
        if not is_autocrlf_proof(policy):
            offenders.append(
                f"{pin.relative_path}: checkout is not autocrlf-proof "
                f"(text={policy.text} eol={policy.eol}); give it `text eol=lf` or `-text`/`binary` "
                f"in .gitattributes ({pin.module})"
            )
            continue
        if policy.cr_in_blob:
            offenders.append(
                f"{pin.relative_path}: tracked blob contains CR, so no checkout rule can make the "
                "pinned digest describe the bytes"
            )
    return offenders


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="frozen-source pin / attribute contract guard")
    parser.add_argument("--root", type=Path, default=REPO, help="repository root to audit")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    engine_tests = root / "apps" / "padiem-ai-engine" / "tests"
    if not engine_tests.is_dir():
        print(f"FROZEN_SOURCE_PIN_GUARD=NO_ENGINE_TESTS ({engine_tests})")
        return 1

    pins = collect_pins(engine_tests, root)
    offenders = find_offenders(pins, lambda path: git_policy(path, root))

    for pin in sorted(pins, key=lambda item: item.relative_path):
        # Match on the full path prefix: one pinned path is routinely a substring of another.
        flagged = any(line.startswith(pin.relative_path) for line in offenders)
        print(f"  {'OFFENDER' if flagged else 'OK':9s} {pin.relative_path}")

    print(f"FROZEN_SOURCE_PINS_COLLECTED={len(pins)}")
    print(f"FROZEN_SOURCE_PIN_GUARD={'FAILED' if offenders else 'PASSED'}")
    for line in offenders:
        print(f"  VIOLATION {line}")
    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main())
