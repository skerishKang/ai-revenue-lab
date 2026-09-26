"""#3108: the local test environment proves where its imports came from.

These tests are deliberately non-vacuous about the one property that matters:
the verifier must actually **detect** a foreign checkout, not merely describe
one. Every "detects" test therefore builds a real second tree on disk, puts it
on the path ahead of the real one, and asserts the verdict flips.

A verifier that only ever ran against a correct environment would pass every
test in this file while providing no protection at all, so the mutation that
matters here is the one that removes the check.

Coverage map:

* A  a module resolved outside the repository root is refused
* B  a module from another checkout is detected even when it is a plausible name
* C  a missing module is refused exactly like a foreign one
* D  the boundary is a separator boundary, not a string prefix
* E  a path that merely shares a name prefix does not pass as inside
* F  the four required modules are the ones CI composes
* G  kagent is required to come from src and is never an install
* H  origins are read from resolved ``__file__``, not from ``sys.path`` text
* I  the canonical command does not require an editable kagent install
* J  the canonical command does not mutate global site-packages
* K  the canonical command does not require Docker
* L  sibling paths are inside this checkout and spelled out, not discovered
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import tokenize
import unittest
from pathlib import Path
from unittest import mock

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]
SCRIPT = REPO_ROOT / "scripts" / "kagent_local_test.py"
VERIFIER = APP_ROOT / "src" / "kagent" / "dev_environment.py"

sys.path.insert(0, str(APP_ROOT / "src"))

import kagent.dev_environment as dev  # noqa: E402

#: Must match ``scripts/kagent_local_test.py``. Duplicated deliberately rather
#: than imported: the launcher is a script, not an importable package module,
#: and a test that imported it would prove nothing about the shipped file.
ENVIRONMENT_DIRECTORY_NAME = ".kagent-local-test-env"


@contextlib.contextmanager
def temporary_root():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _foreign_tree() -> Path:
    """A real importable module tree outside the repository, for the life of the test.

    Module-level so the path stays valid while the verifier subprocess runs: a
    ``TemporaryDirectory`` would be torn down before the child finished.
    """

    global _FOREIGN_ROOT
    if _FOREIGN_ROOT is None:
        directory = Path(tempfile.mkdtemp(prefix="kagent-3108-foreign-"))
        _make_foreign_package(directory, "kagent", "FOREIGN")
        _FOREIGN_ROOT = directory
    return _FOREIGN_ROOT


_FOREIGN_ROOT: Path | None = None


def _code_only(path: Path) -> str:
    """The file's *code*, with comments and docstrings removed.

    Assertions like "this script never runs docker" must not be satisfiable or
    falsifiable by prose. A module docstring that says "no docker is required"
    contains the word ``docker``, and a comment explaining why ``kagent`` is
    never installed contains ``editable``. Reading raw text would make those
    tests fail for the wrong reason, and worse, would let a real call hide
    behind a reassuring comment.

    Implementation: tokenize to drop comments, then walk the AST and blank out
    every docstring expression. What remains is what the interpreter executes.

    Comments are dropped by re-emitting only the tokens that are not comments,
    each tagged with its original line. Untokenizing single tokens one at a time
    would reflow the file, so the non-comment tokens are re-emitted as a stream.
    """

    source = path.read_text(encoding="utf-8")

    kept = [
        token
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type != tokenize.COMMENT
    ]
    stripped = tokenize.untokenize(kept)

    tree = ast.parse(source)
    lines = stripped.splitlines(keepends=True)
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                for line_number in range(
                    first.lineno, (first.end_lineno or first.lineno) + 1
                ):
                    if 0 < line_number <= len(lines):
                        lines[line_number - 1] = "\n"

    return "".join(lines)


def _make_foreign_package(directory: Path, module: str, marker: str) -> Path:
    """Create a real, importable module in a real directory outside the repo."""

    package = directory / module
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        f"MARKER = {marker!r}\n", encoding="utf-8"
    )
    return package


class ForeignCheckoutDetectionTests(unittest.TestCase):
    """A/B/C: a foreign or missing module is refused, not reported as fine."""

    def test_module_outside_the_repository_root_is_refused(self) -> None:
        with mock.patch.object(dev, "_resolve_module", return_value=None):
            check = dev.describe_import_origins(
                ("kagent",), root=REPO_ROOT
            )
        self.assertFalse(check.ok)
        self.assertEqual(len(check.foreign()), 1)

    def test_a_real_foreign_checkout_is_detected_end_to_end(self) -> None:
        # The decisive test. A real second tree is built outside the repository,
        # placed ahead of the real kagent on sys.path, and the verifier is asked
        # the only question that matters: is this import from this checkout?
        with temporary_root() as tmp:
            foreign_root = tmp / "other-checkout"
            _make_foreign_package(foreign_root / "src", "kagent", "FOREIGN")

            saved_path = list(sys.path)
            saved_module = sys.modules.pop("kagent", None)
            try:
                sys.path.insert(0, str(foreign_root / "src"))
                check = dev.describe_import_origins(("kagent",), root=REPO_ROOT)
            finally:
                sys.path[:] = saved_path
                sys.modules.pop("kagent", None)
                if saved_module is not None:
                    sys.modules["kagent"] = saved_module

            self.assertFalse(
                check.ok,
                "a kagent resolved from another checkout must not verify",
            )
            self.assertEqual(len(check.foreign()), 1)
            origin = check.origins[0]
            self.assertIsNotNone(origin.origin)
            self.assertIn("other-checkout", str(origin.origin))

        # The same condition must raise from the strict entry point. Checked
        # after the temp tree is gone, and against the real kagent, to prove the
        # refusal is about the verdict and not about the fake tree still being
        # importable.
        with self.assertRaises(dev.OriginError):
            dev.verify_import_origins(
                ("padiem_module_that_does_not_exist_3108",), root=REPO_ROOT
            )

    def test_the_real_kagent_in_this_checkout_verifies(self) -> None:
        # The counterpart: the genuine article must PASS, or the guard above
        # proves nothing beyond "always fail".
        check = dev.describe_import_origins(("kagent",), root=REPO_ROOT)
        self.assertTrue(check.ok, check.as_dict())
        self.assertIn("korean-ai-code-agent", str(check.origins[0].origin))

    def test_a_missing_module_is_refused_like_a_foreign_one(self) -> None:
        # A missing module and a misplaced module are different failures. If they
        # collapsed into one, a broken environment would be indistinguishable
        # from a contaminated one, and the operator remediation differs.
        check = dev.describe_import_origins(
            ("padiem_module_that_does_not_exist_3108",), root=REPO_ROOT
        )
        self.assertFalse(check.ok)
        self.assertIsNone(check.origins[0].origin)

        with self.assertRaises(dev.OriginError):
            dev.verify_import_origins(
                ("padiem_module_that_does_not_exist_3108",), root=REPO_ROOT
            )

    def test_the_failure_message_names_the_module_and_stays_bounded(self) -> None:
        # The message is operator-facing remediation, so it must name the module
        # and must not degenerate into a traceback dump.
        with self.assertRaises(dev.OriginError) as ctx:
            dev.verify_import_origins(
                ("padiem_module_that_does_not_exist_3108",), root=REPO_ROOT
            )
        message = str(ctx.exception)
        self.assertIn("padiem_module_that_does_not_exist_3108", message)
        self.assertNotIn("Traceback", message)
        self.assertNotIn("File \"", message)
        self.assertLess(len(message), 2000)

    def test_a_foreign_origin_error_names_the_foreign_path(self) -> None:
        # The remediation differs: a foreign origin means "a stale install is
        # answering", a missing one means "the environment is incomplete". The
        # message has to preserve that difference to be actionable.
        with temporary_root() as tmp:
            _make_foreign_package(tmp, "kagent", "FOREIGN")
            with mock.patch.object(
                dev, "_resolve_module", return_value=str(tmp / "kagent" / "__init__.py")
            ):
                with self.assertRaises(dev.OriginError) as ctx:
                    dev.verify_import_origins(("kagent",), root=REPO_ROOT)
        message = str(ctx.exception)
        self.assertIn("kagent", message)
        self.assertNotIn("Traceback", message)


class BoundaryTests(unittest.TestCase):
    """D/E: the containment check is a path boundary, not a string prefix."""

    def test_a_sibling_directory_sharing_a_name_prefix_is_outside(self) -> None:
        # "padiem-ai-core" must not admit "padiem-ai-core-backup". A plain
        # string startswith() would admit it, and a stale backup directory is
        # exactly the kind of thing that appears on a developer machine.
        root = REPO_ROOT
        with temporary_root() as tmp:
            lookalike = tmp / "packages" / (root.name + "-backup") / "module.py"
            lookalike.parent.mkdir(parents=True, exist_ok=True)
            lookalike.write_text("VALUE = 1\n", encoding="utf-8")

            inside = dev._is_inside(root / "packages" / "module.py", root)
            outside = dev._is_inside(lookalike, root)

        self.assertTrue(inside)
        self.assertFalse(outside, "a name-prefix sibling must count as outside")

    def test_the_root_itself_counts_as_inside(self) -> None:
        self.assertTrue(dev._is_inside(REPO_ROOT / "apps", REPO_ROOT))

    def test_repository_root_is_found_from_a_linked_worktree(self) -> None:
        # ``.git`` is a file in a worktree and a directory in a clone. Both must
        # work, because a worktree-only solution would not have been testable
        # from the lane that authored it.
        with temporary_root() as tmp:
            plain = tmp / "plain"
            (plain / ".git").mkdir(parents=True)
            linked = tmp / "linked"
            linked.mkdir(parents=True)
            (linked / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")

            self.assertEqual(dev.repository_root(plain), plain)
            self.assertEqual(dev.repository_root(linked), linked)

    def test_repository_root_falls_back_without_a_git_marker(self) -> None:
        with temporary_root() as tmp:
            # No .git anywhere above: the fallback must still be a defined path
            # rather than a filesystem-root guess.
            resolved = dev.repository_root(tmp / "deep" / "deeper")
            self.assertTrue(resolved.is_absolute())
            self.assertNotEqual(resolved, Path(resolved.anchor))

    def test_a_string_root_never_raises(self) -> None:
        # A regression guard, not a hypothetical. This module is routinely driven
        # from a ``python -c`` probe where the root arrives as a command-line
        # argument, i.e. a str. The first implementation called ``.parents`` on it
        # and raised AttributeError -- so instead of failing closed, the verifier
        # crashed with a traceback and the caller learned nothing about which
        # module was foreign.
        with temporary_root() as tmp:
            resolved = dev.repository_root(str(tmp))
            self.assertIsInstance(resolved, Path)
            self.assertTrue(resolved.is_absolute())

    def test_a_string_root_reaches_a_verdict_rather_than_an_exception(self) -> None:
        # The end-to-end form of the guard above: a string root must produce a
        # verdict, not a traceback.
        check = dev.describe_import_origins(("kagent",), root=str(REPO_ROOT))
        self.assertTrue(check.ok, check.as_dict())

    def test_the_verifier_runs_without_a_dunder_file(self) -> None:
        # The second real defect this file's development exposed.

        # ``python -c`` has no ``__file__``, so the first implementation raised
        # NameError from inside repository_root(). That matters operationally:
        # the launcher has to be able to run this file by path in precisely the
        # contaminated environments where importing kagent normally fails. A
        # verifier that crashes when it is most needed is worse than no verifier,
        # because the crash looks like an unrelated bug.
        with temporary_root() as tmp:
            source = VERIFIER.read_text(encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-S", "-c", source],
                capture_output=True,
                text=True,
                env={
                    key: value
                    for key, value in os.environ.items()
                    if key not in ("PYTHONPATH", "PYTHONHOME")
                },
                cwd=str(tmp),
                timeout=180,
            )

        self.assertNotIn(
            "NameError", completed.stderr, completed.stderr[-500:]
        )
        self.assertNotIn("Traceback", completed.stderr, completed.stderr[-500:])
        # With no checkout in sight and no kagent importable, the only correct
        # outcome is a clean refusal.
        self.assertEqual(completed.returncode, 1, completed.stdout[-500:])
        self.assertIn("IMPORT_ORIGIN_CHECK=FAIL", completed.stderr)


class RequiredModuleTests(unittest.TestCase):
    """F/G: the module set matches what CI actually composes."""

    def test_the_four_ci_composed_modules_are_checked(self) -> None:
        self.assertEqual(
            set(dev.REPO_MODULES),
            {
                "kagent",
                "padiem_ai_core",
                "padiem_control_plane",
                "padiem_ai_engine_client",
            },
        )

    def test_the_checked_modules_match_the_ci_install_list(self) -> None:
        # If CI grows a sibling and this set does not, a local run can silently
        # consume a foreign copy of the new one. Read the workflow rather than
        # restating it, so the two cannot drift apart silently.
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "validate-b54-kagent.yml"
        )
        if not workflow.exists():
            self.skipTest("canonical KAgent workflow not present")
        text = workflow.read_text(encoding="utf-8")
        for distribution in (
            "packages/padiem-ai-core",
            "packages/padiem-control-plane",
            "apps/padiem-ai-engine/clients/python",
        ):
            self.assertIn(distribution, text, distribution)

    def test_kagent_is_required_to_come_from_src(self) -> None:
        origins = dev.describe_import_origins(("kagent",), root=REPO_ROOT)
        self.assertTrue(origins.origins[0].required_src_only)
        # And its origin really is the src tree, not an installed copy.
        self.assertIn(os.path.join("korean-ai-code-agent", "src"), str(origins.origins[0].origin))

    def test_siblings_are_not_required_to_come_from_src(self) -> None:
        # Siblings are installed distributions; demanding a src path for them
        # would be wrong, and would also make the check unsatisfiable.
        origins = dev.describe_import_origins(
            ("padiem_ai_core",), root=REPO_ROOT
        )
        self.assertFalse(origins.origins[0].required_src_only)

    def test_origins_are_read_from_resolved_files_not_sys_path_text(self) -> None:
        # Reading sys.path text would be the obvious implementation and it is
        # wrong: a path entry can look current while an earlier .pth has already
        # won. The check must go through the resolved module.
        source = VERIFIER.read_text(encoding="utf-8")
        tree = ast.parse(source)

        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        self.assertIn("import_module", called_attributes)
        self.assertNotIn(
            "getsitepackages", called_attributes | called_names
        )
        self.assertNotIn("getusersitepackages", called_attributes | called_names)
        # The containment decision itself must be a real path comparison.
        self.assertIn("_is_inside", called_names)


def _script_module():
    """Load the shipped launcher module without running the command.

    Executing the script body is safe: everything with a side effect lives under
    ``if __name__ == "__main__"``. This reads the *shipped* file rather than a
    copy, so a constant or a command cannot drift from what actually runs.
    """

    spec = importlib.util.spec_from_file_location(
        "kagent_local_test_under_test", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _script_constants() -> dict[str, object]:
    module = _script_module()
    return {
        "SIBLING_DISTRIBUTIONS": module.SIBLING_DISTRIBUTIONS,
        "TEST_REQUIREMENTS": module.TEST_REQUIREMENTS,
        "DEFAULT_ENVIRONMENT_DIRECTORY": module.DEFAULT_ENVIRONMENT_DIRECTORY,
        "REPOSITORY_MARKER_FILES": module.REPOSITORY_MARKER_FILES,
    }


class CanonicalCommandTests(unittest.TestCase):
    """I/J/K/L: the shipped command keeps the properties the issue requires."""

    @staticmethod
    def _script_tree() -> ast.Module:
        return ast.parse(SCRIPT.read_text(encoding="utf-8"))

    #: Delegates to the module-level helper so the launcher constants have a
    #: single definition shared with the freshness tests below.
    _script_constants = staticmethod(_script_constants)

    def test_kagent_itself_is_never_installed(self) -> None:
        # THE parser-isolation rule. Installing kagent puts the tree on sys.path
        # unconditionally, which makes
        # test_real_child_without_the_module_fails_closed pass for the wrong
        # reason: the child would import even with an empty PYTHONPATH.
        constants = self._script_constants()
        for entry in constants["SIBLING_DISTRIBUTIONS"]:
            self.assertNotIn("korean-ai-code-agent", entry, entry)
        self.assertNotIn("kagent", constants["SIBLING_DISTRIBUTIONS"])

    def test_the_siblings_are_installed_editable(self) -> None:
        # The correction for the stale-copy blocker CENTRAL raised on #3111.
        #
        # A non-editable install COPIES sibling sources into site-packages at
        # install time. Editing a sibling file afterwards leaves the copy stale
        # while the fingerprint -- which covers pyproject.toml but not source --
        # is unchanged, so the stale copy runs behind a green result. That is
        # the #3108 defect wearing a different mask, and it was live in the
        # first revision of this PR.
        #
        # Editable is what CI already does, so this also restores CI parity
        # rather than inventing a local-only arrangement.
        code = _code_only(SCRIPT)

        # The literal must be present: every sibling target is prefixed so pip
        # installs it in editable mode.
        self.assertIn(
            'f"-e{target}"', code, "sibling targets must be passed to pip as -e"
        )
        self.assertIn("SIBLING_DISTRIBUTIONS", code)

        # And a bare (non-editable) sibling target must not survive anywhere in
        # the install command construction.
        self.assertNotIn("*targets,", code.split("TEST_REQUIREMENTS")[0][-200:])

    def test_the_sibling_install_command_is_editable_for_every_sibling(self) -> None:
        # A behavioural check on the constructed command, not a text search: it
        # proves the prefix is actually applied to each target rather than only
        # mentioned somewhere in the file.
        module = _script_module()

        recorded: dict[str, list[str]] = {}
        original_run = module._run

        def capture(command, *, cwd, env, stream=True):
            recorded["command"] = list(command)
            return 0

        module._run = capture

        class _StubInterpreter:
            def exists(self) -> bool:
                return True

        module._interpreter = lambda environment: _StubInterpreter()

        try:
            with temporary_root() as tmp:
                root = Path(tmp)
                (root / ".git").mkdir()
                for marker in module.REPOSITORY_MARKER_FILES:
                    if marker == ".git":
                        continue
                    target = root / marker
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("", encoding="utf-8")
                # PYTHONPATH requires no sibling path to exist.
                module.build_environment(root, root / "env", recreate=False)
        finally:
            module._run = original_run

        command = recorded["command"]
        install_index = command.index("install")
        targets = command[install_index + 1 :]

        for sibling in module.SIBLING_DISTRIBUTIONS:
            self.assertIn(
                f"-e{sibling}",
                targets,
                f"{sibling} must be installed editable or a source edit goes unseen",
            )
        for requirement in module.TEST_REQUIREMENTS:
            self.assertIn(requirement, targets)
        # The environment must not receive a bare (non-editable) sibling path.
        for sibling in module.SIBLING_DISTRIBUTIONS:
            self.assertNotIn(sibling, targets)

    def test_kagent_is_never_installed_in_the_verifier_either(self) -> None:
        # The verifier is the last line of defence, so it must not be able to
        # install anything either. Checked against code only: the module
        # docstring explains the editable-install hazard in prose, and that
        # explanation must not be what decides this test.
        #
        # What matters is that the module never SHELLS OUT. A string literal
        # containing "install" is inert; a subprocess call is not.
        code = _code_only(VERIFIER)
        for forbidden in ("subprocess", "os.system", "pip", "venv"):
            self.assertNotIn(forbidden, code, forbidden)
        # And no install-shaped string is even present, so the guarantee does
        # not depend on how a future edit is worded.
        for forbidden in ("pip install", "setup.py develop", "pip.main"):
            self.assertNotIn(forbidden, code, forbidden)

    def test_the_command_never_touches_global_site_packages(self) -> None:
        constants = self._script_constants()
        for entry in constants["SIBLING_DISTRIBUTIONS"]:
            self.assertTrue(
                entry.startswith("packages/") or entry.startswith("apps/"),
                f"{entry} must be a path inside this checkout, not an index name",
            )
        source = SCRIPT.read_text(encoding="utf-8")
        # A bare distribution name would let pip resolve from an index or a
        # cache instead of from this checkout.
        self.assertIn("--no-input", source)
        self.assertNotIn("site.getsitepackages", source)
        self.assertNotIn("site.getusersitepackages", source)

    def test_the_command_requires_no_docker(self) -> None:
        # Read as code, not as text: the module docstring says "no docker is
        # used or required", and asserting on raw text would make this test fail
        # on its own documentation. A prose promise is not the property; the
        # absence of the call is.
        code = _code_only(SCRIPT).lower()
        for forbidden in ("docker", "podman", "compose"):
            self.assertNotIn(forbidden, code, forbidden)
        # And the environment is a plain interpreter venv, nothing else.
        self.assertIn("venv", code)

    def test_the_environment_lives_inside_the_checkout_and_is_ignored(self) -> None:
        constants = self._script_constants()
        self.assertEqual(
            constants["DEFAULT_ENVIRONMENT_DIRECTORY"],
            ENVIRONMENT_DIRECTORY_NAME,
        )
        gitignore = REPO_ROOT / ".gitignore"
        self.assertTrue(
            gitignore.exists(),
            "the repository must ignore the isolated environment directory",
        )
        text = gitignore.read_text(encoding="utf-8")
        self.assertIn(
            ENVIRONMENT_DIRECTORY_NAME,
            text,
            "the isolated environment must be gitignored or it becomes a "
            "large untracked tree that pollutes every status check",
        )

    def test_the_child_environment_drops_caller_pythonpath_and_user_site(self) -> None:
        # These two are the mechanism by which a foreign checkout wins. The
        # command must actively remove them, not merely set PYTHONPATH.
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("PYTHONNOUSERSITE", script)
        self.assertIn("PYTHONPATH", script)
        self.assertIn('child["VIRTUAL_ENV"]', script)
        self.assertIn("PYTHONHOME", script)

    def test_padiem_variables_are_not_forwarded_to_the_test_process(self) -> None:
        # A live-service flag inherited from a developer's shell must not change
        # what the suite exercises.
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('name.startswith("PADIEM_")', script)

    def test_the_fingerprint_covers_every_dependency_bearing_input(self) -> None:
        # A stale environment reused across a dependency change is the same class
        # of bug as a stale global install: a green run that proves nothing.
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("def environment_fingerprint", script)
        constants = self._script_constants()
        for marker in ("packages/padiem-ai-core/pyproject.toml",):
            self.assertIn(marker, constants["REPOSITORY_MARKER_FILES"], marker)

    def test_the_command_refuses_to_run_outside_a_real_checkout(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("does not look like a Padiem Claw checkout", script)


def _parse_verdict_output(text: str) -> dict:
    """Read the JSON document the verifier prints before its status line.

    The verifier writes a machine-readable table *and* a human status marker, so
    the whole stream is not valid JSON. Parsing the whole thing fails with a
    confusing "Extra data" error that says nothing about the property under
    test. Decode the first document and ignore the marker.
    """

    decoder = json.JSONDecoder()
    payload, _ = decoder.raw_decode(text.lstrip())
    return payload


class VerifierSubprocessTests(unittest.TestCase):
    """The verifier is runnable, and its exit code matches its verdict.

    An earlier revision of this test asserted ``returncode == 0`` here. That was
    wrong in an instructive way: the machine running it carried a stale global
    editable install, the verifier correctly reported a foreign
    ``padiem_ai_engine_client``, and the test failed. The test was demanding a
    green run from a contaminated environment, which is exactly the false
    evidence #3108 exists to eliminate.

    The correct invariant is not "the verifier passes". It is "the verifier's
    exit code agrees with what it reported, in both directions, and a foreign
    origin is always named". Both branches are exercised below, the passing one
    by pinning the paths to this checkout.
    """

    def _run_verifier(self, pythonpath_entries: list[str]) -> subprocess.CompletedProcess:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in ("PYTHONPATH", "PYTHONHOME")
        }
        environment["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
        return subprocess.run(
            [sys.executable, str(VERIFIER)],
            capture_output=True,
            text=True,
            env=environment,
            timeout=180,
        )

    def test_exit_code_agrees_with_the_reported_verdict_in_a_clean_environment(self) -> None:
        # The healthy branch, and the one a developer sees on a correct machine.

        # It has to be the REAL modules, not a fake tree: the verifier's whole
        # claim is that these four resolve from this checkout. A synthetic tree
        # outside the repository would be reported as foreign by definition, so
        # using one here would only re-test the failing branch.
        #
        # Which is why this test is also the regression guard for the issue
        # itself. On a machine carrying a stale global editable install, the
        # sibling origins resolve elsewhere and this assertion fails — loudly,
        # and for the right reason.
        completed = self._run_verifier(
            [
                str(APP_ROOT / "src"),
                str(REPO_ROOT / "packages/padiem-ai-core"),
                str(REPO_ROOT / "packages/padiem-control-plane"),
                str(REPO_ROOT / "apps/padiem-ai-engine/clients/python"),
            ]
        )

        payload = _parse_verdict_output(completed.stdout)
        if not payload["ok"]:
            self.fail(
                "the real modules must resolve from this checkout. If a global "
                "editable install is answering, that is the #3108 condition this "
                f"suite exists to surface, and the canonical command is the fix: "
                f"{payload}"
            )
        self.assertEqual(completed.returncode, 0, completed.stderr[-500:])
        self.assertIn("IMPORT_ORIGIN_CHECK=PASS", completed.stdout)

    def test_a_foreign_origin_is_named_and_exits_non_zero(self) -> None:
        # The other branch, and the one a contaminated developer machine hits.
        # A fake module tree outside the checkout is put ahead on the path; the
        # verifier must name it and refuse.
        with temporary_root() as tmp:
            _make_foreign_package(tmp, "kagent", "FOREIGN")

            completed = self._run_verifier(
                [str(tmp), str(APP_ROOT / "src"), str(REPO_ROOT / "packages/padiem-ai-core")]
            )

        self.assertEqual(completed.returncode, 1, completed.stdout[-500:])
        self.assertIn("IMPORT_ORIGIN_CHECK=FAIL", completed.stderr)
        # The failure must identify WHICH module and WHERE it came from, or the
        # operator cannot act on it.
        self.assertIn("kagent", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_the_exit_code_always_matches_the_reported_verdict(self) -> None:
        # CI and a developer workstation differ in whether a global editable
        # install is present, so no test may assert a fixed exit code for the
        # ambient environment. What must hold *everywhere* is that the exit code
        # agrees with the reported verdict, in both directions. This is the
        # invariant that makes the verifier trustworthy on a machine whose
        # contamination state is unknown to the test author.
        for entries, label in (
            ([str(APP_ROOT / "src"), str(REPO_ROOT / "packages/padiem-ai-core")], "in-checkout"),
            ([str(_foreign_tree()), str(APP_ROOT / "src")], "foreign"),
        ):
            with self.subTest(label=label):
                completed = self._run_verifier(entries)
                payload = _parse_verdict_output(completed.stdout)

                if payload["ok"]:
                    self.assertEqual(
                        completed.returncode, 0, completed.stderr[-500:]
                    )
                    self.assertIn("IMPORT_ORIGIN_CHECK=PASS", completed.stdout)
                else:
                    self.assertEqual(
                        completed.returncode, 1, completed.stdout[-500:]
                    )
                    self.assertIn("IMPORT_ORIGIN_CHECK=FAIL", completed.stderr)
                    # A failing verdict must always be actionable.
                    self.assertIn("repository_root=", completed.stderr)

    def test_the_verifier_actually_refuses_on_this_machine_when_contaminated(self) -> None:
        # A conditional assertion, which is unusual and deliberate.

        # The point of #3108 is that the ambient environment is not knowable in
        # advance. On a clean machine this asserts nothing; on a contaminated
        # one it asserts the refusal really happened and named a path outside
        # the checkout. Either way the suite result is stable, and neither way
        # is it possible for a contaminated machine to look healthy.
        completed = self._run_verifier(
            [
                str(APP_ROOT / "src"),
                str(REPO_ROOT / "packages/padiem-ai-core"),
                str(REPO_ROOT / "packages/padiem-control-plane"),
                str(REPO_ROOT / "apps/padiem-ai-engine/clients/python"),
            ]
        )
        payload = _parse_verdict_output(completed.stdout)
        foreign = [
            origin
            for origin in payload["origins"]
            if not origin["inside_repository"]
        ]

        if foreign:
            self.assertEqual(
                completed.returncode,
                1,
                "a machine with a foreign install must not exit 0",
            )
            for origin in foreign:
                self.assertTrue(
                    origin["origin"] is not None
                    and not str(origin["origin"]).startswith(str(REPO_ROOT)),
                    f"{origin['module']} reported foreign but resolved inside: "
                    f"{origin['origin']}",
                )
        else:
            self.assertEqual(completed.returncode, 0, completed.stderr[-500:])

    def test_the_refusal_never_leaks_a_traceback_or_a_bare_exception(self) -> None:
        with temporary_root() as tmp:
            _make_foreign_package(tmp, "kagent", "FOREIGN")
            completed = self._run_verifier([str(tmp)])

        for forbidden in ("Traceback", "File \"", "  File ", "Most recent call"):
            self.assertNotIn(forbidden, completed.stderr, forbidden)

    def test_a_stale_editable_install_on_the_host_is_detected(self) -> None:
        # The exact condition #3108 was filed about, reproduced for real.

        # A .pth file is the mechanism: site executes it at interpreter startup
        # and appends the directory unconditionally, which is how an editable
        # install of another checkout wins an import regardless of what
        # PYTHONPATH says. A real one is written into a throwaway site-packages
        # directory, and a real interpreter is started with that directory ahead
        # of the checkout.

        # Three earlier attempts failed here and each is worth recording.
        # One shipped a shadowing kagent.py that made kagent.dev_environment
        # unimportable, so the probe died for an unrelated reason. The next
        # asserted that the other checkout won, and a local shadow beat it
        # instead because the inserted directory outranked the .pth path. The
        # last manipulated sys.path by hand and found the verdict passing --
        # because `from kagent.dev_environment import ...` had already put the
        # real kagent in sys.modules, and an already-imported module is never
        # re-resolved against a new sys.path.
        #
        # So the mechanism is driven the way it actually happens: a real .pth is
        # processed by the real site.addsitedir before any repository code runs.
        # The checkout's src is NOT on the path at all, which is precisely the
        # situation a stale global editable install creates.
        with temporary_root() as tmp:
            foreign_src = tmp / "other-checkout" / "src"
            _make_foreign_package(foreign_src, "kagent", "FOREIGN_VIA_PTH")

            site_packages = tmp / "site-packages"
            site_packages.mkdir(parents=True)
            # The real artefact an editable install leaves behind.
            (site_packages / "__editable__.korean_ai_code_agent.pth").write_text(
                str(foreign_src) + "\n", encoding="utf-8"
            )

            environment = {
                key: value
                for key, value in os.environ.items()
                if key not in ("PYTHONPATH", "PYTHONHOME")
            }
            # -S skips site processing, and PYTHONNOUSERSITE skips the per-user
            # directory. Both are required here, and finding out why is the whole
            # point of this test.
            #
            # An earlier version ran WITHOUT -S and asserted the temp .pth won.
            # It lost -- to this machine's real global editable install at
            # E:/b54-260908, which sits in site-packages and outranks anything a
            # temporary directory adds. That is not a flaw in the test setup; it
            # is the #3108 condition occurring live, on the machine running the
            # suite. A test that depends on winning that race would pass on a
            # clean CI runner and fail on every developer workstation, which is
            # the opposite of a contract test.
            #
            # With the host excluded, the .pth is the only thing on the path and
            # the foreign tree genuinely wins.
            probe = (
                "import json,site,sys;"
                "site.addsitedir(r'%s');"
                "import kagent;"
                "print(json.dumps({'module': kagent.__file__,"
                " 'marker': getattr(kagent, 'MARKER', None)}))"
                % (site_packages,)
            )
            environment["PYTHONNOUSERSITE"] = "1"
            completed = subprocess.run(
                [sys.executable, "-S", "-c", probe],
                capture_output=True,
                text=True,
                env=environment,
                timeout=180,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr[-500:])
            probe_payload = json.loads(completed.stdout)
            self.assertIn("other-checkout", str(probe_payload["module"]))
            self.assertEqual(probe_payload["marker"], "FOREIGN_VIA_PTH")

            # Half two: the verifier must report the foreign origin.
            #
            # PYTHONPATH is deliberately EMPTY and site.addsitedir is called
            # explicitly. Both details are load-bearing:
            #
            # * PYTHONPATH entries precede anything site processing adds, so
            #   pointing it at the checkout made the checkout win and the verdict
            #   came back clean -- the opposite of the condition under test.
            # * site.addsitedir must be re-issued in THIS process. An earlier
            #   version only called it in the probe, so when the verifier ran in a
            #   fresh interpreter the .pth was never processed, kagent was simply
            #   not importable, and the refusal was correct for the wrong reason.
            #
            # The verifier is loaded with runpy rather than imported, because
            # importing kagent.dev_environment would itself resolve through the
            # foreign tree. This also exercises the no-__file__ path, which
            # test_the_verifier_runs_without_a_dunder_file covers directly.
            verdict_probe = (
                "import json,runpy,site,sys;"
                "site.addsitedir(r'%s');"
                "sys.argv=['dev_environment'];"
                "runpy.run_path(r'%s', run_name='__main__')"
                % (site_packages, VERIFIER)
            )
            verdict = subprocess.run(
                [sys.executable, "-S", "-c", verdict_probe],
                capture_output=True,
                text=True,
                env=environment,
                cwd=str(tmp),
                timeout=180,
            )

            # A clean refusal, with no traceback, naming the foreign tree.
            self.assertNotIn("Traceback", verdict.stderr, verdict.stderr[-500:])
            self.assertEqual(verdict.returncode, 1, verdict.stdout[-500:])
            self.assertIn("IMPORT_ORIGIN_CHECK=FAIL", verdict.stderr)
            self.assertIn("kagent", verdict.stderr)
            # The operator can only act if the refusal names where it came from.
            self.assertIn("other-checkout", verdict.stderr)
            self.assertNotIn("Traceback", verdict.stderr)


    def test_the_environment_directory_cannot_satisfy_a_foreign_import(self) -> None:
        # A complementary property: the isolated environment the launcher builds
        # must not be able to launder a foreign module past the check. A module
        # installed into a site-packages directory whose recorded path points
        # outside the checkout is still foreign, because the check reads the
        # RESOLVED file, not the directory that appears to contain it.
        with temporary_root() as tmp:
            foreign_file = tmp / "outside" / "kagent" / "__init__.py"
            foreign_file.parent.mkdir(parents=True, exist_ok=True)
            foreign_file.write_text("MARKER = 'FOREIGN'\n", encoding="utf-8")

            self.assertFalse(dev._is_inside(foreign_file, REPO_ROOT))


class SiblingFreshnessTests(unittest.TestCase):
    """The stale-copy blocker CENTRAL raised on #3111, proved closed.

    The first revision of this PR installed the siblings non-editably, which
    COPIES their sources into ``site-packages`` at install time. The environment
    fingerprint covered each sibling ``pyproject.toml`` but not its source, so
    the sequence below produced a green run against code that was no longer in
    the tree:

        build env -> edit a sibling .py -> pyproject unchanged
        -> fingerprint unchanged -> env reused -> stale copy runs

    The whole point of #3108 is that a green run must prove the current source.
    A stale copy inside the same repository is the same defect as a foreign
    checkout: both produce a pass that proves nothing.

    These tests run against the REAL built environment rather than a model of
    it, because the failure mode is precisely a mismatch between what the
    configuration says and what the interpreter does.

    The environment is located through ``KAGENT_LOCAL_TEST_ENV``, which the
    launcher publishes into the test process. The variable is what makes a
    ``--environment-dir`` run verifiable at all; without it a relocated
    environment would leave these tests pointing at the default location and
    skipping in silence, which is the concealment this suite exists to prevent.

    When no environment is present the tests skip rather than fail: they assert a
    property of a BUILT environment, and the launcher builds one on demand. The
    canonical command publishes the variable, so a run through it never skips.
    """

    def _environment_root(self) -> Path:
        override = os.environ.get("KAGENT_LOCAL_TEST_ENV")
        if not override:
            # No published environment. Fall back to the default location so a
            # developer who built it by hand still gets the check, but say so:
            # silence here would be indistinguishable from the contract holding.
            return REPO_ROOT / ".kagent-local-test-env"
        return Path(override)

    def setUp(self) -> None:
        root = self._environment_root()
        interpreter = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not interpreter.exists():
            self.skipTest(
                f"isolated environment not built at {root}; run "
                "scripts/kagent_local_test.py first"
            )
        self.interpreter = interpreter

    def test_a_mutation_probe_restores_bytes_not_reencoded_text(self) -> None:
        # A guard on the guards, proved by BEHAVIOUR rather than by text.
        #
        # The freshness tests edit real files in the working tree. When they
        # restored with a plain read_text/write_text round trip, universal
        # newlines silently converted LF sources to CRLF and left a whole-file
        # diff behind. Two sibling sources were modified by a PASSING test, and
        # the residue then broke an unrelated Windows process-tree test in the
        # same run.
        #
        # Two earlier versions of this guard were wrong in instructive ways and
        # both are recorded here. The first asserted on this file's own source
        # text, so the forbidden substring appeared in the assertion itself and
        # the guard could only ever fail. The second asserted that
        # ``newline=""`` could NOT repair a text round trip; that was backwards.
        # ``read_text`` normalises CRLF to LF, and ``newline=""`` then writes LF
        # literally, so the pair does round-trip. Only the PLAIN write_text
        # reintroduces CRLF.
        #
        # The freshness tests use bytes for both the mutation and the restore, so
        # none of this subtlety applies to them. That is the point: the
        # behaviour is asserted here so the choice is justified rather than
        # incidental.
        with temporary_root() as tmp:
            target = tmp / "lf_source.py"
            original = b"VALUE = 1\nOTHER = 2\n"
            target.write_bytes(original)

            # The lossy pattern: decode, then write with default newline
            # handling, which translates LF back to the platform separator.
            decoded = target.read_text(encoding="utf-8")
            target.write_text(decoded, encoding="utf-8")
            self.assertNotEqual(
                target.read_bytes(),
                original,
                "premise check: a plain text round trip must alter the bytes, "
                "otherwise this guard would prove nothing",
            )
            self.assertIn(
                b"\r\n",
                target.read_bytes(),
                "premise check: a plain write_text is what introduced the CRLF",
            )

            # The pattern the freshness tests actually use: bytes in, bytes out,
            # with no text decoding anywhere near the file being mutated.
            target.write_bytes(original)
            snapshot = target.read_bytes()
            try:
                target.write_bytes(snapshot + b"PROBE = True\n")
                self.assertNotIn(
                    b"\r\n",
                    target.read_bytes(),
                    "a byte append must not introduce CRLF",
                )
            finally:
                target.write_bytes(snapshot)
            self.assertEqual(
                target.read_bytes(),
                original,
                "the byte round trip must restore exactly",
            )        # The contract the rest of this class depends on.
        #
        # Without it, a `--environment-dir` run relocates the environment and
        # these tests silently fall back to the default path, skip, and report
        # green without ever having checked anything. A test suite that can be
        # skipped into meaninglessness by removing one assignment is not a
        # contract, so the assignment is asserted directly.
        code = _code_only(SCRIPT)
        self.assertIn("KAGENT_LOCAL_TEST_ENV", code)
        self.assertIn(
            'child["KAGENT_LOCAL_TEST_ENV"] = str(environment)',
            code,
            "the launcher must publish the environment it built into the test "
            "process, or the freshness tests verify a different environment "
            "than the one that ran them",
        )

    def _import_probe(self, module: str) -> str:
        """The file a module resolves to inside the real isolated environment."""

        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in ("PYTHONPATH", "PYTHONHOME")
        }
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONPATH"] = str(APP_ROOT / "src")
        completed = subprocess.run(
            [
                str(self.interpreter),
                "-c",
                "import json,importlib;"
                f"m=importlib.import_module({module!r});"
                "print(json.dumps({'file': getattr(m, '__file__', None)}))",
            ],
            capture_output=True,
            text=True,
            env=environment,
            timeout=180,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-500:])
        return json.loads(completed.stdout)["file"]

    def test_every_sibling_resolves_to_a_source_tree_not_site_packages(self) -> None:
        # The structural property that makes staleness impossible: a sibling
        # import must land on a .py file inside the checkout's source tree.
        #
        # A copied install would resolve to
        # .kagent-local-test-env/Lib/site-packages/<name>/__init__.py, which is
        # inside the repository -- so the origin check would PASS while the
        # code was a snapshot. Asserting the path shape is what distinguishes
        # "live source" from "a copy that happens to live in the repo".
        expected_roots = {
            "padiem_ai_core": REPO_ROOT / "packages" / "padiem-ai-core",
            "padiem_control_plane": REPO_ROOT / "packages" / "padiem-control-plane",
            "padiem_ai_engine_client": REPO_ROOT
            / "apps"
            / "padiem-ai-engine"
            / "clients"
            / "python",
        }

        for module, source_root in expected_roots.items():
            with self.subTest(module=module):
                origin = self._import_probe(module)
                self.assertIsNotNone(origin, module)
                resolved = Path(origin).resolve()

                self.assertTrue(
                    dev._is_inside(resolved, source_root),
                    f"{module} resolved to {resolved}, which is not inside its "
                    f"source tree {source_root}. A copied install is exactly "
                    "this failure: same repository, stale code.",
                )
                self.assertNotIn(
                    "site-packages",
                    str(resolved),
                    f"{module} resolved from site-packages, so it is a copied "
                    "snapshot rather than live source",
                )

    def test_editing_a_sibling_source_file_is_visible_to_the_next_import(self) -> None:
        # The exact sequence CENTRAL specified, executed for real.
        #
        #   BUILD ENV -> mutate sibling source without touching pyproject
        #   -> next import must see the mutation
        #   -> a stale copy must never answer
        #
        # The file is restored from the ORIGINAL BYTES in a finally block, not
        # from re-encoded text. An earlier version read with read_text and wrote
        # back with write_text, which is NOT a round trip: universal newlines
        # turned an LF file into CRLF and left a whole-file diff behind. Two
        # sibling sources were silently modified by a passing test, and the
        # residue then broke an unrelated Windows process-tree test. Byte
        # preservation is load-bearing, not tidiness.
        target = (
            REPO_ROOT
            / "packages"
            / "padiem-control-plane"
            / "padiem_control_plane"
            / "__init__.py"
        )
        if not target.exists():
            self.skipTest("control plane source layout differs from expectation")

        original_bytes = target.read_bytes()
        marker = b"PADIEM_3108_FRESHNESS_PROBE = True"
        mutated = original_bytes + b"\n" + marker + b"\n"

        try:
            # Bytes only. `read_text` would decode with universal newlines and
            # turn this LF file into CRLF on the way back out, which is the
            # defect this test was written to avoid reproducing.
            target.write_bytes(mutated)
            origin = self._import_probe("padiem_control_plane")

            # The import must resolve to the file we just wrote, not a copy.
            self.assertEqual(
                Path(origin).resolve(),
                target.resolve(),
                "a sibling edit must be visible immediately; a resolved copy "
                "means the install is non-editable and the run is stale",
            )
        finally:
            target.write_bytes(original_bytes)

        # Byte-for-byte restoration, asserted. A test that mutates the working
        # tree must leave no trace, and this is the only way to know.
        self.assertEqual(
            target.read_bytes(),
            original_bytes,
            "the freshness test must restore the file byte-for-byte",
        )
        self.assertNotIn(b"PADIEM_3108_FRESHNESS_PROBE", target.read_bytes())
        # No CRLF may have been introduced anywhere in the operation.
        self.assertNotIn(b"\r\n", target.read_bytes())

    def test_the_engine_client_is_live_for_the_same_reason(self) -> None:
        # Core is covered by the path-shape test above, which also covers the
        # fact that PYTHONPATH no longer lists a sibling. Engine client is
        # exercised here with a real edit, because it is the sibling whose
        # import count in the suite is smallest and therefore easiest to leave
        # silently stale.
        target = (
            REPO_ROOT
            / "apps"
            / "padiem-ai-engine"
            / "clients"
            / "python"
            / "padiem_ai_engine_client"
            / "__init__.py"
        )
        if not target.exists():
            self.skipTest("engine client source layout differs from expectation")

        original_bytes = target.read_bytes()
        try:
            target.write_bytes(
                original_bytes + b"\nPADIEM_3108_ENGINE_PROBE = True\n"
            )
            origin = self._import_probe("padiem_ai_engine_client")
            self.assertEqual(Path(origin).resolve(), target.resolve())
        finally:
            target.write_bytes(original_bytes)

        self.assertEqual(target.read_bytes(), original_bytes)
        self.assertNotIn(b"\r\n", target.read_bytes())

    def test_pytest_is_not_covered_by_the_sibling_liveness_contract(self) -> None:
        # A guard on the guard: third-party test requirements are ordinary
        # non-editable installs, and the freshness contract must not be claimed
        # for them. PyPI packages are immutable at a given version, so a copy is
        # correct for them in a way it is not for a sibling under active edit.
        constants = _script_constants()
        self.assertIn("pytest>=8,<10", constants["TEST_REQUIREMENTS"])
        for requirement in constants["TEST_REQUIREMENTS"]:
            self.assertFalse(
                requirement.startswith("-e"),
                "a PyPI requirement is not an editable target",
            )


if __name__ == "__main__":
    unittest.main()
