# KAgent local test environment (#3108)

```text
DOC_STATUS = CURRENT
CANONICAL_LOCAL_KAGENT_TEST_COMMAND = python scripts/kagent_local_test.py
ISOLATED_ENVIRONMENT = YES
FOREIGN_EDITABLE_IMPORT_FAILS_CLOSED = YES
KAGENT_EDITABLE_INSTALL_REQUIRED = NO
LOCAL_DOCKER_REQUIRED = NO
```

## The problem this solves

The obvious way to run the KAgent suite locally is not trustworthy:

```bash
python -m unittest discover -s apps/korean-ai-code-agent/tests
```

That resolves `kagent` from whatever the interpreter finds first. On a machine
carrying editable installs, that is frequently **a different checkout**:

```text
running tests from checkout A
  -> an __editable__ .pth from checkout B resolves kagent
  -> the suite passes against code nobody in this checkout reviewed
  -> the local result does not prove the reviewed source
```

The failure is not a crash. It is a **green run that proves nothing**, which is
strictly worse than a failure because it is believed.

You can see it directly:

```bash
python -c "import kagent; print(kagent.__file__)"
```

If that path is not inside the directory you are standing in, your next test
result means nothing.

## The canonical command

```bash
python scripts/kagent_local_test.py
```

From the repository root. That is the whole contract — one command, no flags,
no Docker, no manual environment preparation.

Useful variants:

| Command | Effect |
|---|---|
| `python scripts/kagent_local_test.py --verify-only` | build and verify the environment, do not run the suite |
| `python scripts/kagent_local_test.py --recreate` | force a rebuild even if the inputs are unchanged |
| `python scripts/kagent_local_test.py -k pattern` | extra arguments are forwarded to `unittest discover` |

## What it guarantees

**1. Isolation.** A dedicated virtual environment is created at
`.kagent-local-test-env/` inside the checkout, and the tests run with that
environment's interpreter. The caller's `PYTHONPATH` is replaced rather than
extended, and `PYTHONNOUSERSITE=1` skips the per-user site directory — a user
site `.pth` is one of the ways a foreign checkout wins an import.

**2. Siblings come from this checkout, live.** `padiem-ai-core`,
`padiem-control-plane` and `padiem-ai-engine-client` are installed **editable**
(`pip install -e`) from paths inside this repository, which is exactly what CI
does. Their imports keep resolving to the source trees, so editing a sibling is
visible to the very next run.

Editable is load-bearing, not a convenience. A non-editable install *copies* the
sources into `site-packages` at install time. Editing a sibling file then leaves
the copy stale, the origin check still passes (the copy is inside the
repository), and the suite runs code that is no longer in the tree — the same
defect as a foreign checkout, wearing a different mask. The sibling paths are
spelled out in `SIBLING_DISTRIBUTIONS` rather than discovered, so adding a
package to the monorepo cannot silently widen what a local run installs.

**3. KAgent is never installed.** It runs from `src` on `PYTHONPATH`.

This is not a stylistic choice. Installing KAgent — even as an editable — puts
the tree on `sys.path` unconditionally, which would invalidate the
parser-isolation contract: that contract is proved by a child process *failing*
to import when its import root is emptied
(`test_real_child_without_the_module_fails_closed`). An editable `.pth` makes the
child importable no matter what `PYTHONPATH` says, so the test would pass for
the wrong reason. **Never `pip install -e` KAgent.**

**4. Origins are proved before the suite runs.** The verifier resolves
`kagent`, `padiem_ai_core`, `padiem_control_plane` and
`padiem_ai_engine_client`, and refuses to continue if any of them resolved
outside this checkout. A foreign import is a refusal with a named path, not a
confusing collection error three minutes in.

The ordering matters. Installing first and verifying afterwards would be too
late: `site` processes `.pth` files at interpreter startup, before any code in
this repository runs.

## What the refusal looks like

```text
kagent local test environment refused to run: import origins are not
confined to the checkout under review.
repository_root=E:\padiem-wt-3108
  kagent: resolved to E:\b54-260908\apps\korean-ai-code-agent\src\kagent\__init__.py
  ...
IMPORT_ORIGIN_CHECK=FAIL
```

That output is not hypothetical. It is what this repository's own development
machine produced while building the verifier.

## Verifying the verifier

You can check origins yourself without running the suite:

```bash
python apps/korean-ai-code-agent/src/kagent/dev_environment.py
```

It prints a JSON table and exits non-zero on any foreign origin.

The origin table shows *where* a module came from. Because the siblings are
installed editable, a path under the checkout's own source tree is what a live
import looks like; a path under `.kagent-local-test-env/.../site-packages/` would
mean a copied, potentially stale install. The freshness tests assert that shape
directly.

## If you are still contaminated

The isolated command fixes the *test run*. It does not repair your machine, and
it is not meant to. Removing a stale global editable install is operator-owned
work, and machine-specific paths are deliberately not encoded anywhere in this
repository — doing so would reintroduce the coupling this removes.

To see what your interpreter currently resolves:

```bash
python -c "import site,glob,os;[print(p) for d in {site.getsitepackages()[0], site.getusersitepackages()} for p in glob.glob(os.path.join(d,'*.pth'))]"
```

Remove the entries pointing at checkouts you no longer work in, or work in a
virtual environment of your own. The canonical command makes this optional
rather than mandatory, which is the intended outcome.

## Relationship to CI

CI (`.github/workflows/validate-b54-kagent.yml`) deliberately runs KAgent from
`PYTHONPATH=src` and installs the siblings editable, for the same
parser-isolation reason. This local command mirrors that composition. It does not
change CI, and CI does not depend on it.

`Pillow` is the one deliberate difference. CI installs one exact approved native
wheel and proves its provenance before use
(`PILLOW_12_3_0_NATIVE_WHEEL_PROVENANCE_3016.md`). A local run cannot make the
same guarantee about a platform-resolved wheel, so Pillow is not pinned locally
and the image tests skip. That is documented behaviour, not a silent weakening.

## Files

| Path | Role |
|---|---|
| `scripts/kagent_local_test.py` | the canonical command |
| `apps/korean-ai-code-agent/src/kagent/dev_environment.py` | the import-origin verifier |
| `apps/korean-ai-code-agent/tests/test_dev_environment_3108.py` | contract tests for both |
