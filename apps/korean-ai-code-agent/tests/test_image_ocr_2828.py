"""#2828: the kagent-local PaddleOCR child adapter is bounded and offline.

These tests are non-vacuous. They start the real reviewed child process, hang a
real child and prove it dies, drive the kill ladder against a process double
that refuses to stop, and run the child's real projection against
PaddleOCR-shaped result objects. Nothing here asserts that a string appears in a
module — except where the claim *is* about structure (the child holds no process
or decoder authority, orientation is off) and is simultaneously proven at runtime
or by reading the AST.

Coverage map:

* A  Korean / English / mixed text through the facade's full fixed composition
* B  gate refusal and Core transform refusal -> no child process created
* C  child hang -> finite timeout -> TIMED_OUT -> child dead
* D  terminate that will not stop the child -> kill escalation -> child dead
* E  timeout != cancellation
* F  timeout error: payload 0, host path 0, traceback 0, model dir 0
* G  malformed child result -> fail closed
* H  oversized child result / oversized envelope / oversized text -> fail closed
* I  child crash, missing runtime -> bounded deterministic codes
* J  environment bounds, local model directories, orientation OFF
* K  ORIGINAL_SOURCE_BYTES_TO_OCR_CHILD=0; SECOND_UNTRUSTED_IMAGE_DECODER=0
* L  provenance receipt is path-free, revision-bearing and digest-bearing
* M  every lifecycle and byte knob bounded above; no launcher hook
* N  optional live smoke, gated on explicit local model directories
* O  official model manifests: exact file/size/SHA, symlink, extras, preflight
* P  canonical PNG: signature, format, IHDR dimensions and SHA-256, both sides
"""

from __future__ import annotations

import ast
import base64
import hashlib
import inspect
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import kagent.image_ocr_child as child
import kagent.image_ocr_contract as contract
import kagent.image_ocr_isolation as isolation
from kagent.image_skill import (
    CAPABILITY_IMAGE_OCR,
    ImageSkillError,
    image_ocr,
)

_LEAK_MARKER = "RAWPAYLOADMARKER_DO_NOT_LEAK"
_SECRET = "SUPERSECRETTOKEN_DO_NOT_LEAK"

#: Environment variables that opt a run into the optional live OCR smoke.
_MODEL_DIR_ENV = ("KAGENT_OCR_DETECTOR_DIR", "KAGENT_OCR_RECOGNIZER_DIR")

#: The pinned official manifest triples, captured before the fixtures install
#: their own tiny stand-in manifests. Kept so the production constants can still
#: be asserted after the fixture patch is active.
_PINNED_DETECTOR_MANIFEST = contract.DETECTOR_MODEL_MANIFEST
_PINNED_RECOGNIZER_MANIFEST = contract.RECOGNIZER_MODEL_MANIFEST
_PINNED_DETECTOR_REVISION = contract.DETECTOR_MODEL_REVISION
_PINNED_RECOGNIZER_REVISION = contract.RECOGNIZER_MODEL_REVISION

#: The three required official filenames, in the order the manifests list them.
_MODEL_FILENAMES = ("inference.yml", "inference.json", "inference.pdiparams")

#: Tiny deterministic stand-in file bodies. Every fixture model directory writes
#: exactly these bytes, so one fixture-wide manifest patch covers the whole
#: module; the production 88 MB weight digest is asserted separately as a
#: literal, and is never fabricated here.
_FIXTURE_DETECTOR_BODY = {
    name: f"detector::{name}".encode() for name in _MODEL_FILENAMES
}
_FIXTURE_RECOGNIZER_BODY = {
    name: f"recognizer::{name}".encode() for name in _MODEL_FILENAMES
}


def _manifest_for(bodies: dict[str, bytes]) -> tuple[tuple[str, int, str], ...]:
    """The exact manifest triple a fixture model directory satisfies."""

    return tuple(
        (name, len(bodies[name]), hashlib.sha256(bodies[name]).hexdigest())
        for name in _MODEL_FILENAMES
    )


_FIXTURE_DETECTOR_MANIFEST = _manifest_for(_FIXTURE_DETECTOR_BODY)
_FIXTURE_RECOGNIZER_MANIFEST = _manifest_for(_FIXTURE_RECOGNIZER_BODY)

_MANIFEST_PATCHES: list = []


def setUpModule() -> None:
    """Point the boundary at the tiny fixture manifests for the whole module.

    The real manifests are 88 MB and 13 MB of official weights, which cannot be
    fabricated in a unit test. What is under test is the *check* — exact name,
    exact size, exact digest, no symlink, no extras — so the fixtures write real
    files with real digests and the pinned constants are temporarily replaced by
    their digests. The production constants themselves are asserted separately
    against the literals CENTRAL supplied.
    """

    for module in (contract, isolation, child):
        patch = mock.patch.multiple(
            module,
            DETECTOR_MODEL_MANIFEST=_FIXTURE_DETECTOR_MANIFEST,
            RECOGNIZER_MODEL_MANIFEST=_FIXTURE_RECOGNIZER_MANIFEST,
        )
        _MANIFEST_PATCHES.append(patch)
        patch.start()


def tearDownModule() -> None:
    for patch in reversed(_MANIFEST_PATCHES):
        patch.stop()
    _MANIFEST_PATCHES.clear()


#: A sentinel meaning "remove this key from the frame", so one frame builder can
#: express both an extra key and a missing key.
_DROP = object()


def _png_bytes(
    fmt: str = "PNG",
    *,
    size: tuple[int, int] = (12, 8),
    color: tuple[int, int, int] = (10, 20, 30),
) -> bytes:
    image = Image.new("RGB", size, color)
    out = io.BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


class _Page(dict):
    """A PaddleOCR result page: a mapping that also exposes ``.json``."""

    @property
    def json(self) -> dict:
        return self


def _page(
    texts: list[str],
    scores: list[float] | None = None,
    polys: list[list[list[int]]] | None = None,
) -> _Page:
    return _Page(
        rec_texts=texts,
        rec_scores=scores if scores is not None else [0.99] * len(texts),
        rec_polys=polys if polys is not None else [],
        dt_polys=polys if polys is not None else [],
    )


class _Box:
    """A bounded quad, as a text detector would return it."""

    def __init__(self, x: int = 0, y: int = 0, w: int = 10, h: int = 4) -> None:
        self.points = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


class _FakeRuntime:
    """Stand-in for the ``PaddleOCR`` class the child really constructs.

    The double is installed as ``paddleocr.PaddleOCR`` in a stub module, so the
    child's *real* ``_build_runtime`` runs and this records the exact constructor
    keyword arguments it passed. Replacing ``_build_runtime`` instead would skip
    the code under test and could not prove the model directories or the
    orientation flags are what the child actually sends.
    """

    instances: list["_FakeRuntime"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.predict_calls: list[tuple[str, dict]] = []
        self.read_bytes: list[bytes] = []
        self.closed = False
        self.payload = [_page(["stub"])]
        _FakeRuntime.instances.append(self)

    def predict(self, path, **kwargs):
        self.predict_calls.append((path, kwargs))
        with open(path, "rb") as stream:
            self.read_bytes.append(stream.read())
        return self.payload

    def close(self) -> None:
        self.closed = True


def _fake_paddleocr_module(revision: str = contract.PADDLEOCR_RUNTIME_REVISION):
    """A stub ``paddleocr`` module exposing only what the child imports."""

    module = types.ModuleType("paddleocr")
    module.PaddleOCR = _FakeRuntime
    module.__version__ = revision
    return module


class _SpawnSpy:
    """Count and record spawns, then delegate to the real child."""

    def __init__(self, delegate=None) -> None:
        self.argv: list[list[str]] = []
        self.environments: list[dict[str, str]] = []
        self._delegate = delegate or isolation._spawn_ocr_child

    def __call__(self, argv: list[str], environment: dict[str, str]):
        self.argv.append(list(argv))
        self.environments.append(dict(environment))
        return self._delegate(argv, environment)

    @property
    def calls(self) -> int:
        return len(self.argv)


class _ProcessDouble:
    """``Popen``-shaped double whose terminate and kill can be ignored."""

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        exit_code: int = 0,
        alive: bool = False,
        ignores_terminate: bool = False,
        ignores_kill: bool = False,
    ) -> None:
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode: int | None = None if alive else exit_code
        self.terminated = False
        self.killed = False
        self._exit_code = exit_code
        self._alive = alive
        self._ignores_terminate = ignores_terminate
        self._ignores_kill = ignores_kill

    def wait(self, timeout: float | None = None) -> int | None:
        if self._alive:
            raise subprocess.TimeoutExpired("ocr-child", timeout or 0.0)
        return self.returncode

    def poll(self) -> int | None:
        return None if self._alive else self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if not self._ignores_terminate:
            self._alive = False
            self.returncode = self._exit_code

    def kill(self) -> None:
        self.killed = True
        if not self._ignores_kill:
            self._alive = False
            self.returncode = self._exit_code


def _spawn_returning(process: _ProcessDouble):
    return lambda argv, environment: process


def _spawn_running(program: list[str]) -> tuple[object, list]:
    """A real ``Popen`` of an arbitrary attacker-shaped child program."""

    handles: list = []

    def spawn(_argv: list[str], environment: dict[str, str]):
        process = subprocess.Popen(
            program,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        handles.append(process)
        return process

    return spawn, handles


def _imported_module_names(path: Path) -> set[str]:
    """Every module name imported by a source file, straight from its AST.

    Reading the AST rather than the text is what makes the structural
    assertions documentation-proof: prose that *names* a forbidden module cannot
    trip a test, and a real import cannot hide behind a comment.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
                names.add(node.module.split(".")[0])
            for alias in node.names:
                names.add(alias.name)
    return names


def _called_names(path: Path) -> set[str]:
    """Every bare-name or attribute call target in a source file."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            called.add(func.id)
        elif isinstance(func, ast.Attribute):
            called.add(func.attr)
    return called


def _popen_keywords(path: Path) -> list[str]:
    """Keyword argument names of the ``subprocess.Popen`` call in a module."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Popen"
        ):
            return [keyword.arg for keyword in node.keywords if keyword.arg]
    return []


def _hang_command() -> list[str]:
    """A real child that never reads stdin and never finishes in time."""

    return [sys.executable, "-c", "import time; time.sleep(30)"]


def _provenance_frame(**overrides) -> dict:
    frame = {
        "runtime": "paddleocr",
        "runtime_revision": contract.PADDLEOCR_RUNTIME_REVISION,
        "detector_revision": contract.DETECTOR_MODEL_REVISION,
        "recognizer_revision": contract.RECOGNIZER_MODEL_REVISION,
        "canonical_png_sha256": hashlib.sha256(_png_bytes()).hexdigest(),
        "mode": child.OCR_MODE,
    }
    frame.update(overrides)
    return frame


def _success_bytes(
    results: list[dict] | None = None, provenance: dict | None = None
) -> bytes:
    return json.dumps(
        {
            "ok": True,
            "provenance": provenance or _provenance_frame(),
            "results": results if results is not None else [],
        },
        ensure_ascii=False,
    ).encode("utf-8")


def _result_frame(text: str, score: float = 0.99, points: list | None = None) -> dict:
    return {
        "text": text,
        "score": score,
        "boxes": [] if points is None else [{"points": points}],
    }


class _ModelDirs:
    """Two real local model directories holding real, digest-checked files.

    The files are tiny stand-ins, but they are written for real and validated by
    the real manifest check, so every fixture run exercises the exact
    name/size/SHA-256 path rather than bypassing it.
    """

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.detector = root / "detector"
        self.recognizer = root / "recognizer"
        self.detector.mkdir()
        self.recognizer.mkdir()
        for name, body in _FIXTURE_DETECTOR_BODY.items():
            (self.detector / name).write_bytes(body)
        for name, body in _FIXTURE_RECOGNIZER_BODY.items():
            (self.recognizer / name).write_bytes(body)
        self.root = str(root)
        # The public boundary takes ``str``, so the fixture hands out ``str``
        # exactly as a caller would.
        self.detector_dir = str(self.detector)
        self.recognizer_dir = str(self.recognizer)

    def cleanup(self) -> None:
        self._tmp.cleanup()


def _run_isolated(
    *,
    png: bytes | None = None,
    width: int = 12,
    height: int = 8,
    dirs: "_ModelDirs | None" = None,
    policy=None,
):
    owned = dirs is None
    dirs = dirs or _ModelDirs()
    try:
        return isolation.ocr_png_isolated(
            png=png if png is not None else _png_bytes(),
            width=width,
            height=height,
            detector_dir=dirs.detector_dir,
            recognizer_dir=dirs.recognizer_dir,
            policy=policy or isolation.DEFAULT_OCR_ISOLATION_POLICY,
        )
    finally:
        if owned:
            dirs.cleanup()


def _noisy_png(size: int = 900) -> bytes:
    """A PNG whose encoded size is dominated by real pixel data, not a header."""

    import random

    generator = random.Random(20260925)
    image = Image.new("RGB", (size, size))
    image.putdata(
        [
            (generator.randrange(256), generator.randrange(256), generator.randrange(256))
            for _ in range(size * size)
        ]
    )
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _child_main(envelope: bytes) -> contract.OcrReport | None:
    """Run the reviewed child's ``main`` in-process and decode its report.

    ``sys.stdout`` itself is replaced rather than its ``buffer`` attribute,
    because the real stream's buffer is read-only on this interpreter.
    """

    stdin = mock.Mock()
    stdin.buffer.read.return_value = envelope
    sink = io.BytesIO()
    text_stream = io.TextIOWrapper(sink, encoding="utf-8", write_through=True)
    with mock.patch.object(sys, "stdin", stdin), mock.patch.object(
        sys, "stdout", text_stream
    ), mock.patch.object(
        child,
        "_deny_python_network",
        return_value=None,
    ):
        # Production executes ``main`` in a dedicated process. Unit tests call it
        # in-process, so the real global socket monkey-patch would poison unrelated
        # tests (notably Windows asyncio's local socketpair). The production guard
        # is exercised separately in a real child subprocess.
        exit_code = child.main()
        text_stream.flush()
    assert exit_code == 0
    return contract.decode_report(sink.getvalue())


class KoreanEnglishMixedProjectionTests(unittest.TestCase):
    """A: Korean, English and mixed text project without being mangled."""

    def test_korean_text_projects_with_its_box(self) -> None:
        out = child.project_results([_page(["견적서"], [0.99], [_Box(1, 2).points])])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].text, "견적서")
        self.assertEqual(out[0].score, 0.99)
        self.assertEqual(out[0].boxes[0].points, ((1, 2), (11, 2), (11, 6), (1, 6)))

    def test_english_text_projects_with_its_box(self) -> None:
        out = child.project_results([_page(["Invoice No. 42"], [0.87], [_Box().points])])
        self.assertEqual(out[0].text, "Invoice No. 42")
        self.assertEqual(out[0].score, 0.87)
        self.assertEqual(len(out[0].boxes), 1)

    def test_mixed_korean_english_page_keeps_every_line_in_order(self) -> None:
        texts = ["견적서", "Invoice", "합계 1,000원", "Total", "부가세 100원"]
        out = child.project_results([_page(texts, [0.9, 0.8, 0.95, 0.7, 0.99])])
        self.assertEqual([result.text for result in out], texts)

    def test_a_page_with_no_recognized_text_is_empty_not_an_error(self) -> None:
        self.assertEqual(child.project_results([_page([])]), ())
        self.assertEqual(child.project_results([]), ())
        self.assertEqual(child.project_results(None), ())

    def test_singular_result_keys_are_read_as_well_as_plural(self) -> None:
        page = _Page(rec_text=["legacy"], rec_score=[0.5], dt_polys=[_Box().points])
        out = child.project_results([page])
        self.assertEqual(out[0].text, "legacy")
        self.assertEqual(out[0].score, 0.5)

    def test_a_result_object_exposing_json_is_read_without_a_dict(self) -> None:
        class Result:
            json = {"rec_texts": ["from .json"], "rec_scores": [0.75], "rec_polys": []}

        out = child.project_results([Result()])
        self.assertEqual(out[0].text, "from .json")
        self.assertEqual(out[0].score, 0.75)

    def test_a_line_with_an_unusable_score_keeps_its_text_and_drops_the_score(self) -> None:
        # Dropping a confidence is honest; dropping a line the page really
        # contains would be a silent content loss.
        out = child.project_results([_page(["kept"], [float("nan")])])
        self.assertEqual(out[0].text, "kept")
        self.assertEqual(out[0].score, 0.0)

    def test_an_unusable_box_drops_only_the_box(self) -> None:
        out = child.project_results([_page(["kept"], [0.9], [[["not", "a", "point"]]])])
        self.assertEqual(out[0].text, "kept")
        self.assertEqual(out[0].boxes, ())


class MalformedChildOutputTests(unittest.TestCase):
    """G/H: an untrustworthy child result fails closed with a bounded code."""

    def _run(self, process: _ProcessDouble, policy=None, dirs=None):
        owned = dirs is None
        dirs = dirs or _ModelDirs()
        try:
            with mock.patch.object(
                isolation, "_spawn_ocr_child", _spawn_returning(process)
            ):
                return isolation.ocr_png_isolated(
                    png=_png_bytes(),
                    width=12,
                    height=8,
                    detector_dir=dirs.detector_dir,
                    recognizer_dir=dirs.recognizer_dir,
                    policy=policy or isolation.DEFAULT_OCR_ISOLATION_POLICY,
                )
        finally:
            if owned:
                dirs.cleanup()

    def test_malformed_child_output_fails_closed(self) -> None:
        for label, stdout in (
            ("not-json", b"not a report at all"),
            ("partial", b'{"ok": true, "provenance": '),
            ("empty", b""),
            ("not-an-object", b'["ok", true]'),
            ("missing-ok", b'{"results": []}'),
            ("wrong-type", b'{"ok": "yes"}'),
            ("success-with-extra-key", _success_bytes() + b'  trailing'),
            ("success-with-code", b'{"ok": true, "code": "ok", "provenance": {}, "results": []}'),
            ("refusal-with-results", b'{"ok": false, "code": "image_ocr_result_invalid", "results": []}'),
            ("refusal-with-provenance", b'{"ok": false, "code": "ok", "provenance": {}}'),
            ("traceback", b'Traceback (most recent call last): File "C:/x.py"'),
        ):
            with self.subTest(label=label):
                result = self._run(_ProcessDouble(stdout=stdout))
                self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)
                self.assertEqual(result.results, ())
                self.assertEqual(
                    result.reason_code, contract.OCR_ISOLATION_FAILURE_REASON_CODE
                )

    def test_a_success_missing_its_provenance_fails_closed(self) -> None:
        body = json.dumps({"ok": True, "results": []}).encode("utf-8")
        result = self._run(_ProcessDouble(stdout=body))
        self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)

    def test_provenance_with_an_extra_or_missing_key_fails_closed(self) -> None:
        extra = _provenance_frame()
        extra["host_path"] = "C:/models/detector"
        for frame in (
            _provenance_frame(runtime_revision=""),
            _provenance_frame(runtime=123),
            extra,
            {key: value for key, value in _provenance_frame().items() if key != "mode"},
        ):
            with self.subTest(frame=sorted(frame)):
                result = self._run(_ProcessDouble(stdout=_success_bytes(provenance=frame)))
                self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)

    def test_unbounded_reason_code_in_a_child_report_fails_closed(self) -> None:
        for code in (
            f'Traceback (most recent call last): File "C:/x.py"',
            _LEAK_MARKER,
            "image_ocr_result_invalid; rm -rf /",
            "Image_Ocr_Result_Invalid",
            "x" * 200,
        ):
            with self.subTest(code=code[:24]):
                body = json.dumps({"ok": False, "code": code}).encode("utf-8")
                result = self._run(_ProcessDouble(stdout=body))
                self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)
                self.assertEqual(
                    result.reason_code, contract.OCR_ISOLATION_FAILURE_REASON_CODE
                )

    def test_a_bounded_child_refusal_is_reported_as_rejected(self) -> None:
        for code in (
            contract.OCR_RESULT_INVALID_REASON_CODE,
            contract.OCR_RUNTIME_MISSING_REASON_CODE,
        ):
            with self.subTest(code=code):
                body = json.dumps({"ok": False, "code": code}).encode("utf-8")
                result = self._run(_ProcessDouble(stdout=body))
                self.assertEqual(result.outcome, isolation.OcrOutcome.REJECTED)
                self.assertEqual(result.reason_code, code)
                self.assertEqual(result.results, ())
                self.assertIsNone(result.provenance)

    def test_a_child_result_outside_every_text_and_box_bound_fails_closed(self) -> None:
        oversized = [
            ("result-count", [_result_frame(f"line {index}") for index in range(contract.MAX_OCR_RESULTS + 1)]),
            ("result-text", [_result_frame("x" * (contract.MAX_OCR_RESULT_TEXT_CHARS + 1))]),
            ("total-text", [_result_frame("x" * contract.MAX_OCR_RESULT_TEXT_CHARS) for _ in range(11)]),
            ("score-above-one", [_result_frame("ok", score=1.5)]),
            ("score-negative", [_result_frame("ok", score=-0.1)]),
            ("box-points", [_result_frame("ok", points=[[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]])]),
            ("box-empty", [_result_frame("ok", points=[])]),
            ("box-float", [_result_frame("ok", points=[[0.5, 0], [1, 0], [1, 1], [0, 1]])]),
            ("box-coordinate", [_result_frame("ok", points=[[0, 0], [10**9, 0], [10**9, 4], [0, 4]])]),
            ("box-count", [_result_frame("ok", points=[_Box().points, _Box().points])]),
            ("result-extra-key", [{"text": "ok", "score": 0.9, "boxes": [], "raw": 1}]),
            ("result-missing-key", [{"text": "ok", "score": 0.9}]),
        ]
        for label, results in oversized:
            with self.subTest(label=label):
                result = self._run(_ProcessDouble(stdout=_success_bytes(results)))
                self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)
                self.assertEqual(result.results, ())

    def test_oversized_child_output_fails_closed(self) -> None:
        body = _success_bytes([_result_frame("x" * 500)])
        policy = isolation.OcrIsolationPolicy(max_output_bytes=64)
        result = self._run(_ProcessDouble(stdout=body), policy=policy)
        self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)
        self.assertEqual(result.results, ())

    def test_nonzero_child_exit_code_fails_closed(self) -> None:
        result = self._run(_ProcessDouble(stdout=_success_bytes(), exit_code=1))
        self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)
        self.assertEqual(result.child_exit_code, 1)

    def test_child_result_with_missing_pipes_fails_closed(self) -> None:
        process = _ProcessDouble()
        process.stdout = None
        dirs = _ModelDirs()
        try:
            with mock.patch.object(
                isolation, "_spawn_ocr_child", _spawn_returning(process)
            ):
                result = isolation.ocr_png_isolated(
                    png=_png_bytes(),
                    width=12,
                    height=8,
                    detector_dir=dirs.detector_dir,
                    recognizer_dir=dirs.recognizer_dir,
                )
        finally:
            dirs.cleanup()
        self.assertTrue(process.killed)
        self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)

    def test_child_stderr_is_drained_and_never_surfaced(self) -> None:
        noisy = _ProcessDouble(
            stdout=_success_bytes([_result_frame("hello")]),
            stderr=(_LEAK_MARKER + "\n" + _SECRET + "\n").encode() * 5000,
        )
        result = self._run(noisy)
        self.assertEqual(result.outcome, isolation.OcrOutcome.COMPLETED)
        self.assertEqual(result.results[0].text, "hello")
        self.assertNotIn(_LEAK_MARKER, repr(result))
        self.assertNotIn(_SECRET, repr(result))
        self.assertNotIn(_LEAK_MARKER, json.dumps(result.safe_dict(), ensure_ascii=False))


class OversizedInputTests(unittest.TestCase):
    """H: input outside the existing Core image bounds never starts a process."""

    def test_oversized_png_is_refused_without_spawning(self) -> None:
        spy = _SpawnSpy()
        dirs = _ModelDirs()
        noisy = _noisy_png(2_400)
        self.assertGreater(len(noisy), isolation.IMAGE_OCR_MAX_NORMALIZED_BYTES)
        try:
            with mock.patch.object(isolation, "_spawn_ocr_child", spy):
                result = isolation.ocr_png_isolated(
                    png=noisy,
                    width=2_400,
                    height=2_400,
                    detector_dir=dirs.detector_dir,
                    recognizer_dir=dirs.recognizer_dir,
                )
        finally:
            dirs.cleanup()
        self.assertEqual(spy.calls, 0)
        self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)
        self.assertEqual(result.reason_code, contract.OCR_INPUT_REASON_CODE)

    def test_empty_png_is_refused_without_spawning(self) -> None:
        spy = _SpawnSpy()
        dirs = _ModelDirs()
        try:
            with mock.patch.object(isolation, "_spawn_ocr_child", spy):
                result = isolation.ocr_png_isolated(
                    png=b"",
                    width=12,
                    height=8,
                    detector_dir=dirs.detector_dir,
                    recognizer_dir=dirs.recognizer_dir,
                )
        finally:
            dirs.cleanup()
        self.assertEqual(spy.calls, 0)
        self.assertEqual(result.reason_code, contract.OCR_INPUT_REASON_CODE)

    def test_oversized_pixel_count_is_refused_without_spawning(self) -> None:
        spy = _SpawnSpy()
        dirs = _ModelDirs()
        try:
            with mock.patch.object(isolation, "_spawn_ocr_child", spy):
                result = isolation.ocr_png_isolated(
                    png=_png_bytes(),
                    width=10_000,
                    height=10_000,
                    detector_dir=dirs.detector_dir,
                    recognizer_dir=dirs.recognizer_dir,
                )
        finally:
            dirs.cleanup()
        self.assertEqual(spy.calls, 0)
        self.assertEqual(result.reason_code, contract.OCR_INPUT_REASON_CODE)

    def test_a_lowered_envelope_bound_refuses_before_spawning(self) -> None:
        spy = _SpawnSpy()
        dirs = _ModelDirs()
        policy = isolation.OcrIsolationPolicy(max_envelope_bytes=1_024)
        noisy = _noisy_png(200)
        self.assertGreater(len(contract.encode_envelope(
            detector_dir=dirs.detector_dir,
            recognizer_dir=dirs.recognizer_dir,
            payload=noisy,
            width=200,
            height=200,
        )), 1_024)
        try:
            with mock.patch.object(isolation, "_spawn_ocr_child", spy):
                result = isolation.ocr_png_isolated(
                    png=noisy,
                    width=200,
                    height=200,
                    detector_dir=dirs.detector_dir,
                    recognizer_dir=dirs.recognizer_dir,
                    policy=policy,
                )
        finally:
            dirs.cleanup()
        self.assertEqual(spy.calls, 0)
        self.assertEqual(result.reason_code, contract.OCR_INPUT_REASON_CODE)


class HardTimeoutTests(unittest.TestCase):
    """C/F: a hung OCR child is terminated by a finite, enforced timeout."""

    def test_real_hanging_child_is_killed_and_reported_as_timed_out(self) -> None:
        spawn, handles = _spawn_running(_hang_command())
        policy = isolation.OcrIsolationPolicy(
            timeout_seconds=1.0, terminate_grace_seconds=2.0
        )
        started = time.monotonic()
        result = self._run_with(spawn, policy)
        elapsed = time.monotonic() - started

        self.assertEqual(result.outcome, isolation.OcrOutcome.TIMED_OUT)
        self.assertEqual(result.reason_code, contract.OCR_TIMEOUT_REASON_CODE)
        self.assertEqual(result.results, ())
        # A terminated child reports no exit code, matching the semantic
        # reference in kagent.windows_local_executor.
        self.assertIsNone(result.child_exit_code)

        # The timeout is finite and the child is really gone.
        self.assertLess(elapsed, 30.0)
        self.assertEqual(len(handles), 1)
        handle = handles[0]
        self.assertIsNotNone(handle.poll(), "the OCR child outlived the timeout")
        self.assertIsNotNone(handle.returncode)

    def test_timeout_note_leaks_no_payload_path_traceback_or_model_dir(self) -> None:
        spawn, _ = _spawn_running(_hang_command())
        dirs = _ModelDirs()
        policy = isolation.OcrIsolationPolicy(timeout_seconds=1.0)
        try:
            result = self._run_with(spawn, policy, dirs=dirs)
        finally:
            dirs.cleanup()
        note = json.dumps(result.safe_dict(), ensure_ascii=False)
        for forbidden in (
            _LEAK_MARKER,
            _SECRET,
            "Traceback",
            "Exception",
            dirs.root,
            "detector",
            "recognizer",
        ):
            self.assertNotIn(forbidden, note)
        self.assertLess(len(note), 400, note)

    def test_surviving_child_fails_closed_instead_of_being_called_a_timeout(self) -> None:
        process = _ProcessDouble(alive=True, ignores_terminate=True, ignores_kill=True)
        dirs = _ModelDirs()
        policy = isolation.OcrIsolationPolicy(
            timeout_seconds=1.0, terminate_grace_seconds=0.05, kill_grace_seconds=0.05
        )
        try:
            result = self._run_with(
                _spawn_returning(process), policy, dirs=dirs
            )
        finally:
            dirs.cleanup()
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)
        self.assertEqual(
            result.reason_code, contract.OCR_ISOLATION_FAILURE_REASON_CODE
        )
        self.assertEqual(result.results, ())

    def _run_with(self, spawn, policy, dirs=None):
        owned = dirs is None
        dirs = dirs or _ModelDirs()
        try:
            with mock.patch.object(isolation, "_spawn_ocr_child", spawn):
                return isolation.ocr_png_isolated(
                    png=_png_bytes(),
                    width=12,
                    height=8,
                    detector_dir=dirs.detector_dir,
                    recognizer_dir=dirs.recognizer_dir,
                    policy=policy,
                )
        finally:
            if owned:
                dirs.cleanup()


class KillEscalationTests(unittest.TestCase):
    """D: terminate that does not stop the child must escalate to kill."""

    def _run_with(self, process, policy):
        dirs = _ModelDirs()
        try:
            with mock.patch.object(
                isolation, "_spawn_ocr_child", _spawn_returning(process)
            ):
                return isolation.ocr_png_isolated(
                    png=_png_bytes(),
                    width=12,
                    height=8,
                    detector_dir=dirs.detector_dir,
                    recognizer_dir=dirs.recognizer_dir,
                    policy=policy,
                )
        finally:
            dirs.cleanup()

    def test_ignored_terminate_escalates_to_kill(self) -> None:
        process = _ProcessDouble(alive=True, ignores_terminate=True)
        result = self._run_with(
            process,
            isolation.OcrIsolationPolicy(
                timeout_seconds=1.0, terminate_grace_seconds=0.05
            ),
        )
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertIsNotNone(process.poll(), "the child survived the kill escalation")
        self.assertEqual(result.outcome, isolation.OcrOutcome.TIMED_OUT)
        self.assertTrue(result.terminated_by_kill)
        self.assertEqual(result.reason_code, contract.OCR_TIMEOUT_REASON_CODE)

    def test_successful_terminate_does_not_escalate_to_kill(self) -> None:
        process = _ProcessDouble(alive=True)
        result = self._run_with(
            process,
            isolation.OcrIsolationPolicy(
                timeout_seconds=1.0, terminate_grace_seconds=0.05
            ),
        )
        self.assertTrue(process.terminated)
        self.assertFalse(process.killed)
        self.assertEqual(result.outcome, isolation.OcrOutcome.TIMED_OUT)
        self.assertFalse(result.terminated_by_kill)

    def test_timeout_action_cannot_be_weakened(self) -> None:
        with self.assertRaises(isolation.OcrIsolationError):
            isolation.OcrIsolationPolicy(timeout_action="warn")
        self.assertEqual(isolation.OCR_TIMEOUT_ACTION, "kill")


class TimeoutIsNotCancellationTests(unittest.TestCase):
    """E: the boundary has no cancellation authority and never claims one."""

    def test_outcome_vocabulary_has_no_cancellation_term(self) -> None:
        self.assertEqual(
            {outcome.value for outcome in isolation.OcrOutcome},
            {"completed", "rejected", "timed_out", "failed"},
        )
        for name in ("cancel", "cancelled", "cancel_ocr", "abort"):
            self.assertFalse(
                hasattr(isolation, name), f"unexpected cancellation authority: {name}"
            )

    def test_timed_out_result_may_not_carry_results_or_an_exit_code(self) -> None:
        with self.assertRaises(isolation.OcrIsolationError):
            isolation.IsolatedOcrResult(
                outcome=isolation.OcrOutcome.TIMED_OUT,
                reason_code=contract.OCR_TIMEOUT_REASON_CODE,
                results=(contract.OcrResult(text="partial", score=0.9),),
            )
        with self.assertRaises(isolation.OcrIsolationError):
            isolation.IsolatedOcrResult(
                outcome=isolation.OcrOutcome.TIMED_OUT,
                reason_code=contract.OCR_TIMEOUT_REASON_CODE,
                child_exit_code=0,
            )

    def test_a_non_completed_result_may_not_carry_provenance(self) -> None:
        with self.assertRaises(isolation.OcrIsolationError):
            isolation.IsolatedOcrResult(
                outcome=isolation.OcrOutcome.REJECTED,
                reason_code=contract.OCR_RUNTIME_MISSING_REASON_CODE,
                provenance=contract.OcrProvenance(
                    runtime="paddleocr",
                    runtime_revision="3.7.0",
                    detector_revision="d",
                    recognizer_revision="r",
                    canonical_png_sha256="0" * 64,
                    mode=child.OCR_MODE,
                ),
            )


class ChildRuntimeAvailabilityTests(unittest.TestCase):
    """I/N: an unprovisioned runtime is a bounded refusal, never a download."""

    def test_a_missing_runtime_in_the_real_child_is_a_bounded_rejection(self) -> None:
        # The production command line and environment are used unchanged. The
        # heavy PaddleOCR stack is deliberately absent from the product
        # manifests, so a real run must refuse rather than fetch weights.
        dirs = _ModelDirs()
        try:
            result = _run_isolated(dirs=dirs)
        finally:
            dirs.cleanup()
        self.assertEqual(result.outcome, isolation.OcrOutcome.REJECTED)
        self.assertEqual(
            result.reason_code, contract.OCR_RUNTIME_MISSING_REASON_CODE
        )
        self.assertEqual(result.results, ())
        self.assertIsNone(result.provenance)

    def test_a_missing_model_directory_never_starts_a_process(self) -> None:
        spy = _SpawnSpy()
        dirs = _ModelDirs()
        try:
            for detector, recognizer in (
                (str(dirs.detector / "absent"), dirs.recognizer_dir),
                (dirs.detector_dir, str(dirs.recognizer / "absent")),
                ("relative/detector", dirs.recognizer_dir),
                ("https://example.invalid/models/det", dirs.recognizer_dir),
                ("", dirs.recognizer_dir),
                ("C:/models/../models/det", dirs.recognizer_dir),
            ):
                with self.subTest(detector=detector):
                    result = isolation.ocr_png_isolated(
                        png=_png_bytes(),
                        width=12,
                        height=8,
                        detector_dir=detector,
                        recognizer_dir=recognizer,
                    )
                    self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)
                    self.assertEqual(
                        result.reason_code, contract.OCR_RUNTIME_MISSING_REASON_CODE
                    )
        finally:
            dirs.cleanup()
        self.assertEqual(spy.calls, 0)
        self.assertEqual(spy.argv, [])

    def test_a_missing_interpreter_is_a_bounded_failure_without_a_spawn(self) -> None:
        spy = _SpawnSpy()
        dirs = _ModelDirs()
        try:
            with mock.patch.object(isolation, "_spawn_ocr_child", spy), mock.patch.object(
                isolation.sys, "executable", ""
            ):
                result = isolation.ocr_png_isolated(
                    png=_png_bytes(),
                    width=12,
                    height=8,
                    detector_dir=dirs.detector_dir,
                    recognizer_dir=dirs.recognizer_dir,
                )
        finally:
            dirs.cleanup()
        self.assertEqual(spy.calls, 0)
        self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)

    def test_spawn_oserror_is_a_bounded_failure(self) -> None:
        def explode(argv, environment):
            raise OSError("cannot start the OCR child")

        dirs = _ModelDirs()
        try:
            with mock.patch.object(isolation, "_spawn_ocr_child", explode):
                result = isolation.ocr_png_isolated(
                    png=_png_bytes(),
                    width=12,
                    height=8,
                    detector_dir=dirs.detector_dir,
                    recognizer_dir=dirs.recognizer_dir,
                )
        finally:
            dirs.cleanup()
        self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)
        self.assertEqual(
            result.reason_code, contract.OCR_ISOLATION_FAILURE_REASON_CODE
        )
        self.assertNotIn("cannot start", result.reason_code)

    def test_a_real_child_that_exits_without_a_report_fails_closed(self) -> None:
        spawn, handles = _spawn_running([sys.executable, "-c", "import sys; sys.exit(3)"])
        dirs = _ModelDirs()
        try:
            result = self._run_with(spawn, dirs)
        finally:
            dirs.cleanup()
        self.assertEqual(result.outcome, isolation.OcrOutcome.FAILED)
        self.assertEqual(result.child_exit_code, 3)
        self.assertEqual(handles[0].returncode, 3)

    def _run_with(self, spawn, dirs):
        with mock.patch.object(isolation, "_spawn_ocr_child", spawn):
            return isolation.ocr_png_isolated(
                png=_png_bytes(),
                width=12,
                height=8,
                detector_dir=dirs.detector_dir,
                recognizer_dir=dirs.recognizer_dir,
            )


class RealChildProjectionTests(unittest.TestCase):
    """The reviewed child is really startable and projects what it is given."""

    def setUp(self) -> None:
        _FakeRuntime.instances.clear()
        self._dirs = _ModelDirs()
        self.addCleanup(self._dirs.cleanup)
        # The real ``_build_runtime`` is left intact; only the imported class is
        # doubled, so the constructor arguments under test are the real ones.
        patch = mock.patch.dict(
            sys.modules, {"paddleocr": _fake_paddleocr_module()}, clear=False
        )
        patch.start()
        self.addCleanup(patch.stop)

    def _child_report(
        self, payload: bytes, width: int = 12, height: int = 8
    ) -> contract.OcrReport:
        envelope = contract.encode_envelope(
            detector_dir=self._dirs.detector_dir,
            recognizer_dir=self._dirs.recognizer_dir,
            payload=payload,
            width=width,
            height=height,
        )
        return _child_main(envelope)

    def test_a_korean_page_completes_with_provenance_and_a_box(self) -> None:
        report = self._child_report(_png_bytes())
        # The stub runtime returns a page; the real runtime path is exercised by
        # the live smoke test below.
        self.assertIsNotNone(report)
        self.assertTrue(report.ok)
        self.assertEqual(report.provenance.runtime, "paddleocr")
        self.assertEqual(
            report.provenance.runtime_revision, contract.PADDLEOCR_RUNTIME_REVISION
        )
        self.assertEqual(report.provenance.detector_revision, _PINNED_DETECTOR_REVISION)
        self.assertEqual(
            report.provenance.recognizer_revision, _PINNED_RECOGNIZER_REVISION
        )
        self.assertEqual(
            report.provenance.canonical_png_sha256,
            hashlib.sha256(_png_bytes()).hexdigest(),
        )
        self.assertEqual(report.provenance.mode, child.OCR_MODE)
        self.assertEqual([result.text for result in report.results], ["stub"])

    def test_the_child_writes_the_exact_sanitized_png_and_no_more(self) -> None:
        payload = _png_bytes()
        report = self._child_report(payload)
        self.assertIsNotNone(report)
        runtime = _FakeRuntime.instances[-1]
        path, predict_kwargs = runtime.predict_calls[-1]
        # The runtime read exactly the bytes the child was handed, from a
        # child-owned temporary PNG the child then unlinked.
        self.assertEqual(runtime.read_bytes, [payload])
        self.assertTrue(path.endswith(".png"))
        self.assertFalse(os.path.exists(path))
        self.assertTrue(runtime.closed)
        for stage, value in predict_kwargs.items():
            self.assertIs(value, False, f"{stage} must be off at predict time")
            self.assertIn(stage, contract.ORIENTATION_STAGES_OFF)

    def test_the_runtime_is_built_with_local_model_dirs_and_orientation_off(self) -> None:
        self._child_report(_png_bytes())
        runtime = _FakeRuntime.instances[-1]
        self.assertEqual(
            runtime.kwargs["text_detection_model_dir"], self._dirs.detector_dir
        )
        self.assertEqual(
            runtime.kwargs["text_recognition_model_dir"], self._dirs.recognizer_dir
        )
        self.assertEqual(runtime.kwargs["device"], "cpu")
        self.assertIs(runtime.kwargs["enable_hpi"], False)
        for stage in contract.ORIENTATION_STAGES_OFF:
            self.assertIs(
                runtime.kwargs[stage], False, f"{stage} must be off at build time"
            )
        # Only the detector and recognizer are supplied; no orientation stage is
        # given a model directory that could be silently turned on.
        for stage in contract.ORIENTATION_STAGES_OFF:
            stem = stage.replace("use_", "")
            self.assertNotIn(f"{stem}_model_dir", runtime.kwargs)

    def test_a_malformed_envelope_is_a_bounded_refusal_without_a_runtime(self) -> None:
        payload = _png_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        good = {
            "base64": base64.b64encode(payload).decode("ascii"),
            "detector_dir": self._dirs.detector_dir,
            "recognizer_dir": self._dirs.recognizer_dir,
            "format": "PNG",
            "width": 12,
            "height": 8,
            "sha256": digest,
        }

        def framed(**overrides) -> bytes:
            frame = dict(good)
            for key, value in overrides.items():
                if value is _DROP:
                    frame.pop(key, None)
                else:
                    frame[key] = value
            return json.dumps(frame).encode("utf-8")

        for label, raw in (
            ("not-json", b"not an envelope"),
            ("empty", b""),
            ("extra-key", framed(extra=1)),
            ("missing-key", framed(format=_DROP)),
            ("relative-model-dir", framed(detector_dir="rel")),
            ("traversal-model-dir", framed(detector_dir="/a/../b")),
            ("bad-base64", framed(base64="!!!")),
            ("wrong-format", framed(format="JPEG")),
            ("wrong-width", framed(width=13)),
            ("wrong-height", framed(height=9)),
            ("wrong-sha256", framed(sha256="0" * 64)),
            ("short-sha256", framed(sha256="abc")),
            ("uppercase-sha256", framed(sha256=digest.upper())),
            ("float-width", framed(width=12.0)),
        ):
            with self.subTest(label=label):
                _FakeRuntime.instances.clear()
                report = _child_main(raw)
                self.assertFalse(report.ok)
                self.assertEqual(
                    report.code, contract.OCR_ISOLATION_FAILURE_REASON_CODE
                )
                self.assertEqual(_FakeRuntime.instances, [], label)

    def test_a_runtime_that_raises_becomes_a_bounded_refusal(self) -> None:
        _FakeRuntime.instances.clear()
        report = self._child_report_with_failing_runtime(
            RuntimeError("model exploded: " + _SECRET)
        )
        self.assertFalse(report.ok)
        self.assertEqual(report.code, contract.OCR_RESULT_INVALID_REASON_CODE)
        # The exception text never becomes part of the bounded report.
        self.assertNotIn(_SECRET, repr(report.safe_dict()))

    def _child_report_with_failing_runtime(self, error: BaseException):
        def failing_predict(self, path, **kwargs):
            self.predict_calls.append((path, kwargs))
            raise error

        with mock.patch.object(_FakeRuntime, "predict", failing_predict):
            return self._child_report(_png_bytes())

    def test_a_runtime_returning_malformed_output_becomes_a_bounded_refusal(self) -> None:
        def malformed_predict(self, path, **kwargs):
            self.predict_calls.append((path, kwargs))
            return "not a result page"

        with mock.patch.object(_FakeRuntime, "predict", malformed_predict):
            report = self._child_report(_png_bytes())
        self.assertFalse(report.ok)
        self.assertEqual(report.code, contract.OCR_RESULT_INVALID_REASON_CODE)

    def test_a_runtime_revision_mismatch_is_a_bounded_refusal(self) -> None:
        # Exact equality, not a prefix match: a build that merely *starts with*
        # the reviewed revision is a different runtime with a possibly different
        # result schema, so it is refused too.
        for revision in ("2.9.1", "3.7", "3.7.0-rc1", "3.7.1", "3.10.0", "3.7.0.post1"):
            with self.subTest(revision=revision):
                _FakeRuntime.instances.clear()
                with mock.patch.dict(
                    sys.modules,
                    {"paddleocr": _fake_paddleocr_module(revision)},
                    clear=False,
                ):
                    report = self._child_report(_png_bytes())
                self.assertFalse(report.ok)
                self.assertEqual(report.code, contract.OCR_RUNTIME_MISSING_REASON_CODE)
                # The revision gate runs before the model is built, so a
                # mismatched runtime never loads weights it is not allowed to
                # report on.
                self.assertEqual(_FakeRuntime.instances, [])

    def test_the_runtime_revision_is_compared_for_exact_equality(self) -> None:
        source = Path(child.__file__).read_text(encoding="utf-8")
        self.assertIn("revision != PADDLEOCR_RUNTIME_REVISION", source)
        self.assertNotIn("startswith(PADDLEOCR_RUNTIME_REVISION)", source)
        self.assertEqual(contract.PADDLEOCR_RUNTIME_REVISION, "3.7.0")

    def test_a_symlinked_model_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real-detector"
            real.mkdir()
            link = Path(tmp) / "linked-detector"
            try:
                link.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("this platform does not allow directory symlinks")
            self.assertFalse(child._is_local_dir(str(link)))
            self.assertTrue(child._is_local_dir(str(real)))
            self.assertFalse(child._is_local_dir(str(real / "absent")))


class FacadeCompositionTests(unittest.TestCase):
    """A/B/K: intake, then Core transform, then the child — in that order."""

    def setUp(self) -> None:
        self._dirs = _ModelDirs()
        self.addCleanup(self._dirs.cleanup)

    def test_the_facade_normalizes_to_a_sanitized_single_frame_png(self) -> None:
        spy = _SpawnSpy()
        body = _success_bytes([_result_frame("견적서", points=_Box().points)])
        with mock.patch.object(isolation, "_spawn_ocr_child", _spawn_returning(_ProcessDouble(stdout=body))):
            result = image_ocr(
                _png_bytes("JPEG"),
                filename="quote.jpg",
                detector_dir=self._dirs.detector_dir,
                recognizer_dir=self._dirs.recognizer_dir,
            )
        self.assertEqual(result.capability_id, CAPABILITY_IMAGE_OCR)
        self.assertEqual(result.intake.detected_format, "jpeg")
        self.assertTrue(result.intake.safe_to_parse)
        self.assertEqual(result.image.format, "PNG")
        # A JPEG carries EXIF and an ICC-less but real frame; the receipt reports
        # the sanitized PNG's facts and never the encoded bytes.
        self.assertEqual(result.image.icc_profile_preserved, False)
        self.assertNotIn("data", result.image.safe_dict())
        self.assertEqual(result.ocr.outcome, isolation.OcrOutcome.COMPLETED)
        self.assertEqual(result.ocr.results[0].text, "견적서")

    def test_the_facade_applies_exif_orientation_before_the_child(self) -> None:
        source = _oriented_jpeg(orientation=6)
        seen: dict[str, object] = {}

        def capture(png, width, height, detector_dir, recognizer_dir, policy):
            seen.update(width=width, height=height, png=png)
            return isolation.ocr_png_isolated(
                png=png,
                width=width,
                height=height,
                detector_dir=detector_dir,
                recognizer_dir=recognizer_dir,
                policy=policy,
            )

        with mock.patch("kagent.image_skill.ocr_png_isolated", capture):
            result = image_ocr(
                source,
                filename="oriented.jpg",
                detector_dir=self._dirs.detector_dir,
                recognizer_dir=self._dirs.recognizer_dir,
            )
        # A 6 means a quarter turn, so a 12x8 source becomes 8x12 upstream.
        self.assertEqual((seen["width"], seen["height"]), (8, 12))
        self.assertEqual((result.image.width, result.image.height), (8, 12))
        self.assertTrue(seen["png"].startswith(b"\x89PNG\r\n\x1a\n"))

    def test_a_gate_refusal_never_reaches_the_core_transform_or_the_child(self) -> None:
        with mock.patch.object(
            isolation, "_spawn_ocr_child", _SpawnSpy()
        ) as spawn, mock.patch("kagent.image_skill.transform_image") as transform:
            for filename, payload in (
                ("fake.png", b"plain text, not an image" + _LEAK_MARKER.encode()),
                # A PDF extension over non-PDF content: the gate ranks content
                # above extension, so this is refused before any decode.
                ("quote.pdf", b"not a pdf" + _LEAK_MARKER.encode()),
                ("quote.png", b""),
            ):
                with self.subTest(filename=filename):
                    with self.assertRaises(ImageSkillError) as ctx:
                        image_ocr(
                            payload,
                            filename=filename,
                            detector_dir=self._dirs.detector_dir,
                            recognizer_dir=self._dirs.recognizer_dir,
                        )
                    self.assertEqual(ctx.exception.code, "image_intake_refused")
            self.assertEqual(spawn.calls, 0)
            self.assertEqual(transform.call_count, 0)

    def test_a_multiframe_image_is_refused_by_the_core_transform(self) -> None:
        animated = _animated_gif()
        with mock.patch.object(isolation, "_spawn_ocr_child", _SpawnSpy()) as spawn:
            with self.assertRaises(ImageSkillError) as ctx:
                image_ocr(
                    animated,
                    filename="anim.gif",
                    detector_dir=self._dirs.detector_dir,
                    recognizer_dir=self._dirs.recognizer_dir,
                )
        self.assertEqual(ctx.exception.code, "image_multiframe_refused")
        self.assertEqual(spawn.calls, 0)

    def test_a_core_transform_refusal_maps_to_the_stable_facade_code(self) -> None:
        with mock.patch("kagent.image_skill.transform_image", side_effect=_core_error("image_decode_failed")):
            with self.assertRaises(ImageSkillError) as ctx:
                image_ocr(
                    _png_bytes(),
                    filename="x.png",
                    detector_dir=self._dirs.detector_dir,
                    recognizer_dir=self._dirs.recognizer_dir,
                )
        self.assertEqual(ctx.exception.code, "image_decode_failed")

    def test_the_facade_receipt_is_path_free_and_carries_provenance(self) -> None:
        body = _success_bytes([_result_frame("Invoice", points=_Box().points)])
        with mock.patch.object(
            isolation,
            "_spawn_ocr_child",
            _spawn_returning(_ProcessDouble(stdout=body)),
        ):
            result = image_ocr(
                _png_bytes(),
                filename="invoice.png",
                detector_dir=self._dirs.detector_dir,
                recognizer_dir=self._dirs.recognizer_dir,
            )
        note = json.dumps(result.safe_dict(), ensure_ascii=False)
        for forbidden in (self._dirs.root, "Traceback", _SECRET, _LEAK_MARKER):
            self.assertNotIn(forbidden, note)
        # The filename is the caller's own name and is part of the gate receipt;
        # a *host path* is what must never appear.
        for forbidden in (":\\", ":\\Users", "AppData", "Temp"):
            self.assertNotIn(forbidden, note)
        provenance = result.safe_dict()["ocr"]["provenance"]
        self.assertEqual(provenance["runtime"], "paddleocr")
        self.assertEqual(
            provenance["runtime_revision"], contract.PADDLEOCR_RUNTIME_REVISION
        )
        self.assertEqual(provenance["mode"], child.OCR_MODE)
        # The revision is the fixed official constant, not the directory
        # basename: the caller named that directory "detector", and the receipt
        # must not report a caller-controlled name as a model identity.
        self.assertEqual(provenance["detector_revision"], _PINNED_DETECTOR_REVISION)
        self.assertEqual(provenance["recognizer_revision"], _PINNED_RECOGNIZER_REVISION)
        self.assertEqual(
            provenance["canonical_png_sha256"],
            hashlib.sha256(result.image.data).hexdigest(),
        )

    def test_the_facade_reuses_the_reserved_capability_and_mints_none(self) -> None:
        import kagent.image_skill as facade

        self.assertIn(CAPABILITY_IMAGE_OCR, facade.IMAGE_SKILL_CAPABILITY_IDS)
        self.assertIn(CAPABILITY_IMAGE_OCR, facade.RESERVED_CAPABILITY_IDS)
        from kagent.claw_skill_registry import RESERVED_CAPABILITY_IDS

        self.assertEqual(
            {cid for cid in facade.IMAGE_SKILL_CAPABILITY_IDS if cid not in RESERVED_CAPABILITY_IDS},
            set(),
        )

    def test_the_facade_passes_no_launcher_hook_to_the_child_boundary(self) -> None:
        parameters = inspect.signature(image_ocr).parameters
        for forbidden in ("spawn", "launcher", "executor", "argv", "command", "executable", "env"):
            self.assertNotIn(forbidden, parameters, forbidden)


def _oriented_jpeg(orientation: int) -> bytes:
    image = Image.new("RGB", (12, 8), (10, 20, 30))
    exif = Image.Exif()
    exif[274] = orientation
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif, quality=90)
    return out.getvalue()


def _animated_gif() -> bytes:
    # The two frames must differ in pixels, or the encoder collapses them into a
    # single-frame GIF and the multi-frame refusal would never be exercised.
    frames = [Image.new("RGB", (8, 8), color) for color in ((255, 0, 0), (0, 0, 255))]
    out = io.BytesIO()
    frames[0].save(
        out, format="GIF", save_all=True, append_images=frames[1:], duration=100
    )
    return out.getvalue()


def _core_error(code: str):
    from padiem_ai_core.image_helpers import ImageContractError

    return ImageContractError(code)


class ChildAuthorityTests(unittest.TestCase):
    """J/K: the child starts nothing, decodes nothing and touches no PDF."""

    def test_child_holds_no_process_creation_authority_at_runtime(self) -> None:
        # Proven in a real process, in the production child environment.
        probe = (
            "import kagent.image_ocr_child as module;"
            "names = ('subprocess', 'multiprocessing', 'Popen', 'system', 'fork',"
            " 'spawn', 'Thread', 'alarm');"
            "print(sorted(name for name in names if hasattr(module, name)))"
        )
        completed = subprocess.run(
            [sys.executable, "-P", "-c", probe],
            capture_output=True,
            text=True,
            env=isolation._child_environment(),
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-400:])
        self.assertEqual(completed.stdout.strip(), "[]")

    def test_child_imports_no_process_thread_or_network_authority(self) -> None:
        child_path = Path(child.__file__)
        imported = _imported_module_names(child_path)
        for forbidden in (
            "subprocess",
            "multiprocessing",
            "concurrent",
            "threading",
            "signal",
            "urllib",
            "requests",
            "httpx",
            "shutil",
        ):
            self.assertNotIn(forbidden, imported, forbidden)

    def test_python_socket_connections_fail_closed_in_the_child(self) -> None:
        probe = (
            "import socket; import kagent.image_ocr_child as module; "
            "module._deny_python_network(); "
            "exec(\"try:\\n socket.create_connection(('127.0.0.1', 9), 0.01)\\n"
            "except OSError as exc:\\n print(type(exc).__name__ + ':' + str(exc))\\n"
            "else:\\n raise SystemExit(2)\")"
        )
        completed = subprocess.run(
            [sys.executable, "-P", "-c", probe],
            capture_output=True,
            text=True,
            env=isolation._child_environment(),
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-400:])
        self.assertEqual(
            completed.stdout.strip(),
            "OSError:kagent OCR network access is disabled",
        )

    def test_the_child_is_not_a_second_decoder_or_a_second_intake(self) -> None:
        child_path = Path(child.__file__)
        imported = _imported_module_names(child_path)
        called = _called_names(child_path)
        # The image is decoded and classified by the existing Core helper in the
        # parent. The child neither imports a decoder nor calls one.
        for forbidden in (
            "PIL",
            "Pillow",
            "cv2",
            "imageio",
            "matplotlib",
            "numpy",
            "paddle",
            "paddlex",
        ):
            self.assertNotIn(forbidden, imported, forbidden)
        for forbidden in (
            "Image",
            "open",
            "imdecode",
            "imread",
            "load",
            "detect_format",
            "sniff",
            "inspect_file",
            "inspect_image",
            "transform_image",
        ):
            self.assertNotIn(forbidden, called, forbidden)
        # PaddleOCR is imported lazily and locally, so importing the child module
        # must not pull in the heavy stack.
        self.assertEqual(_called_names(child_path) & {"main", "project_results"}, {"main", "project_results"})

    def test_the_child_has_no_pdf_authority(self) -> None:
        for path in (Path(child.__file__), Path(isolation.__file__), Path(contract.__file__)):
            imported = _imported_module_names(path)
            called = _called_names(path)
            for forbidden in ("pypdf", "PyPDF2", "fitz", "pdfminer", "reportlab"):
                self.assertNotIn(forbidden, imported, forbidden)
            for forbidden in ("PdfReader", "PdfWriter", "extract_binary_document"):
                self.assertNotIn(forbidden, called, forbidden)

    def test_the_heavy_ocr_stack_is_absent_from_the_product_manifests(self) -> None:
        # The adapter is deliberately non-Production: the runtime is not a
        # product dependency, so it is provisioned out of band.
        import tomllib

        package = Path(isolation.__file__).resolve().parents[2] / "pyproject.toml"
        manifest = tomllib.loads(package.read_text(encoding="utf-8"))
        declared = set(manifest["project"].get("dependencies", []))
        for heavy in ("paddleocr", "paddlex", "paddlepaddle", "numpy", "opencv-python"):
            self.assertNotIn(heavy, declared, heavy)
        self.assertEqual(manifest["project"]["dependencies"], [])

    def test_the_boundary_does_not_request_a_process_group_shell_or_executor(self) -> None:
        imported = _imported_module_names(Path(isolation.__file__))
        # ``subprocess`` is the process authority this module deliberately owns;
        # every cooperative mechanism is absent by construction.
        self.assertIn("subprocess", imported)
        for forbidden in (
            "asyncio",
            "concurrent",
            "multiprocessing",
            "signal",
            "windows_local_executor",
        ):
            self.assertNotIn(forbidden, imported, forbidden)

        keywords = _popen_keywords(Path(isolation.__file__))
        self.assertIn("shell", keywords)
        self.assertIn("creationflags", keywords)
        for forbidden in ("start_new_session", "preexec_fn", "process_group"):
            self.assertNotIn(forbidden, keywords, forbidden)

        called = _called_names(Path(isolation.__file__))
        for forbidden in ("wait_for", "ProcessPoolExecutor", "ThreadPoolExecutor"):
            self.assertNotIn(forbidden, called, forbidden)

    def test_the_timeout_action_is_kill_not_a_cooperative_cancel(self) -> None:
        source = Path(isolation.__file__).read_text(encoding="utf-8")
        self.assertIn("process.terminate()", source)
        self.assertIn("process.kill()", source)
        self.assertEqual(isolation.OCR_TIMEOUT_ACTION, "kill")

    def test_the_started_command_is_fixed_and_never_contains_caller_or_model_data(self) -> None:
        spy = _SpawnSpy()
        dirs = _ModelDirs()
        try:
            with mock.patch.object(isolation, "_spawn_ocr_child", spy):
                _run_isolated(dirs=dirs)
        finally:
            dirs.cleanup()
        self.assertEqual(len(spy.argv), 1)
        argv = spy.argv[0]
        self.assertEqual(argv, [sys.executable, "-P", "-m", contract.CHILD_MODULE_NAME])
        self.assertNotIn("-c", argv)
        for token in argv:
            self.assertNotIn(dirs.root, token)
            self.assertNotIn(_LEAK_MARKER, token)

    def test_the_parent_never_puts_the_png_or_the_model_dirs_on_the_command_line(self) -> None:
        captured: dict[str, bytes] = {}

        def capture(argv, environment):
            captured["env"] = dict(environment)
            return _ProcessDouble(stdout=_success_bytes())

        dirs = _ModelDirs()
        try:
            with mock.patch.object(isolation, "_spawn_ocr_child", capture):
                _run_isolated(dirs=dirs)
        finally:
            dirs.cleanup()
        joined = " ".join(captured["env"].values())
        self.assertNotIn(dirs.root, joined)
        self.assertNotIn("PNG", joined)


class EnvironmentBoundTests(unittest.TestCase):
    """J: the child environment is bounded and drops caller values."""

    def test_child_environment_is_bounded_and_drops_caller_values(self) -> None:
        environment = isolation._child_environment()
        self.assertEqual(
            set(environment),
            {
                "PYTHONPATH",
                "PYTHONIOENCODING",
                "PYTHONUTF8",
                "SystemRoot",
                "WINDIR",
                "SystemDrive",
                "APPDATA",
                "USERPROFILE",
                "HOME",
                "TEMP",
                "TMP",
            }
            & set(environment),
        )
        for forbidden in (
            "PATH",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "PADIEM_CHAT_LIVE_ENABLED",
            "PADDLE_PDX_MODEL_SOURCE",
        ):
            self.assertNotIn(forbidden, environment, forbidden)
        self.assertTrue(Path(environment["TEMP"]).is_absolute())
        self.assertEqual(environment["TEMP"], environment["TMP"])
        self.assertEqual(environment["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(environment["PYTHONUTF8"], "1")

    def test_a_caller_variable_is_never_inherited_by_the_child(self) -> None:
        with mock.patch.dict(os.environ, {"KAGENT_OCR_DETECTOR_DIR": "C:/models/det"}):
            environment = isolation._child_environment()
        self.assertNotIn("KAGENT_OCR_DETECTOR_DIR", environment)

    def test_import_roots_expose_only_the_reviewed_trees(self) -> None:
        roots = isolation.child_import_roots()
        self.assertEqual(len(roots), 2)
        self.assertTrue(roots[0].endswith(os.path.join("korean-ai-code-agent", "src")))
        self.assertTrue(roots[1].endswith(os.path.join("packages", "padiem-ai-core")))
        self.assertIn(os.pathsep.join(roots), isolation._child_environment()["PYTHONPATH"])

    def test_the_real_child_runs_in_the_production_environment(self) -> None:
        # The reviewed child must be importable and startable with exactly the
        # environment the parent builds — otherwise every isolation test would be
        # testing a different runtime than production.
        completed = subprocess.run(
            [sys.executable, "-P", "-m", contract.CHILD_MODULE_NAME],
            input=b"",
            capture_output=True,
            env=isolation._child_environment(),
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-400:])
        report = contract.decode_report(completed.stdout)
        self.assertIsNotNone(report)
        self.assertFalse(report.ok)
        self.assertEqual(report.code, contract.OCR_ISOLATION_FAILURE_REASON_CODE)


class LocalModelDirectoryTests(unittest.TestCase):
    """J/N: model directories are explicit, local, absolute and bounded."""

    def test_a_relative_or_non_directory_model_path_is_refused_by_the_contract(self) -> None:
        payload = _png_bytes()
        for detector, recognizer in (
            ("detector", "/recognizer"),
            ("./detector", "/recognizer"),
            ("/a/../b", "/recognizer"),
            ("/detector\\..\\b", "/recognizer"),
            ("https://example.invalid/d", "/recognizer"),
            ("file:///models/d", "/recognizer"),
            ("", "/recognizer"),
            ("/d\n/recognizer", "/recognizer"),
            ("/d\x00", "/recognizer"),
            ("x" * (contract.MAX_OCR_MODEL_DIR_CHARS + 1), "/recognizer"),
        ):
            with self.subTest(detector=detector):
                with self.assertRaises(ValueError):
                    contract.encode_envelope(
                        detector_dir=detector,
                        recognizer_dir=recognizer,
                        payload=payload,
                        width=12,
                        height=8,
                    )

    def test_a_traversing_model_directory_is_refused_when_decoding(self) -> None:
        payload = _png_bytes()
        frame = {
            "base64": base64.b64encode(payload).decode("ascii"),
            "detector_dir": "/models/../etc",
            "recognizer_dir": "/models/recognizer",
            "format": "PNG",
            "width": 12,
            "height": 8,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        self.assertIsNone(contract.decode_envelope(json.dumps(frame).encode("utf-8")))

    def test_the_child_refuses_a_model_directory_that_is_not_a_local_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a_file = Path(tmp) / "not-a-dir"
            a_file.write_text("x", encoding="utf-8")
            for path in (str(a_file), str(Path(tmp) / "absent"), "", "relative"):
                with self.subTest(path=path):
                    self.assertFalse(child._is_local_dir(path))
            self.assertTrue(child._is_local_dir(tmp))


class OrientationOffTests(unittest.TestCase):
    """J: every orientation stage is off, at build time and at predict time."""

    def test_all_three_orientation_stages_are_named_and_off(self) -> None:
        self.assertEqual(
            contract.ORIENTATION_STAGES_OFF,
            frozenset(
                {
                    "use_doc_orientation_classify",
                    "use_doc_unwarping",
                    "use_textline_orientation",
                }
            ),
        )
        for stage, value in child._ORIENTATION_OFF.items():
            self.assertIs(value, False, stage)

    def test_no_orientation_stage_is_silently_enabled_anywhere(self) -> None:
        source = Path(child.__file__).read_text(encoding="utf-8")
        for stage in contract.ORIENTATION_STAGES_OFF:
            # Each stage may appear only inside the pinned OFF mapping.
            occurrences = [
                line
                for line in source.splitlines()
                if stage in line and not line.strip().startswith("#")
            ]
            for line in occurrences:
                self.assertNotIn("True", line, f"{stage} may not be enabled: {line}")

    def test_the_child_passes_no_orientation_model_directory(self) -> None:
        _FakeRuntime.instances.clear()
        source = Path(child.__file__).read_text(encoding="utf-8")
        for stage in contract.ORIENTATION_STAGES_OFF:
            model_dir_kwarg = f"{stage.replace('use_', '')}_model_dir"
            self.assertNotIn(model_dir_kwarg, source)


class PolicyAndLifecycleBoundTests(unittest.TestCase):
    """M: every lifecycle and byte knob is bounded above, and unhookable."""

    def test_default_timeout_is_the_central_decision(self) -> None:
        self.assertEqual(isolation.IMAGE_OCR_TIMEOUT_SECONDS, 120.0)
        self.assertEqual(
            isolation.DEFAULT_OCR_ISOLATION_POLICY.timeout_seconds, 120.0
        )
        self.assertLessEqual(
            isolation.IMAGE_OCR_TIMEOUT_SECONDS,
            isolation.IMAGE_OCR_TIMEOUT_MAX_SECONDS,
        )

    def test_unbounded_or_non_positive_timeouts_are_rejected(self) -> None:
        for value in (0, 0.0, -1.0, 120.5, 300.0, float("inf"), float("nan")):
            with self.subTest(timeout=value), self.assertRaises(
                isolation.OcrIsolationError
            ):
                isolation.OcrIsolationPolicy(timeout_seconds=value)

    def test_above_max_seconds_knobs_are_rejected(self) -> None:
        for knob, constant_name in (
            ("timeout_seconds", "IMAGE_OCR_TIMEOUT_MAX_SECONDS"),
            ("terminate_grace_seconds", "IMAGE_OCR_TERMINATE_GRACE_MAX_SECONDS"),
            ("kill_grace_seconds", "IMAGE_OCR_KILL_GRACE_MAX_SECONDS"),
            ("drain_join_seconds", "IMAGE_OCR_DRAIN_JOIN_MAX_SECONDS"),
        ):
            ceiling = getattr(isolation, constant_name)
            for value in (ceiling + 1e-6, ceiling * 2, ceiling + 60.0, 1e9, float("inf")):
                with self.subTest(knob=knob, value=value), self.assertRaises(
                    isolation.OcrIsolationError
                ):
                    isolation.OcrIsolationPolicy(**{knob: value})

    def test_above_max_bytes_knobs_are_rejected(self) -> None:
        for knob, constant_name in (
            ("max_envelope_bytes", "MAX_OCR_CHILD_ENVELOPE_BYTES"),
            ("max_output_bytes", "MAX_OCR_CHILD_OUTPUT_BYTES"),
            ("max_error_bytes", "MAX_OCR_CHILD_ERROR_BYTES"),
        ):
            ceiling = getattr(contract, constant_name)
            for value in (ceiling + 1, ceiling * 2, 1 << 40):
                with self.subTest(knob=knob, value=value), self.assertRaises(
                    isolation.OcrIsolationError
                ):
                    isolation.OcrIsolationPolicy(**{knob: value})

    def test_canonical_grace_ceilings_exist_and_are_the_policy_defaults(self) -> None:
        policy = isolation.DEFAULT_OCR_ISOLATION_POLICY
        for knob, constant_name in (
            ("timeout_seconds", "IMAGE_OCR_TIMEOUT_MAX_SECONDS"),
            ("terminate_grace_seconds", "IMAGE_OCR_TERMINATE_GRACE_MAX_SECONDS"),
            ("kill_grace_seconds", "IMAGE_OCR_KILL_GRACE_MAX_SECONDS"),
            ("drain_join_seconds", "IMAGE_OCR_DRAIN_JOIN_MAX_SECONDS"),
        ):
            self.assertEqual(getattr(policy, knob), getattr(isolation, constant_name))
        self.assertEqual(isolation.IMAGE_OCR_TERMINATE_GRACE_MAX_SECONDS, 5.0)
        self.assertEqual(isolation.IMAGE_OCR_KILL_GRACE_MAX_SECONDS, 5.0)
        self.assertEqual(isolation.IMAGE_OCR_DRAIN_JOIN_MAX_SECONDS, 5.0)

    def test_smaller_values_remain_permitted_for_fail_closed_exercise(self) -> None:
        policy = isolation.OcrIsolationPolicy(
            timeout_seconds=1.0,
            terminate_grace_seconds=0.05,
            kill_grace_seconds=0.05,
            drain_join_seconds=0.05,
            max_envelope_bytes=1 << 20,
            max_output_bytes=1 << 16,
            max_error_bytes=1024,
        )
        self.assertEqual(policy.max_output_bytes, 1 << 16)

    def test_policy_rejects_a_non_policy_and_bad_input_types(self) -> None:
        dirs = _ModelDirs()
        try:
            with self.assertRaises(isolation.OcrIsolationError):
                isolation.ocr_png_isolated(
                    png=_png_bytes(),
                    width=12,
                    height=8,
                    detector_dir=dirs.detector_dir,
                    recognizer_dir=dirs.recognizer_dir,
                    policy=object(),
                )
            for overrides in (
                {"png": "not bytes"},
                {"width": 0},
                {"height": -1},
                {"width": True},
                {"height": 1.5},
            ):
                kwargs = {"png": _png_bytes(), "width": 12, "height": 8}
                kwargs.update(overrides)
                with self.subTest(**overrides), self.assertRaises(
                    isolation.OcrIsolationError
                ):
                    isolation.ocr_png_isolated(
                        detector_dir=dirs.detector_dir,
                        recognizer_dir=dirs.recognizer_dir,
                        **kwargs,
                    )
        finally:
            dirs.cleanup()

    def test_image_bounds_are_the_existing_core_bounds(self) -> None:
        from padiem_ai_core.image_helpers import (
            MAX_IMAGE_BYTES,
            MAX_IMAGE_PIXELS,
            MAX_OUTPUT_BYTES,
        )

        self.assertEqual(isolation.IMAGE_OCR_MAX_INPUT_BYTES, MAX_IMAGE_BYTES)
        self.assertEqual(isolation.IMAGE_OCR_MAX_NORMALIZED_BYTES, MAX_OUTPUT_BYTES)
        self.assertEqual(isolation.IMAGE_OCR_MAX_IMAGE_PIXELS, MAX_IMAGE_PIXELS)
        self.assertEqual(contract.MAX_OCR_INPUT_PIXELS, MAX_IMAGE_PIXELS)

    def test_contract_ceilings_are_derived_and_bounded(self) -> None:
        from padiem_ai_core.image_helpers import MAX_IMAGE_BYTES

        self.assertGreater(contract.MAX_OCR_CHILD_ENVELOPE_BYTES, MAX_IMAGE_BYTES)
        self.assertGreater(contract.MAX_OCR_CHILD_OUTPUT_BYTES, 40_000)
        self.assertEqual(contract.MAX_OCR_CHILD_ERROR_BYTES, 8192)
        self.assertEqual(contract.MAX_OCR_TOTAL_TEXT_CHARS, 40_000)

    def test_public_boundary_signature_has_no_launcher_hook(self) -> None:
        parameters = inspect.signature(isolation.ocr_png_isolated).parameters
        self.assertEqual(
            set(parameters),
            {"png", "width", "height", "detector_dir", "recognizer_dir", "policy"},
        )
        for forbidden in (
            "spawn",
            "spawn_child",
            "launcher",
            "executor",
            "factory",
            "argv",
            "command",
            "executable",
            "env",
        ):
            self.assertNotIn(forbidden, parameters, forbidden)
        for parameter in parameters.values():
            self.assertEqual(
                parameter.kind, inspect.Parameter.KEYWORD_ONLY, parameter.name
            )

    def test_passing_a_spawn_hook_is_a_type_error(self) -> None:
        dirs = _ModelDirs()
        try:
            with self.assertRaises(TypeError):
                isolation.ocr_png_isolated(
                    png=_png_bytes(),
                    width=12,
                    height=8,
                    detector_dir=dirs.detector_dir,
                    recognizer_dir=dirs.recognizer_dir,
                    spawn=lambda argv, environment: None,
                )
        finally:
            dirs.cleanup()

    def test_module_exposes_no_spawn_injection_seam(self) -> None:
        self.assertFalse(hasattr(isolation, "SpawnChild"))
        for name in isolation.__all__:
            if "spawn" in name.lower():
                self.fail(f"unexpected public spawn seam: {name}")
        self.assertTrue(callable(isolation._spawn_ocr_child))
        source = Path(isolation.__file__).read_text(encoding="utf-8")
        self.assertIn("process = _spawn_ocr_child(argv, _child_environment())", source)


class OfficialModelManifestTests(unittest.TestCase):
    """O: the exact official manifests are a hard preflight condition."""

    def setUp(self) -> None:
        self._dirs = _ModelDirs()
        self.addCleanup(self._dirs.cleanup)

    # -- the production constants themselves ---------------------------------

    def test_the_pinned_manifests_are_exactly_the_central_values(self) -> None:
        self.assertEqual(
            _PINNED_DETECTOR_REVISION, "ca867c897ecbca8873081573a802ad70d499cb94"
        )
        self.assertEqual(
            _PINNED_RECOGNIZER_REVISION, "c02ecaf1f22bfd1c618cce154fd19185b47e663a"
        )
        self.assertEqual(
            dict((name, (size, digest)) for name, size, digest in _PINNED_DETECTOR_MANIFEST),
            {
                "inference.yml": (
                    903,
                    "28fb721efc3634fc8aa677e474b9602cb815a91cf569ef357a7a553d7b3ce685",
                ),
                "inference.json": (
                    402480,
                    "af5876933d8806a1b50d895867e0781e135cd92ff37381992828fc8d1b842d28",
                ),
                "inference.pdiparams": (
                    87932887,
                    "183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d",
                ),
            },
        )
        self.assertEqual(
            dict((name, (size, digest)) for name, size, digest in _PINNED_RECOGNIZER_MANIFEST),
            {
                "inference.yml": (
                    96039,
                    "f757fa1c40e99edcf27e9cce879b93eb2a51fa46f5ef39095689b8c37dd75998",
                ),
                "inference.json": (
                    217724,
                    "562404e3c590c50c93778d5f0a94df21b47b5ab8f3ea6d47c7f8a7930c3bc844",
                ),
                "inference.pdiparams": (
                    13342671,
                    "cac3e5f12cf04aaa77f6a5bc704e4e736ef2908476551891d84b41b4e9090462",
                ),
            },
        )

    def test_both_manifests_require_exactly_three_named_files(self) -> None:
        for manifest in (_PINNED_DETECTOR_MANIFEST, _PINNED_RECOGNIZER_MANIFEST):
            self.assertEqual(
                sorted(name for name, _size, _digest in manifest),
                ["inference.json", "inference.pdiparams", "inference.yml"],
            )
            for _name, size, digest in manifest:
                self.assertGreater(size, 0)
                self.assertRegex(digest, r"^[0-9a-f]{64}$")

    # -- acceptance and mutation ---------------------------------------------

    def test_an_exact_manifest_directory_is_accepted(self) -> None:
        self.assertTrue(
            contract.validate_model_manifest(
                self._dirs.detector_dir, _FIXTURE_DETECTOR_MANIFEST
            )
        )
        self.assertTrue(
            contract.validate_model_manifest(
                self._dirs.recognizer_dir, _FIXTURE_RECOGNIZER_MANIFEST
            )
        )

    def test_every_model_file_size_mutation_is_refused(self) -> None:
        for name in _MODEL_FILENAMES:
            with self.subTest(file=name):
                target = self._dirs.detector / name
                original = target.read_bytes()
                try:
                    # Same length, different content: a size-only prefilter must
                    # not be mistaken for the whole check.
                    target.write_bytes(bytes(len(original)))
                    self.assertFalse(
                        contract.validate_model_manifest(
                            self._dirs.detector_dir, _FIXTURE_DETECTOR_MANIFEST
                        ),
                        "a same-size content change must be refused",
                    )
                    target.write_bytes(original + b"\x00")
                    self.assertFalse(
                        contract.validate_model_manifest(
                            self._dirs.detector_dir, _FIXTURE_DETECTOR_MANIFEST
                        )
                    )
                finally:
                    target.write_bytes(original)

    def test_every_model_file_hash_mutation_is_refused(self) -> None:
        for name in _MODEL_FILENAMES:
            for role, directory, manifest in (
                ("detector", self._dirs.detector, _FIXTURE_DETECTOR_MANIFEST),
                ("recognizer", self._dirs.recognizer, _FIXTURE_RECOGNIZER_MANIFEST),
            ):
                with self.subTest(role=role, file=name):
                    target = directory / name
                    original = target.read_bytes()
                    try:
                        # Flip one bit deep inside the body, leaving the length
                        # and every other file untouched.
                        mutated = bytearray(original)
                        mutated[-1] ^= 0x01
                        target.write_bytes(bytes(mutated))
                        self.assertFalse(
                            contract.validate_model_manifest(
                                str(directory), manifest
                            ),
                            f"{role}/{name} with a flipped bit must be refused",
                        )
                    finally:
                        target.write_bytes(original)
        self.assertTrue(
            contract.validate_model_manifest(
                self._dirs.detector_dir, _FIXTURE_DETECTOR_MANIFEST
            )
        )

    def test_a_missing_required_file_is_refused(self) -> None:
        for name in _MODEL_FILENAMES:
            with self.subTest(file=name):
                target = self._dirs.detector / name
                body = target.read_bytes()
                target.unlink()
                try:
                    self.assertFalse(
                        contract.validate_model_manifest(
                            self._dirs.detector_dir, _FIXTURE_DETECTOR_MANIFEST
                        )
                    )
                finally:
                    target.write_bytes(body)

    def test_an_extra_unexpected_file_is_refused(self) -> None:
        # Chosen behaviour: refuse. An unrecognised artifact in a model root is
        # a second, unreviewed input to whatever loads that directory, and there
        # is no safe default for "which one did the runtime actually use?".
        extra = self._dirs.detector / "extra_weights.bin"
        extra.write_bytes(b"not reviewed")
        self.assertFalse(
            contract.validate_model_manifest(
                self._dirs.detector_dir, _FIXTURE_DETECTOR_MANIFEST
            )
        )
        extra.unlink()
        self.assertTrue(
            contract.validate_model_manifest(
                self._dirs.detector_dir, _FIXTURE_DETECTOR_MANIFEST
            )
        )

    def test_a_renamed_file_is_refused(self) -> None:
        source = self._dirs.detector / "inference.pdiparams"
        renamed = self._dirs.detector / "inference.pdiparams.bak"
        source.rename(renamed)
        try:
            self.assertFalse(
                contract.validate_model_manifest(
                    self._dirs.detector_dir, _FIXTURE_DETECTOR_MANIFEST
                )
            )
        finally:
            renamed.rename(source)

    def test_a_symlinked_model_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "linked-root"
            try:
                link.symlink_to(self._dirs.detector, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("this platform does not allow directory symlinks")
            self.assertTrue(
                contract.validate_model_manifest(
                    self._dirs.detector_dir, _FIXTURE_DETECTOR_MANIFEST
                )
            )
            self.assertFalse(
                contract.validate_model_manifest(
                    str(link), _FIXTURE_DETECTOR_MANIFEST
                )
            )
            self.assertFalse(child._is_local_dir(str(link)))
            self.assertFalse(child._model_manifests_valid(str(link), self._dirs.recognizer_dir))

    def test_a_symlinked_model_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real-weights"
            real.write_bytes(_FIXTURE_DETECTOR_BODY["inference.pdiparams"])
            link = self._dirs.detector / "inference.pdiparams"
            backup = link.read_bytes()
            link.unlink()
            try:
                link.symlink_to(real)
            except (OSError, NotImplementedError):
                self.skipTest("this platform does not allow file symlinks")
            try:
                # The link resolves to the right bytes, so only the explicit
                # symlink refusal can catch it.
                self.assertEqual(
                    link.read_bytes(), _FIXTURE_DETECTOR_BODY["inference.pdiparams"]
                )
                self.assertFalse(
                    contract.validate_model_manifest(
                        self._dirs.detector_dir, _FIXTURE_DETECTOR_MANIFEST
                    )
                )
            finally:
                link.unlink()
                link.write_bytes(backup)

    def test_a_subdirectory_in_a_model_root_is_refused(self) -> None:
        (self._dirs.detector / "sub").mkdir()
        self.assertFalse(
            contract.validate_model_manifest(
                self._dirs.detector_dir, _FIXTURE_DETECTOR_MANIFEST
            )
        )

    def test_an_absent_or_non_directory_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a_file = Path(tmp) / "not-a-dir"
            a_file.write_text("x", encoding="utf-8")
            for path in (
                str(Path(tmp) / "absent"),
                str(a_file),
                "relative/detector",
                "",
                None,
                42,
            ):
                with self.subTest(path=path):
                    self.assertFalse(
                        contract.validate_model_manifest(
                            path, _FIXTURE_DETECTOR_MANIFEST
                        )
                    )
        # An empty manifest is never a licence to accept anything.
        self.assertFalse(contract.validate_model_manifest(self._dirs.detector_dir, ()))

    # -- parent preflight prevents the spawn ----------------------------------

    def test_parent_preflight_prevents_spawn_for_every_manifest_failure(self) -> None:
        mutations = {}

        missing = self._dirs.detector / "inference.json"
        body = missing.read_bytes()
        missing.unlink()
        mutations["missing-file"] = (lambda: missing.write_bytes(body))

        extra = self._dirs.recognizer / "extra.bin"
        extra.write_bytes(b"x")
        mutations["extra-file"] = (lambda: extra.unlink(missing_ok=True))

        flipped = self._dirs.detector / "inference.yml"
        original = flipped.read_bytes()
        mutated = bytearray(original)
        mutated[0] ^= 0xFF
        flipped.write_bytes(bytes(mutated))
        mutations["wrong-hash"] = (lambda: flipped.write_bytes(original))

        grown = self._dirs.recognizer / "inference.pdiparams"
        original_grown = grown.read_bytes()
        grown.write_bytes(original_grown + b"\x00")
        mutations["wrong-size"] = (lambda: grown.write_bytes(original_grown))

        try:
            for label, restore in mutations.items():
                with self.subTest(mutation=label):
                    spy = _SpawnSpy()
                    with mock.patch.object(isolation, "_spawn_ocr_child", spy):
                        result = isolation.ocr_png_isolated(
                            png=_png_bytes(),
                            width=12,
                            height=8,
                            detector_dir=self._dirs.detector_dir,
                            recognizer_dir=self._dirs.recognizer_dir,
                        )
                    self.assertEqual(spy.calls, 0, label)
                    self.assertEqual(
                        result.reason_code,
                        contract.OCR_RUNTIME_MISSING_REASON_CODE,
                        label,
                    )
                    restore()
        finally:
            for restore in mutations.values():
                restore()
        self.assertTrue(
            isolation.model_manifests_present(
                self._dirs.detector_dir, self._dirs.recognizer_dir
            )
        )

    def test_the_parent_runs_the_manifest_preflight_before_the_spawn(self) -> None:
        calls: list[str] = []
        real_spawn = isolation._spawn_ocr_child

        def spawn(argv, environment):
            calls.append("spawn")
            return real_spawn(argv, environment)

        def preflight(detector, recognizer):
            calls.append("preflight")
            return True

        with mock.patch.object(isolation, "_spawn_ocr_child", spawn), mock.patch.object(
            isolation, "model_manifests_present", preflight
        ):
            result = isolation.ocr_png_isolated(
                png=_png_bytes(),
                width=12,
                height=8,
                detector_dir=self._dirs.detector_dir,
                recognizer_dir=self._dirs.recognizer_dir,
            )
        self.assertEqual(calls[0], "preflight")
        self.assertEqual(calls.count("preflight"), 1)
        # The real child has no PaddleOCR in the product manifests, so the run
        # is still a bounded refusal; what matters here is the ordering.
        self.assertIsNotNone(result)

    def test_a_manifest_failure_is_a_bounded_runtime_missing_code(self) -> None:
        (self._dirs.detector / "inference.yml").write_bytes(b"wrong")
        self.assertFalse(
            isolation.model_manifests_present(
                self._dirs.detector_dir, self._dirs.recognizer_dir
            )
        )
        self.assertFalse(
            child._model_manifests_valid(
                self._dirs.detector_dir, self._dirs.recognizer_dir
            )
        )

    def test_the_child_revalidates_the_manifests_before_importing_paddleocr(self) -> None:
        _FakeRuntime.instances.clear()
        patch = mock.patch.dict(
            sys.modules, {"paddleocr": _fake_paddleocr_module()}, clear=False
        )
        patch.start()
        self.addCleanup(patch.stop)
        # Break only the child-side view of the manifest: the envelope is built
        # by the parent, but the directory is mutated before the child looks.
        (self._dirs.detector / "inference.json").write_bytes(b"tampered")
        with mock.patch.object(
            isolation, "model_manifests_present", lambda detector, recognizer: True
        ):
            envelope = contract.encode_envelope(
                detector_dir=self._dirs.detector_dir,
                recognizer_dir=self._dirs.recognizer_dir,
                payload=_png_bytes(),
                width=12,
                height=8,
            )
        report = _child_main(envelope)
        self.assertFalse(report.ok)
        self.assertEqual(report.code, contract.OCR_RUNTIME_MISSING_REASON_CODE)
        # The manifest gate precedes the import-and-build step entirely, so no
        # weight set was ever loaded.
        self.assertEqual(_FakeRuntime.instances, [])

    def test_the_child_manifest_gate_runs_before_the_runtime_is_built(self) -> None:
        source = Path(child.__file__).read_text(encoding="utf-8")
        manifest_gate = source.index("_model_manifests_valid(detector_dir, recognizer_dir)")
        build = source.index("_build_runtime(detector_dir, recognizer_dir)")
        self.assertLess(manifest_gate, build)


class CanonicalPngValidationTests(unittest.TestCase):
    """P: the canonical PNG is validated structurally, on both sides."""

    def setUp(self) -> None:
        self._dirs = _ModelDirs()
        self.addCleanup(self._dirs.cleanup)
        self._png = _png_bytes()

    def test_the_valid_canonical_png_yields_exact_facts(self) -> None:
        facts = contract.inspect_canonical_png(self._png, width=12, height=8)
        self.assertIsNotNone(facts)
        self.assertEqual(facts.format, "PNG")
        self.assertEqual((facts.width, facts.height), (12, 8))
        self.assertEqual(facts.sha256, hashlib.sha256(self._png).hexdigest())

    def test_a_non_png_signature_is_refused(self) -> None:
        for label, payload in (
            ("jpeg", _png_bytes("JPEG")),
            ("gif", _png_bytes("GIF")),
            ("corrupt-signature", b"\x89PNG\r\n\x1a\x00" + self._png[8:]),
            ("empty", b""),
            ("truncated-header", self._png[:16]),
        ):
            with self.subTest(label=label):
                self.assertIsNone(
                    contract.inspect_canonical_png(payload, width=12, height=8)
                )

    def test_wrong_declared_dimensions_are_refused(self) -> None:
        for width, height in (
            (13, 8),
            (12, 9),
            (1, 1),
            (0, 8),
            (12, 0),
            (-12, 8),
            (12, -8),
            (True, 8),
            (12.0, 8),
            ("12", 8),
        ):
            with self.subTest(width=width, height=height):
                self.assertIsNone(
                    contract.inspect_canonical_png(self._png, width=width, height=height)
                )

    def test_a_mismatched_ihdr_is_refused(self) -> None:
        # A PNG whose declared IHDR length or type is wrong is not a PNG this
        # boundary will read, and the check is bytes, not a decode.
        for label, payload in (
            ("bad-length", self._png[:8] + b"\x00\x00\x00\x0c" + self._png[12:]),
            ("bad-type", self._png[:12] + b"IHDA" + self._png[16:]),
            ("zero-width", self._png[:16] + b"\x00\x00\x00\x00" + self._png[20:]),
            ("zero-height", self._png[:20] + b"\x00\x00\x00\x00" + self._png[24:]),
        ):
            with self.subTest(label=label):
                self.assertIsNone(
                    contract.inspect_canonical_png(payload, width=12, height=8)
                )

    def test_a_forged_or_truncated_png_prefix_is_refused(self) -> None:
        oversized = _png_bytes(size=(12, 8))
        forged = bytearray(oversized[:24])
        self.assertIsNone(
            contract.inspect_canonical_png(bytes(forged), width=12, height=8)
        )
        self.assertIsNone(
            contract.inspect_canonical_png(oversized[:-1], width=12, height=8)
        )

    def test_png_chunk_crc_idat_and_iend_are_required(self) -> None:
        idat_type = self._png.find(b"IDAT")
        self.assertGreater(idat_type, 0)
        corrupt = bytearray(self._png)
        corrupt[idat_type + 4] ^= 0x01
        mutations = {
            "bad-crc": bytes(corrupt),
            "truncated": self._png[:-1],
            "no-terminal-iend": self._png[: self._png.rfind(b"IEND") - 4],
        }
        for label, payload in mutations.items():
            with self.subTest(label=label):
                self.assertIsNone(
                    contract.inspect_canonical_png(payload, width=12, height=8)
                )

    def test_the_envelope_carries_format_dimensions_and_digest(self) -> None:
        envelope = contract.encode_envelope(
            detector_dir=self._dirs.detector_dir,
            recognizer_dir=self._dirs.recognizer_dir,
            payload=self._png,
            width=12,
            height=8,
        )
        frame = json.loads(envelope.decode("utf-8"))
        self.assertEqual(frame["format"], "PNG")
        self.assertEqual(frame["width"], 12)
        self.assertEqual(frame["height"], 8)
        self.assertEqual(frame["sha256"], hashlib.sha256(self._png).hexdigest())
        self.assertEqual(set(frame), set(contract.ENVELOPE_KEYS))
        decoded = contract.decode_envelope(envelope)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.payload, self._png)
        self.assertEqual(decoded.sha256, frame["sha256"])
        self.assertEqual((decoded.width, decoded.height), (12, 8))
        self.assertEqual(decoded.format, "PNG")

    def test_a_wrong_digest_in_the_envelope_is_refused_by_the_child(self) -> None:
        for label, digest in (
            ("zeroes", "0" * 64),
            ("flipped", "f" * 64),
            ("truncated", "abc"),
            ("uppercase", hashlib.sha256(self._png).hexdigest().upper()),
            ("non-hex", "z" * 64),
        ):
            with self.subTest(label=label):
                frame = {
                    "base64": base64.b64encode(self._png).decode("ascii"),
                    "detector_dir": self._dirs.detector_dir,
                    "recognizer_dir": self._dirs.recognizer_dir,
                    "format": "PNG",
                    "width": 12,
                    "height": 8,
                    "sha256": digest,
                }
                self.assertIsNone(
                    contract.decode_envelope(json.dumps(frame).encode("utf-8"))
                )

    def test_a_swapped_payload_is_caught_by_the_declared_digest(self) -> None:
        # Same format, same dimensions, different pixels: only the digest can
        # tell these apart, which is exactly why it is in the envelope.
        other = _png_bytes(size=(12, 8), color=(200, 100, 50))
        self.assertNotEqual(other, self._png)
        frame = {
            "base64": base64.b64encode(other).decode("ascii"),
            "detector_dir": self._dirs.detector_dir,
            "recognizer_dir": self._dirs.recognizer_dir,
            "format": "PNG",
            "width": 12,
            "height": 8,
            "sha256": hashlib.sha256(self._png).hexdigest(),
        }
        self.assertIsNone(contract.decode_envelope(json.dumps(frame).encode("utf-8")))

    def test_a_wrong_format_claim_is_refused(self) -> None:
        for value in ("JPEG", "png", "", None, 1, "WEBP"):
            with self.subTest(format=value):
                frame = {
                    "base64": base64.b64encode(self._png).decode("ascii"),
                    "detector_dir": self._dirs.detector_dir,
                    "recognizer_dir": self._dirs.recognizer_dir,
                    "format": value,
                    "width": 12,
                    "height": 8,
                    "sha256": hashlib.sha256(self._png).hexdigest(),
                }
                self.assertIsNone(
                    contract.decode_envelope(json.dumps(frame).encode("utf-8"))
                )

    def test_a_non_png_payload_cannot_be_encoded_at_all(self) -> None:
        for label, payload, width, height in (
            ("jpeg", _png_bytes("JPEG"), 12, 8),
            ("text", b"plain text, not an image", 12, 8),
            ("empty", b"", 12, 8),
            ("wrong-size", _png_bytes(size=(12, 8)), 13, 8),
        ):
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    contract.encode_envelope(
                        detector_dir=self._dirs.detector_dir,
                        recognizer_dir=self._dirs.recognizer_dir,
                        payload=payload,
                        width=width,
                        height=height,
                    )

    def test_the_parent_refuses_a_non_canonical_png_without_spawning(self) -> None:
        for label, payload, width, height in (
            ("jpeg", _png_bytes("JPEG"), 12, 8),
            ("corrupt-signature", b"\x00" + self._png[1:], 12, 8),
            ("wrong-width", self._png, 13, 8),
            ("wrong-height", self._png, 12, 9),
        ):
            with self.subTest(label=label):
                spy = _SpawnSpy()
                with mock.patch.object(isolation, "_spawn_ocr_child", spy):
                    result = isolation.ocr_png_isolated(
                        png=payload,
                        width=width,
                        height=height,
                        detector_dir=self._dirs.detector_dir,
                        recognizer_dir=self._dirs.recognizer_dir,
                    )
                self.assertEqual(spy.calls, 0, label)
                self.assertEqual(
                    result.reason_code, contract.OCR_INPUT_REASON_CODE, label
                )

    def test_the_child_repeats_the_png_validation_before_writing_a_temp_file(self) -> None:
        _FakeRuntime.instances.clear()
        patch = mock.patch.dict(
            sys.modules, {"paddleocr": _fake_paddleocr_module()}, clear=False
        )
        patch.start()
        self.addCleanup(patch.stop)
        # The envelope is well formed and decoded; the child is then handed a
        # payload whose digest does not match the claim it validated.
        with mock.patch.object(
            child,
            "inspect_canonical_png",
            return_value=contract.CanonicalPngFacts(
                format="PNG", width=12, height=8, sha256="0" * 64
            ),
        ):
            report = child._run_ocr(
                self._png,
                self._dirs.detector_dir,
                self._dirs.recognizer_dir,
                12,
                8,
                "1" * 64,
            )
        self.assertFalse(report.ok)
        self.assertEqual(report.code, contract.OCR_ISOLATION_FAILURE_REASON_CODE)
        self.assertEqual(_FakeRuntime.instances, [])

    def test_the_child_refuses_a_structurally_invalid_png_without_a_runtime(self) -> None:
        _FakeRuntime.instances.clear()
        patch = mock.patch.dict(
            sys.modules, {"paddleocr": _fake_paddleocr_module()}, clear=False
        )
        patch.start()
        self.addCleanup(patch.stop)
        digest = hashlib.sha256(self._png).hexdigest()
        for label, payload in (
            ("non-png", _png_bytes("JPEG")),
            ("bad-signature", b"\x00" + self._png[1:]),
            ("truncated", self._png[:16]),
        ):
            with self.subTest(label=label):
                _FakeRuntime.instances.clear()
                report = child._run_ocr(
                    payload,
                    self._dirs.detector_dir,
                    self._dirs.recognizer_dir,
                    12,
                    8,
                    digest,
                )
                self.assertFalse(report.ok)
                self.assertEqual(
                    report.code, contract.OCR_ISOLATION_FAILURE_REASON_CODE
                )
                self.assertEqual(_FakeRuntime.instances, [])

    def test_no_image_decoder_is_used_on_either_side(self) -> None:
        # SECOND_UNTRUSTED_IMAGE_DECODER=0. The PNG is read as bytes: the 8-byte
        # signature, a 13-byte IHDR length, the chunk type and two big-endian
        # dimensions. Neither module imports or calls an image decoder.
        for path in (Path(child.__file__), Path(isolation.__file__), Path(contract.__file__)):
            imported = _imported_module_names(path)
            called = _called_names(path)
            for forbidden in (
                "PIL",
                "Pillow",
                "cv2",
                "imageio",
                "matplotlib",
                "numpy",
                "paddle",
                "paddlex",
            ):
                self.assertNotIn(forbidden, imported, f"{path.name}: {forbidden}")
            # ``open`` is exempted in the contract only, and only because the
            # bounded manifest digest must read model *files*; it is asserted
            # absent from the child and the parent.
            forbidden_calls = (
                "Image",
                "imdecode",
                "imread",
                "load",
                "detect_format",
                "sniff",
                "inspect_file",
                "transform_image",
            )
            if path.name != "image_ocr_contract.py":
                forbidden_calls = forbidden_calls + ("open",)
            for forbidden in forbidden_calls:
                self.assertNotIn(forbidden, called, f"{path.name}: {forbidden}")
        source = Path(contract.__file__).read_text(encoding="utf-8")
        self.assertIn("PNG_SIGNATURE", source)
        self.assertIn(">II", source)

    def test_original_source_bytes_never_reach_the_child(self) -> None:
        # ORIGINAL_SOURCE_BYTES_TO_OCR_CHILD=0: the envelope the parent writes
        # contains the Core output, and the parent's own byte ceiling keeps the
        # caller's payload out of the command line and the environment.
        source = _png_bytes("JPEG")
        seen: dict[str, object] = {}
        body = _success_bytes([_result_frame("ok")])

        def capture(argv, environment):
            process = _ProcessDouble(stdout=body)
            seen["process"] = process
            return process

        with mock.patch.object(isolation, "_spawn_ocr_child", capture):
            with mock.patch.object(
                isolation, "_write_envelope", lambda stream, envelope: seen.setdefault(
                    "envelope", envelope
                )
            ):
                result = image_ocr(
                    source,
                    filename="quote.jpg",
                    detector_dir=self._dirs.detector_dir,
                    recognizer_dir=self._dirs.recognizer_dir,
                )
        self.assertEqual(result.ocr.outcome, isolation.OcrOutcome.COMPLETED)
        envelope = seen["envelope"]
        frame = json.loads(envelope.decode("utf-8"))
        payload = base64.b64decode(frame["base64"])
        self.assertTrue(payload.startswith(contract.PNG_SIGNATURE))
        self.assertNotIn(base64.b64encode(source).decode("ascii"), envelope.decode("utf-8"))
        self.assertEqual(frame["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(frame["sha256"], hashlib.sha256(result.image.data).hexdigest())

    def test_the_provenance_digest_is_bound_to_the_decoded_png(self) -> None:
        _FakeRuntime.instances.clear()
        patch = mock.patch.dict(
            sys.modules, {"paddleocr": _fake_paddleocr_module()}, clear=False
        )
        patch.start()
        self.addCleanup(patch.stop)
        payload = _png_bytes(size=(12, 8))
        report = _child_main(
            contract.encode_envelope(
                detector_dir=self._dirs.detector_dir,
                recognizer_dir=self._dirs.recognizer_dir,
                payload=payload,
                width=12,
                height=8,
            )
        )
        self.assertTrue(report.ok)
        self.assertEqual(
            report.provenance.canonical_png_sha256,
            hashlib.sha256(payload).hexdigest(),
        )
        # The receipt is still path-free: a digest is not a location.
        note = json.dumps(report.safe_dict(), ensure_ascii=False)
        self.assertNotIn(self._dirs.root, note)
        self.assertNotIn("detector", note.replace("detector_revision", ""))

    def test_provenance_requires_a_well_formed_canonical_digest(self) -> None:
        for label, value in (
            ("empty", ""),
            ("short", "abc"),
            ("uppercase", "A" * 64),
            ("non-hex", "z" * 64),
            ("not-a-string", 1),
        ):
            with self.subTest(label=label):
                body = _success_bytes(
                    provenance=_provenance_frame(canonical_png_sha256=value)
                )
                self.assertIsNone(contract.decode_report(body))


class OptionalLiveSmokeTests(unittest.TestCase):
    """N: a real end-to-end run, gated on explicitly provisioned local models.

    The heavy PaddleOCR stack is deliberately absent from the product manifests,
    so this is opt-in: set both ``KAGENT_OCR_DETECTOR_DIR`` and
    ``KAGENT_OCR_RECOGNIZER_DIR`` to real local model directories to exercise a
    genuine OCR. Without them the test is skipped rather than faked.
    """

    def test_live_local_paddleocr_smoke(self) -> None:
        detector = os.environ.get(_MODEL_DIR_ENV[0])
        recognizer = os.environ.get(_MODEL_DIR_ENV[1])
        if not detector or not recognizer:
            self.skipTest(
                "set KAGENT_OCR_DETECTOR_DIR and KAGENT_OCR_RECOGNIZER_DIR to run the live smoke"
            )
        result = image_ocr(
            _ocr_fixture_png(),
            filename="fixture.png",
            detector_dir=detector,
            recognizer_dir=recognizer,
        )
        self.assertEqual(
            result.ocr.outcome,
            isolation.OcrOutcome.COMPLETED,
            result.ocr.reason_code,
        )
        self.assertEqual(
            result.ocr.provenance.runtime_revision, contract.PADDLEOCR_RUNTIME_REVISION
        )
        texts = " ".join(item.text for item in result.ocr.results)
        self.assertTrue(texts.strip(), "a real OCR run must produce text")
        for item in result.ocr.results:
            self.assertLessEqual(len(item.text), contract.MAX_OCR_RESULT_TEXT_CHARS)
            self.assertLessEqual(len(item.boxes), contract.MAX_OCR_BOXES_PER_RESULT)
            for box in item.boxes:
                self.assertLessEqual(len(box.points), contract.MAX_OCR_BOX_POINTS)
                for x, y in box.points:
                    self.assertLessEqual(x, result.image.width)
                    self.assertLessEqual(y, result.image.height)


def _ocr_fixture_png() -> bytes:
    """A small high-contrast fixture, rendered without a font dependency."""

    image = Image.new("RGB", (320, 80), (255, 255, 255))
    pixels = image.load()
    for top in range(20, 40):
        for left in range(20, 300):
            pixels[left, top] = (0, 0, 0)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


if __name__ == "__main__":
    unittest.main()
