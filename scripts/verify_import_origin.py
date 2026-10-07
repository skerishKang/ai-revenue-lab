"""#3658 prove that the packages under test came from this checkout.

One user-level Python interpreter is shared by every concurrent worktree, and an editable install
records the **absolute path of the worktree that installed it**. So a test run started inside
checkout A can import `padiem_ai_core` from checkout B. The failure that matters is not a crash --
it is a *green* run that proves nothing, because the code under test was never this checkout's code.

`docs/operations/MULTI_MACHINE_LOCAL_WORKTREE_POLICY.md` §8 already requires
`VERIFY_IMPORT_ORIGIN_BEFORE_TESTS=YES`, but states it as a manual snippet, and #3108's verifier is
owned by the KAgent lane. This is the repository-neutral form of the same check, so any lane can
run it before a suite and so a lane's own `conftest.py` can refuse to start.

Usage:

    python scripts/verify_import_origin.py
    python scripts/verify_import_origin.py --modules padiem_ai_core

Rules, and why:

* The origin is the **resolved module file**, not a `sys.path` entry. A path entry can look current
  while a `.pth` earlier in the order already won; only the resolved answer tells the truth.
* A module that is not importable is reported and skipped, not failed. A lane that does not use a
  sibling package must keep working. #3108's stricter four-module requirement belongs to that
  suite's composition, not to this one.
* Only repository-owned packages are in the default set. Third-party and stdlib imports are never
  constrained: they legitimately live in a site-packages directory outside the checkout.
* Nothing here repairs the machine. Deleting a stale `.pth` is operator-owned, and encoding a host
  path into repository source would reintroduce the coupling this check removes.

Deliberately not imported at runtime: `kagent/dev_environment.py`. That module is the KAgent lane's
authority and reaching into it from Core would create exactly the cross-lane collection dependency
that the #3625 guard exists to prevent. Agreement between the two verifiers is asserted by a test
instead, which is where such a coupling belongs.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

__all__ = [
    "DEFAULT_MODULES",
    "ImportOrigin",
    "OriginVerdict",
    "check_origins",
    "diagnostic",
    "main",
    "repository_root",
    "resolve_origin",
]


REPO = Path(__file__).resolve().parents[1]

#: Repository-owned packages that are installed editable from a checkout path.
#:
#: `kagent` is intentionally absent: it is never installed, and runs from `src` on PYTHONPATH under
#: #3108's own verifier. Listing it here would make every non-KAgent lane fail for a module it is
#: designed not to have.
DEFAULT_MODULES: tuple[str, ...] = (
    "padiem_ai_core",
    "padiem_control_plane",
    "padiem_ai_engine_client",
)


@dataclass(frozen=True)
class ImportOrigin:
    module: str
    origin: str | None
    inside_repository: bool
    note: str = ""

    @property
    def absent(self) -> bool:
        return self.origin is None


@dataclass(frozen=True)
class OriginVerdict:
    repository_root: str
    origins: tuple[ImportOrigin, ...]

    @property
    def foreign(self) -> tuple[ImportOrigin, ...]:
        return tuple(o for o in self.origins if o.origin is not None and not o.inside_repository)

    @property
    def broken(self) -> tuple[ImportOrigin, ...]:
        return tuple(o for o in self.origins if o.note)

    @property
    def ok(self) -> bool:
        return not self.foreign and not self.broken

    def summary(self) -> str:
        return " ".join(
            (
                f"IMPORT_ORIGIN_CHECK={'PASSED' if self.ok else 'FAILED'}",
                f"IMPORT_ORIGINS_CHECKED={len(self.origins)}",
                f"IMPORT_ORIGINS_FOREIGN={len(self.foreign)}",
                f"IMPORT_ORIGINS_ABSENT={sum(1 for o in self.origins if o.absent)}",
            )
        )


def repository_root(start: Path | str | None = None) -> Path:
    """The checkout root: the nearest ancestor holding `.git`.

    `.git` is a *file* in a linked worktree and a directory in a plain clone, and both are accepted:
    CLAW/COMP lanes run from worktrees, so a root finder that only matched a directory would be
    unusable exactly where the contamination happens.
    """

    base = Path(start) if start is not None else Path(__file__).resolve()
    for candidate in (base, *base.parents):
        if (candidate / ".git").exists():
            return candidate
    # Two levels above this file is scripts/.. == the repository, whatever .git looks like.
    return Path(__file__).resolve().parents[2]


def is_inside(path: Path | str, root: Path) -> bool:
    """True when `path` is `root` or below it, compared resolved and on a component boundary."""

    try:
        Path(path).resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def resolve_origin(module: str) -> tuple[str | None, str]:
    """Where `module` actually resolves, plus a note when it could not be answered.

    Importing rather than `find_spec` mirrors #3108: for a regular or namespace package
    `find_spec(...).origin` can be `None` even though the import succeeds, which would turn a
    healthy environment into a false failure.
    """

    try:
        imported = importlib.import_module(module)
    except ImportError:
        return None, ""
    except Exception as exc:  # a module that explodes on import is not a clean environment
        return None, f"import raised {type(exc).__name__}"

    origin = getattr(imported, "__file__", None)
    if origin:
        return str(Path(origin).resolve()), ""

    paths = getattr(imported, "__path__", None)
    if paths:
        first = next(iter(paths), None)
        if first:
            return str(Path(first).resolve()), ""

    return None, f"{module} imported but exposes neither __file__ nor __path__"


def check_origins(
    modules: Iterable[str] = DEFAULT_MODULES,
    root: Path | None = None,
    resolver: Callable[[str], tuple[str | None, str]] = resolve_origin,
) -> OriginVerdict:
    """Resolve every candidate and classify it. Never raises for a foreign origin."""

    repository = Path(root) if root is not None else repository_root()
    origins = []
    for module in modules:
        origin, note = resolver(module)
        origins.append(
            ImportOrigin(
                module=module,
                origin=origin,
                inside_repository=bool(origin) and is_inside(origin, repository),
                note=note,
            )
        )
    return OriginVerdict(repository_root=str(repository), origins=tuple(origins))


def diagnostic(verdict: OriginVerdict) -> list[str]:
    """Package name, expected checkout root, actual origin path. Nothing else.

    No sys.path dump, no environment values, no interpreter configuration: the three fields below
    are what an operator needs to find the stale install, and the rest risks printing a machine
    configuration that has no business reaching a log.
    """

    lines = [f"EXPECTED_CHECKOUT_ROOT={verdict.repository_root}"]
    for origin in verdict.origins:
        if origin.absent and not origin.note:
            lines.append(f"ABSENT  {origin.module} (not importable here; not a finding)")
        elif not origin.inside_repository:
            reason = origin.note or "resolves outside the checkout under test"
            lines.append(f"FOREIGN {origin.module} ACTUAL_ORIGIN={origin.origin or 'unresolvable'} {reason}")
    return lines


def main(argv: list[str] | None = None, writer=print) -> int:
    parser = argparse.ArgumentParser(description="prove local packages were imported from this checkout")
    parser.add_argument("--modules", nargs="*", default=list(DEFAULT_MODULES))
    parser.add_argument("--root", type=Path, default=None, help="expected checkout root")
    args = parser.parse_args(argv)

    root = args.root.expanduser().resolve() if args.root else repository_root()
    verdict = check_origins(args.modules, root)

    for line in diagnostic(verdict):
        writer(line)
    writer(verdict.summary())
    return 0 if verdict.ok else 1


if __name__ == "__main__":
    sys.exit(main())
