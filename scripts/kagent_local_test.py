"""#3108: the one canonical local KAgent test command.

    python scripts/kagent_local_test.py

This is the supported way to run the KAgent suite locally. It exists because
the obvious command is not trustworthy on a developer machine:

    python -m unittest discover -s apps/korean-ai-code-agent/tests

That runs against whatever ``kagent`` the interpreter happens to find first,
which on a machine carrying editable installs is frequently *another checkout*.
The suite then passes, and the pass proves nothing about the code in the
directory you are standing in.

What this command guarantees, in order:

1. **Isolation.** A dedicated virtual environment is created for this checkout
   and the interpreter that runs the tests is that environment's. The caller's
   interpreter, ``PYTHONPATH`` and ``VIRTUAL_ENV`` are not inherited, so a stale
   global ``.pth`` cannot answer an import.

2. **Siblings from this checkout, live.** ``padiem-ai-core``,
   ``padiem-control-plane`` and ``padiem-ai-engine-client`` are installed
   EDITABLE from the paths inside this checkout, which is exactly what
   ``.github/workflows/validate-b54-kagent.yml`` does. Their imports therefore
   keep resolving to the source trees, so editing a sibling is visible to the
   next run.

   Editable is load-bearing, not a convenience. An earlier revision installed
   them non-editable, which COPIES the sources into ``site-packages`` at install
   time. Editing a sibling file then left the copy stale while the environment
   fingerprint -- which covers ``pyproject.toml`` but not source -- stayed
   unchanged, so the stale copy ran behind a green result. Same defect as above,
   different mask.

3. **KAgent is never installed.** It runs from ``src`` on ``PYTHONPATH``.
   Installing it would make the parser-isolation contract vacuous: that contract
   is proved by a child process failing to import when its import root is
   emptied, and an editable ``.pth`` makes the import succeed regardless of
   ``PYTHONPATH``.

4. **Origins are proved, then the tests run.** The verifier resolves all four
   modules and refuses to continue if any resolved outside this checkout. The
   check runs *before* the suite, so a foreign import is a refusal rather than a
   confusing collection error three minutes in.

Ordering matters: installing first and verifying after would already have let a
global install win the import, because ``site`` processes ``.pth`` files at
interpreter start, before any code in this repository runs.

The environment is cached between runs and reused when its inputs have not
changed. Pass ``--recreate`` to rebuild it. No Docker is used or required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_MARKER_FILES: tuple[str, ...] = (
    ".git",
    "apps/korean-ai-code-agent/pyproject.toml",
    "packages/padiem-ai-core/pyproject.toml",
    "packages/padiem-control-plane/pyproject.toml",
    "apps/padiem-ai-engine/clients/python/pyproject.toml",
)

#: Sibling distributions the KAgent suite composes, installed from this checkout.
#:
#: Paths are relative to the repository root. They are deliberately spelled out
#: rather than discovered, so that adding a package to the monorepo cannot
#: silently widen what a local test run installs.
#:
#: These are installed EDITABLE (``-e``), exactly as
#: ``.github/workflows/validate-b54-kagent.yml`` installs them. That is not a
#: style preference. A non-editable install COPIES the sources into
#: ``site-packages`` at install time, so editing a sibling file afterwards
#: leaves the copy stale while the fingerprint -- which covers
#: ``pyproject.toml`` but not source -- stays unchanged and the environment is
#: reused. The result is a green run against code that is no longer in the tree:
#: the same defect #3108 exists to prevent, wearing a different mask.
#:
#: Editable is safe for the siblings precisely because KAgent is not editable.
#: The parser-isolation contract only requires that ``kagent`` itself be absent
#: from ``site`` processing; a sibling ``.pth`` pointing back into this checkout
#: is what CI already relies on.
SIBLING_DISTRIBUTIONS: tuple[str, ...] = (
    "packages/padiem-ai-core[tools,documents,render,tables,authoring]",
    "packages/padiem-control-plane",
    "apps/padiem-ai-engine/clients/python",
)

#: Third-party test runtime. Mirrors the canonical CI invocation.
#:
#: ``Pillow`` is deliberately absent from this list. CI installs one exact
#: approved native wheel and proves its provenance before use
#: (``PILLOW_12_3_0_NATIVE_WHEEL_PROVENANCE_3016.md``). A local run may exercise
#: whatever Pillow the platform resolves, so the image tests are not part of the
#: canonical local contract and Pillow is not pinned here. Tests that need it
#: skip; that is the documented behaviour, not a silent weakening.
TEST_REQUIREMENTS: tuple[str, ...] = ("pytest>=8,<10",)

DEFAULT_ENVIRONMENT_DIRECTORY = ".kagent-local-test-env"


def repository_root() -> Path:
    """The checkout root, from this file's own location.

    ``scripts/`` is one level below the root, so no filesystem search is needed
    and the result is correct from a linked worktree as well as a plain clone.
    """

    return Path(__file__).resolve().parents[1]


def _fail(message: str) -> int:
    print(f"kagent_local_test: {message}", file=sys.stderr)
    return 1


def environment_directory(root: Path, override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    return root / DEFAULT_ENVIRONMENT_DIRECTORY


def environment_fingerprint(root: Path) -> str:
    """A hash of every input that can change what the environment contains.

    Covers the repository marker files, every sibling ``pyproject.toml``, and
    this script. A change to any of them rebuilds the environment; an unrelated
    edit does not. The stamp is advisory -- a rebuild is always safe -- but it
    keeps the common case fast without ever letting a stale environment be
    silently reused across a dependency change.
    """

    digest = hashlib.sha256()
    digest.update(b"kagent-local-test-env-v1\n")

    paths: list[Path] = [root / relative for relative in REPOSITORY_MARKER_FILES]
    paths.append(Path(__file__).resolve())
    for sibling in SIBLING_DISTRIBUTIONS:
        base = sibling.split("[", 1)[0]
        paths.append(root / base / "pyproject.toml")
    paths.append(root / "apps/korean-ai-code-agent/src/kagent/dev_environment.py")

    for path in sorted(set(paths)):
        digest.update(str(path).encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            # A missing marker means the checkout is not what it claims to be.
            # Recording the absence still changes the fingerprint, so the next
            # run rebuilds and the verifier fails closed on the real problem.
            digest.update(b"<absent>")

    return digest.hexdigest()


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stream: bool = True,
) -> int:
    if stream:
        print(f"\n$ {' '.join(command)}", flush=True)
        return subprocess.call(command, cwd=str(cwd), env=env)

    completed = subprocess.run(
        command, cwd=str(cwd), env=env, capture_output=True, text=True
    )
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.returncode


def _child_environment(root: Path, environment: Path) -> dict[str, str]:
    """A minimal environment for the isolated interpreter.

    Everything the caller's process carried is dropped except what an
    interpreter needs to start on Windows (``SystemRoot`` and friends) and
    nothing that can influence import resolution:

    * ``PYTHONPATH`` is **replaced**, not extended, with this checkout's roots.
    * ``PYTHONNOUSERSITE`` is set so the per-user site directory is skipped. A
      user site ``.pth`` is one of the ways a foreign checkout wins an import.
    * ``PYTHONDONTWRITEBYTECODE`` keeps the environment directory from
      accumulating caches next to the source tree.

    ``PADIEM_*`` variables are intentionally not forwarded. This is a test
    environment, and a live-service flag inherited from a developer's shell
    should not be able to change what the suite exercises.
    """

    child = dict(os.environ)
    for name in list(child):
        if name.startswith("PADIEM_"):
            child.pop(name)

    child["VIRTUAL_ENV"] = str(environment)
    child.pop("PYTHONHOME", None)
    child["PYTHONNOUSERSITE"] = "1"
    child["PYTHONDONTWRITEBYTECODE"] = "1"
    child["PYTHONIOENCODING"] = "utf-8"
    child["PYTHONUTF8"] = "1"

    # Published so the freshness tests can find the same environment this
    # command built, including when it was relocated with --environment-dir.
    # Without it they would look only at the default location, skip, and the
    # stale-copy contract would go unverified precisely when a developer
    # relocated the environment.
    child["KAGENT_LOCAL_TEST_ENV"] = str(environment)

    # The only import root the test process is given.
    #
    # kagent comes from src and is never installed. The siblings are NOT listed
    # here: they resolve through the editable installs, which point back at this
    # checkout's source trees. That is the whole point of installing them
    # editable -- an edit to a sibling file is visible to the very next run, with
    # no rebuild and no fingerprint involvement.
    #
    # Naming a sibling here as well would be harmless today but is exactly the
    # shape that hides a stale install: a path that looks authoritative while the
    # real resolution happens somewhere else.
    child["PYTHONPATH"] = str(root / "apps/korean-ai-code-agent/src")

    return child


def _interpreter(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def build_environment(root: Path, environment: Path, recreate: bool) -> tuple[int, dict[str, str]]:
    """Create the virtual environment and install the sibling distributions."""

    if recreate and environment.exists():
        print(f"kagent_local_test: recreating {environment}", flush=True)
        # shutil rather than subprocess rm: the tree is inside the repository
        # and is a build artifact of this command, not a source directory.
        import shutil

        shutil.rmtree(environment)

    interpreter = _interpreter(environment)

    if not interpreter.exists():
        print(
            f"kagent_local_test: creating isolated environment at {environment}",
            flush=True,
        )
        code = _run(
            [sys.executable, "-m", "venv", str(environment)],
            cwd=root,
            env=dict(os.environ),
        )
        if code != 0:
            return code, {}

    child = _child_environment(root, environment)

    # Siblings go in editable, mirroring the canonical CI installation. A copied
    # install would let an edit to a sibling file leave a stale copy running
    # behind an unchanged fingerprint.
    targets = [
        *(f"-e{target}" for target in SIBLING_DISTRIBUTIONS),
        *TEST_REQUIREMENTS,
    ]
    command = [
        str(interpreter),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        *targets,
    ]
    code = _run(command, cwd=root, env=child)
    return code, child


def verify(child: dict[str, str], root: Path) -> int:
    """Prove the import origins before the suite runs."""

    verifier = (
        "import json,sys;"
        "from kagent.dev_environment import verify_import_origins;"
        "check=verify_import_origins();"
        "print(json.dumps(check.as_dict(), indent=2, sort_keys=True))"
    )
    code = _run(
        [str(_interpreter(Path(child["VIRTUAL_ENV"]))), "-c", verifier],
        cwd=root,
        env=child,
    )
    if code == 0:
        print("IMPORT_ORIGIN_CHECK=PASS", flush=True)
    else:
        print("IMPORT_ORIGIN_CHECK=FAIL", file=sys.stderr, flush=True)
    return code


def run_tests(child: dict[str, str], root: Path, extra: list[str]) -> int:
    application = root / "apps/korean-ai-code-agent"
    command = [
        str(_interpreter(Path(child["VIRTUAL_ENV"]))),
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-v",
        *extra,
    ]
    return _run(command, cwd=application, env=child)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kagent_local_test",
        description=(
            "Run the KAgent suite against this checkout in an isolated "
            "environment, proving import origins first."
        ),
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="rebuild the isolated environment even if it already exists",
    )
    parser.add_argument(
        "--environment-dir",
        default=None,
        help=f"override the environment location (default: ./{DEFAULT_ENVIRONMENT_DIRECTORY})",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="build and verify the environment, but do not run the suite",
    )
    parser.add_argument(
        "unittest_args",
        nargs="*",
        help="extra arguments forwarded to unittest discover",
    )
    options = parser.parse_args(argv)

    root = repository_root()
    if not all((root / marker).exists() for marker in REPOSITORY_MARKER_FILES):
        return _fail(
            f"{root} does not look like a Padiem Claw checkout; "
            f"expected markers {list(REPOSITORY_MARKER_FILES)}"
        )

    environment = environment_directory(root, options.environment_dir)
    fingerprint = environment_fingerprint(root)
    stamp = environment / ".padiem-kagent-env-stamp"
    current = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else ""

    if current != fingerprint:
        if current:
            print(
                "kagent_local_test: environment inputs changed, rebuilding",
                flush=True,
            )
        code, child = build_environment(root, environment, recreate=options.recreate)
        if code != 0:
            return _fail("environment build failed")
        environment.mkdir(parents=True, exist_ok=True)
        stamp.write_text(fingerprint, encoding="utf-8")
    else:
        print(
            f"kagent_local_test: reusing isolated environment at {environment}",
            flush=True,
        )
        child = _child_environment(root, environment)

    code = verify(child, root)
    if code != 0:
        return _fail(
            "import origin verification failed; the suite was not run. "
            "See the message above for which module resolved outside this checkout."
        )

    if options.verify_only:
        print("VERIFY_ONLY=YES")
        return 0

    return run_tests(child, root, options.unittest_args)


if __name__ == "__main__":
    raise SystemExit(main())
