"""#3108: prove a local KAgent test run imports the checkout under review.

The failure this module exists to prevent is not a crash. It is a *green* test
run that proves nothing, because a stale global editable install silently
answered the imports:

    running tests from checkout A
    -> a .pth or editable finder from checkout B resolves ``kagent``
    -> tests pass against code nobody in this checkout reviewed
    -> the local result does not prove the reviewed source

Nothing here repairs the machine. Removing a stale ``.pth`` is operator-owned
and machine-specific, and encoding a host path into repository source would
reintroduce the very coupling this module removes. The repository-side fix is
to make the canonical local path *prove* where its imports came from, and to
refuse to run when they came from anywhere else.

Two rules make the proof meaningful:

1. ``kagent`` itself is never installed. It runs from ``src`` on
   ``PYTHONPATH`` only. An editable ``kagent`` would put the tree on ``sys.path``
   unconditionally, which would invalidate the parser-isolation contract that
   :mod:`kagent.document_parser_isolation` depends on -- that contract is proved
   by a child failing to import when its import root is emptied
   (``test_real_child_without_the_module_fails_closed``). A ``.pth`` entry makes
   the child importable no matter what ``PYTHONPATH`` says, so the test would
   pass for the wrong reason.

2. The sibling packages *are* installed, because they are ordinary
   distributions. But an editable install of a sibling records an absolute path,
   and that path is checked against the repository root before any test runs.

The check is on resolved module ``__file__`` values, not on ``sys.path`` strings.
A path entry can look current while a ``.pth`` earlier in the order has already
won; only the resolved origin tells the truth.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ImportOrigin",
    "OriginCheck",
    "OriginError",
    "REPO_MODULES",
    "describe_import_origins",
    "repository_root",
    "verify_import_origins",
]


#: Modules whose origin must resolve inside the checkout under review.
#:
#: ``kagent`` is the product under test. The other three are the sibling
#: distributions its suite composes. All four are checked: a suite that proves
#: ``kagent`` but silently consumed a foreign ``padiem_ai_core`` is exactly the
#: ambiguity this module is closing.
REPO_MODULES: tuple[str, ...] = (
    "kagent",
    "padiem_ai_core",
    "padiem_control_plane",
    "padiem_ai_engine_client",
)

#: Modules that must resolve from the checkout ``src`` tree, never from site.
#:
#: KAgent is deliberately excluded from any install. See the module docstring.
_SRC_ONLY_MODULES: tuple[str, ...] = ("kagent",)


class OriginError(RuntimeError):
    """A required module did not resolve inside the checkout under review.

    Deliberately a distinct type from ``ImportError``: a missing module and a
    module found in the wrong place are different failures and must not collapse
    into one, or a broken environment becomes indistinguishable from a foreign
    one.
    """


@dataclass(frozen=True)
class ImportOrigin:
    """Where one module actually came from."""

    module: str
    origin: str | None
    inside_repository: bool
    required_src_only: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "module": self.module,
            "origin": self.origin,
            "inside_repository": self.inside_repository,
            "required_src_only": self.required_src_only,
        }


@dataclass(frozen=True)
class OriginCheck:
    """The full verdict for a set of modules."""

    repository_root: str
    origins: tuple[ImportOrigin, ...]

    @property
    def ok(self) -> bool:
        return all(
            origin.origin is not None and origin.inside_repository
            for origin in self.origins
        )

    def foreign(self) -> tuple[ImportOrigin, ...]:
        return tuple(
            origin
            for origin in self.origins
            if origin.origin is None or not origin.inside_repository
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "repository_root": self.repository_root,
            "ok": self.ok,
            "origins": [origin.as_dict() for origin in self.origins],
        }


#: This module's own file, resolved once at import.
#:
#: ``__file__`` is not always available. Running a module's source through
#: ``python -c`` gives ``__name__`` but no ``__file__``, and a naive
#: ``Path(__file__)`` then raises ``NameError`` -- so the verifier would crash
#: with a traceback instead of failing closed, which is the one behaviour this
#: module must never have. The launcher needs to be able to run this file by
#: path in exactly the contaminated environments where importing ``kagent``
#: normally fails, so the fallback below is a real requirement, not a nicety.
_OWN_FILE: Path = (
    Path(__file__).resolve()
    if "__file__" in globals()
    else Path.cwd() / "kagent" / "dev_environment.py"
)

#: Directory three levels above this file: ``<repo>/apps/korean-ai-code-agent/src``
#: is two, so three lands on the application root that holds ``src``.
_DEFAULT_ANCESTOR_COUNT = 3


def repository_root(start: Path | str | None = None) -> Path:
    """The checkout root, found by walking up to the directory holding ``.git``.

    ``.git`` is a file in a linked worktree and a directory in a plain clone.
    Both are accepted, because CLAW4 lanes run from worktrees and a solution that
    only works in a plain clone would not have been testable here.

    Falls back to a fixed ancestor of this file when no ``.git`` is found, so the
    verifier still has a defined root rather than guessing the filesystem root.

    Two input types are accepted and both are required in practice:

    * ``str`` -- the root routinely arrives as a ``python -c`` command-line
      argument. Calling ``.parents`` on a str raises ``AttributeError``, so a
      verifier that did this would crash instead of failing closed.
    * ``None`` -- the default, meaning "locate my own checkout". This path must
      tolerate a missing ``__file__``; see ``_OWN_FILE``.
    """

    if start is None:
        start = _OWN_FILE
    elif not isinstance(start, Path):
        start = Path(start)

    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate

    return _OWN_FILE.parents[_DEFAULT_ANCESTOR_COUNT]


def _is_inside(path: Path, root: Path) -> bool:
    """True when ``path`` is ``root`` or below it.

    Compared as resolved paths so a symlinked or differently-cased path cannot
    produce a false negative, and with a separator boundary so a sibling
    directory sharing a name prefix (``padiem-ai-core-old``) cannot pass as
    ``padiem-ai-core``.
    """

    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _resolve_module(module: str) -> str | None:
    """The file a module resolved to, or ``None`` when it is not importable.

    ``importlib.import_module`` is used rather than ``importlib.util.find_spec``
    because the reported ``origin`` must be the *parent package's* location. For
    a namespace or plain package, ``find_spec(...).origin`` can be ``None`` even
    when the module imported fine, which would turn a healthy environment into a
    false failure.
    """

    try:
        imported = importlib.import_module(module)
    except ImportError:
        return None

    origin = getattr(imported, "__file__", None)
    if origin is not None:
        return str(Path(origin).resolve())

    # Namespace packages expose ``__path__`` instead of ``__file__``.
    paths = getattr(imported, "__path__", None)
    if paths:
        return str(Path(list(paths)[0]).resolve())

    return None


def describe_import_origins(
    modules: tuple[str, ...] = REPO_MODULES,
    root: Path | None = None,
) -> OriginCheck:
    """Resolve each module and record whether it came from this checkout.

    This never raises for a foreign origin. Reporting and failing are separate
    concerns: a caller that wants a report (a developer reading the output, a
    test asserting the verifier detects a foreign tree) needs the data even when
    the verdict is bad.
    """

    repository = repository_root(root)
    origins: list[ImportOrigin] = []

    for module in modules:
        origin = _resolve_module(module)
        if origin is None:
            origins.append(
                ImportOrigin(
                    module=module,
                    origin=None,
                    inside_repository=False,
                    required_src_only=module in _SRC_ONLY_MODULES,
                )
            )
            continue

        origins.append(
            ImportOrigin(
                module=module,
                origin=origin,
                inside_repository=_is_inside(Path(origin), repository),
                required_src_only=module in _SRC_ONLY_MODULES,
            )
        )

    return OriginCheck(repository_root=str(repository), origins=tuple(origins))


def _format_failure(check: OriginCheck) -> str:
    lines = [
        "kagent local test environment refused to run: import origins are not "
        "confined to the checkout under review.",
        f"repository_root={check.repository_root}",
    ]

    for origin in check.foreign():
        if origin.origin is None:
            detail = "not importable in this environment"
        else:
            detail = f"resolved to {origin.origin}"
        lines.append(f"  {origin.module}: {detail}")

    lines.append(
        "A stale global editable install or an inherited PYTHONPATH is answering "
        "these imports, so a test run here would not prove the reviewed source."
    )
    lines.append(
        "Remove the stale editable install on this machine (operator-owned; the "
        "repository does not and must not encode machine-specific paths), or run "
        "the canonical command below, which builds an isolated environment from "
        "this checkout."
    )
    return "\n".join(lines)


def verify_import_origins(
    modules: tuple[str, ...] = REPO_MODULES,
    root: Path | None = None,
) -> OriginCheck:
    """Raise :class:`OriginError` unless every module resolved in-checkout.

    Fails closed. A missing module is treated exactly like a foreign one, so a
    partially built environment cannot produce a green run.
    """

    check = describe_import_origins(modules, root=root)
    if not check.ok:
        raise OriginError(_format_failure(check))
    return check


def _main() -> int:
    """Print the origin table and exit non-zero on any foreign module."""

    check = describe_import_origins()
    print(json.dumps(check.as_dict(), indent=2, sort_keys=True))
    if check.ok:
        print("IMPORT_ORIGIN_CHECK=PASS")
        return 0

    print(_format_failure(check), file=sys.stderr)
    print("IMPORT_ORIGIN_CHECK=FAIL", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(_main())
