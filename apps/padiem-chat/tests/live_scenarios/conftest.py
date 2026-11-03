"""Playwright recorder for explicitly selected live scenario tests."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # Normal collection remains usable without the browser extra.
    sync_playwright = None

_RUNS: dict[str, dict] = {}
_ARTIFACT_ROOT: Path | None = None


def _artifact_root() -> Path:
    configured = os.getenv("PADIEM_LIVE_ARTIFACTS", "").strip()
    root = Path(configured).expanduser() if configured else Path.cwd() / "live-artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _safe_origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname or 'invalid'}"


def _base_url() -> str:
    value = os.getenv("PADIEM_LIVE_BASE_URL", "https://chat.padiem.net").strip()
    parts = urlsplit(value)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise pytest.UsageError("PADIEM_LIVE_BASE_URL must be an http(s) origin")
    return value.rstrip("/")


_SCRIPT_CAPTIONS = {
    ("test_guest_public_screens_and_read_only_auth_gate", "chat-first-screen"): ("01-first-visit.md", 1),
    ("test_guest_public_screens_and_read_only_auth_gate", "help-bookai-copy"): ("04-bookai.md", 3),
    ("test_guest_public_screens_and_read_only_auth_gate", "pc-install-guide"): ("02-pc-connection.md", 1),
    ("test_guest_public_screens_and_read_only_auth_gate", "guest-auth-status"): ("01-first-visit.md", 2),
    ("test_guest_public_screens_and_read_only_auth_gate", "guest-login-required-gate"): ("01-first-visit.md", 3),
    ("test_guest_public_screens_and_read_only_auth_gate", "bookai-guest-device-storage"): ("04-bookai.md", 1),
    ("test_first_question_with_prepared_login", "open-chat-with-session"): ("01-first-visit.md", 1),
    ("test_first_question_with_prepared_login", "verify-login-session"): ("01-first-visit.md", 4),
    ("test_first_question_with_prepared_login", "send-first-question"): ("01-first-visit.md", 5),
    ("test_pc_install_guide_and_read_only_xlsx_search", "pc-install-guide"): ("02-pc-connection.md", 1),
    ("test_pc_install_guide_and_read_only_xlsx_search", "verify-preapproved-pc"): ("02-pc-connection.md", 3),
    ("test_pc_install_guide_and_read_only_xlsx_search", "search-xlsx-on-pc"): ("02-pc-connection.md", 4),
    ("test_synthetic_document_upload_summary_and_download", "open-document-chat"): ("03-document-work.md", 1),
    ("test_synthetic_document_upload_summary_and_download", "attach-synthetic-text"): ("03-document-work.md", 1),
    ("test_synthetic_document_upload_summary_and_download", "summarize-document"): ("03-document-work.md", 2),
    ("test_synthetic_document_upload_summary_and_download", "download-saved-summary"): ("03-document-work.md", 3),
    ("test_bookai_reading_screen_with_prepared_account", "bookai-with-session"): ("04-bookai.md", 1),
    ("test_bookai_reading_screen_with_prepared_account", "open-reading-screen"): ("04-bookai.md", 2),
    ("test_bookai_reading_screen_with_prepared_account", "resume-reading-on-second-device"): ("04-bookai.md", 4),
    ("test_tutorial_account_deletion_flow", "open-account-settings"): ("05-account-deletion.md", 1),
    ("test_tutorial_account_deletion_flow", "open-delete-confirm"): ("05-account-deletion.md", 2),
    ("test_tutorial_account_deletion_flow", "delete-account"): ("05-account-deletion.md", 3),
    ("test_tutorial_external_ai_connect_flow", "open-connect-settings"): ("07-external-ai-connect.md", 1),
    ("test_tutorial_external_ai_connect_flow", "open-connection-guide"): ("07-external-ai-connect.md", 2),
}


def _caption_from_script(scenario: str, step: str) -> str:
    source = _SCRIPT_CAPTIONS.get((scenario, step))
    if source is None:
        raise AssertionError(f"live step has no screenplay caption: {scenario}/{step}")
    document, row_number = source
    root = Path(__file__).resolve().parents[4]
    path = root / "docs" / "qa" / "scenarios" / document
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0].isdigit() and int(cells[0]) == row_number:
            if len(cells) < 4 or not cells[3]:
                break
            return cells[3]
    raise AssertionError(f"screenplay row is missing: {document}#{row_number}")


@pytest.fixture
def live_base_url():
    return _base_url()


@pytest.fixture
def live_storage_state():
    raw = os.getenv("PADIEM_LIVE_STORAGE_STATE", "").strip()
    if not raw or not Path(raw).expanduser().is_file():
        pytest.skip("test_account_missing")
    return str(Path(raw).expanduser().resolve())


class LiveScenario:
    def __init__(self, page, scenario: str, directory: Path):
        self.page = page
        self.scenario = scenario
        self.directory = directory
        self.steps: list[dict] = []
        self.video_path: str | None = None
        self.extra_contexts = []
        self.extra_video_paths: list[str] = []
        self.browser = None
        self.video_dir: Path | None = None

    def step(self, name: str, caption: str, action, page=None):
        # Captions come from the human screenplay, not a second copy in test data.
        caption = _caption_from_script(self.scenario, name)
        target = page or self.page
        number = len(self.steps) + 1
        image = self.directory / f"step-{number:02d}.png"
        started = time.perf_counter()
        status_code = None
        outcome = "passed"
        try:
            value = action()
            status_code = getattr(value, "status", None)
            if isinstance(value, dict):
                status_code = value.get("status_code", status_code)
            return value
        except BaseException as exc:
            status_code = getattr(exc, "status_code", status_code)
            outcome = "skipped" if isinstance(exc, pytest.skip.Exception) else "failed"
            raise
        finally:
            elapsed = round((time.perf_counter() - started) * 1000)
            try:
                target.screenshot(
                    path=str(image),
                    full_page=True,
                    animations="disabled",
                    mask=[target.locator(
                        "input[type='email'], input[type='password'], [data-sensitive]"
                    )],
                )
                image_ref = str(image.relative_to(_ARTIFACT_ROOT)).replace("\\", "/")
            except Exception:
                image_ref = None
            self.steps.append(
                {
                    "name": name,
                    "caption": caption,
                    "outcome": outcome,
                    "duration_ms": elapsed,
                    "status_code": status_code,
                    "http_504": status_code == 504,
                    "screenshot": image_ref,
                }
            )

    def open_second_context(self, storage_state: str):
        video_dir = self.video_dir / "second-device"
        video_dir.mkdir(exist_ok=True)
        context = self.browser.new_context(
            record_video_dir=str(video_dir),
            record_video_size={"width": 1280, "height": 900},
            viewport={"width": 1280, "height": 900},
            storage_state=storage_state,
        )
        self.extra_contexts.append(context)
        return context

    def close_context(self, page):
        video = page.video
        context = page.context
        for closer in (page.close, context.close):
            try:
                closer()
            except Exception:
                pass
        self.extra_contexts = [item for item in self.extra_contexts if item is not context]
        if video is not None:
            try:
                self.extra_video_paths.append(
                    str(Path(video.path()).resolve().relative_to(_ARTIFACT_ROOT)).replace("\\", "/")
                )
            except Exception:
                pass


@pytest.fixture
def live_scenario(request):
    global _ARTIFACT_ROOT
    if sync_playwright is None:
        pytest.skip("playwright_unavailable")
    _ARTIFACT_ROOT = _artifact_root()
    scenario_key = re.sub(r"[^a-zA-Z0-9_-]+", "-", request.node.name).strip("-")
    directory = _ARTIFACT_ROOT / scenario_key
    directory.mkdir(parents=True, exist_ok=True)
    video_dir = directory / "video"
    video_dir.mkdir(exist_ok=True)
    base_url = _base_url()
    state = None
    if request.node.get_closest_marker("live_storage"):
        raw_state = os.getenv("PADIEM_LIVE_STORAGE_STATE", "").strip()
        state = str(Path(raw_state).expanduser().resolve())

    with sync_playwright() as driver:
        browser = driver.chromium.launch(args=["--no-sandbox"])
        context_args = {
            "record_video_dir": str(video_dir),
            "record_video_size": {"width": 1280, "height": 900},
            "viewport": {"width": 1280, "height": 900},
        }
        if state:
            context_args["storage_state"] = state
        context = browser.new_context(**context_args)
        page = context.new_page()

        # This run has no session state. Its browser may issue only safe reads.
        if not state:
            def read_only(route):
                if route.request.method.upper() in {"GET", "HEAD"}:
                    route.continue_()
                else:
                    route.abort("blockedbyclient")
            page.route("**/*", read_only)

        recorder = LiveScenario(page, request.node.name, directory)
        recorder.browser = browser
        recorder.video_dir = video_dir
        request.node._live_scenario_record = recorder
        yield recorder
        for extra in recorder.extra_contexts:
            try:
                extra.close()
            except Exception:
                pass
        try:
            page.close()
            context.close()
            browser.close()
        finally:
            video = getattr(page, "video", None)
            if video is not None:
                try:
                    recorder.video_path = str(
                        Path(video.path()).resolve().relative_to(_ARTIFACT_ROOT)
                    ).replace("\\", "/")
                except Exception:
                    recorder.video_path = None
            entry = {
                "scenario": request.node.name,
                "outcome": getattr(request.node, "_live_outcome", "passed"),
                "steps": recorder.steps,
                "video": recorder.video_path,
                "extra_videos": recorder.extra_video_paths,
            }
            skip_reason = getattr(request.node, "_live_skip_reason", None)
            if skip_reason:
                entry["skip_reason"] = skip_reason
            _RUNS[request.node.nodeid] = entry


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if not item.get_closest_marker("live"):
        return
    if call.when in {"setup", "call"} and report.skipped:
        reason = "test_account_missing" if "test_account_missing" in str(report.longrepr) else "setup_skipped"
        item._live_skip_reason = reason
        _RUNS[item.nodeid] = {
            "scenario": item.name,
            "outcome": "skipped",
            "skip_reason": reason,
            "steps": [],
            "video": None,
            "extra_videos": [],
        }
    elif call.when == "call":
        item._live_outcome = report.outcome


def pytest_sessionfinish(session, exitstatus):
    if not _RUNS:
        return
    root = _ARTIFACT_ROOT or _artifact_root()
    base = os.getenv("PADIEM_LIVE_BASE_URL", "https://chat.padiem.net")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    result = {
        "schema_version": 1,
        "run_id": run_id,
        "base_origin": _safe_origin(base),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "exit_status": exitstatus,
        "scenarios": list(_RUNS.values()),
    }
    target = root / f"summary-{run_id}.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)
