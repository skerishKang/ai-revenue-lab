#!/usr/bin/env python3
"""#6724 2: record the guest scenes of the live scenarios.

Only screens an anonymous visitor can reach are recorded: GET/HEAD on
chat.padiem.net and bookai.padiem.net, no form posts, no login, no account. The
steps that need a prepared account are not faked; the tutorial shows a
placeholder and the future session file is named here, empty today.

Artifacts stay outside the repository (default: ``<repo>/../out``):

    out/<scenario>/step-NN.png   full-page screenshot per captured step
    out/<scenario>/video.webm    one recording per scene
    out/<scenario>/captions.vtt  one cue per captured step, from real offsets
    out/<scenario>/manifest.json keys, outcomes, timings (no request bodies)

``--dry-run`` prints the plan without starting a browser; the unit test reads it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_tutorials  # noqa: E402 - sibling module, same folder

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO.parent / "out"
#: Reserved for the test account's Playwright session file. Not set today, and
#: never committed: the file holds a real login.
ACCOUNT_ENV = build_tutorials.ACCOUNT_ENV
CHAT_ORIGIN = "https://chat.padiem.net"
BOOKAI_ORIGIN = "https://bookai.padiem.net"
VIEWPORT = {"width": 1280, "height": 900}


@dataclass(frozen=True)
class Step:
    number: int
    origin: str
    path: str
    expect: tuple[str, ...] = ()
    selector: str = ""
    api: str = ""
    #: Text the page shows while it boots. The screenshot waits until it is gone,
    #: so a loader can never become the tutorial's illustration.
    wait_absent: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scene:
    slug: str
    steps: tuple[Step, ...]


#: One entry per recorded scene. Numbers match the screenplay rows, so the
#: manifest and the tutorial caption the same step.
SCENES = (
    Scene(
        "01-first-visit",
        (
            Step(1, CHAT_ORIGIN, "/", ("안녕하세요.", "무엇을 도와드릴까요?")),
            Step(2, CHAT_ORIGIN, "/", api="/api/auth/status"),
            Step(3, CHAT_ORIGIN, "/", api="/api/conversations"),
        ),
    ),
    Scene(
        "02-pc-connection",
        (
            Step(1, CHAT_ORIGIN, "/install.html", ("컴퓨터 연결 프로그램 설치 안내", "이 PC 연결하기")),
            Step(2, CHAT_ORIGIN, "/install.html", ("설치 파일",)),
        ),
    ),
    Scene(
        "04-bookai",
        (
            Step(
                1,
                BOOKAI_ORIGIN,
                "/",
                selector="#openBook",
                wait_absent=("책과 기록을 열고 있습니다.",),
            ),
            Step(
                3,
                CHAT_ORIGIN,
                "/help.html",
                (
                    "로그인하지 않아도 읽기 기록과 Memory가 이 기기에 저장돼요.",
                    "파디엠 계정으로 로그인하면 계정에도 저장되어 다른 기기에서 이어져요.",
                ),
            ),
        ),
    ),
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(max(0, int(milliseconds)), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def build_vtt(records: list[dict]) -> str:
    """One cue per captured step, ending where the next cue starts."""

    lines = ["WEBVTT", ""]
    for index, record in enumerate(records):
        start = int(record["offset_ms"])
        end = (
            int(records[index + 1]["offset_ms"])
            if index + 1 < len(records)
            else start + 5_000
        )
        if end <= start:
            end = start + 2_000
        lines.extend(
            [str(index + 1), f"{_timestamp(start)} --> {_timestamp(end)}", record["caption"], ""]
        )
    return "\n".join(lines).rstrip() + "\n"


def plan_document(only: set[str] | None = None) -> dict:
    documents = build_tutorials.load_scenarios()
    scenes = {scene.slug: scene for scene in SCENES}
    entries = []
    for document in documents:
        if only and document["key"] not in only:
            continue
        scene = scenes.get(document["key"])
        steps = scene.steps if scene else ()
        entries.append(
            {
                "scenario": document["key"],
                "guest_steps": document["guest"],
                "account_steps": document["account"],
                "capture": [
                    {
                        "number": step.number,
                        "url": step.origin + step.path,
                        "api": step.api or None,
                        "selector": step.selector or None,
                        "expect": list(step.expect),
                    }
                    for step in steps
                ],
            }
        )
    return {
        "schema_version": 1,
        "account_env": ACCOUNT_ENV,
        "account_env_set": bool(os.environ.get(ACCOUNT_ENV, "").strip()),
        "out": str(DEFAULT_OUT),
        "scenes": entries,
    }


def _assert_expectations(page, step: Step) -> None:
    if step.selector:
        if not page.locator(step.selector).is_visible():
            raise AssertionError(f"missing selector: {step.selector}")
    if step.expect:
        body = _normalize(page.locator("body").inner_text())
        for expected in step.expect:
            needle = _normalize(expected)
            if needle not in body:
                raise AssertionError(f"missing text: {needle[:60]}")


def _capture_scene(browser, scene: Scene, directory: Path, document: dict) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    raw_video = directory / "video-raw"
    if raw_video.exists():
        shutil.rmtree(raw_video)
    raw_video.mkdir()
    context = browser.new_context(
        record_video_dir=str(raw_video),
        record_video_size=VIEWPORT,
        viewport=VIEWPORT,
    )
    page = context.new_page()
    blocked: list[str] = []

    def guard(route):
        # A guest run may only read. Anything else is refused in the browser,
        # not left to the server to reject.
        if route.request.method.upper() in {"GET", "HEAD"}:
            route.continue_()
        else:
            blocked.append(route.request.method)
            route.abort("blockedbyclient")

    page.route("**/*", guard)
    video = page.video
    records: list[dict] = []
    started = time.perf_counter()
    try:
        for step in scene.steps:
            caption = next(
                (item["caption"] for item in document["steps"] if item["number"] == step.number),
                f"{step.number}단계",
            )
            entry = {"number": step.number, "caption": caption}
            try:
                response = page.goto(
                    step.origin + step.path, wait_until="domcontentloaded", timeout=60_000
                )
                if response is None:
                    raise RuntimeError("no_navigation_response")
                if response.status >= 500:
                    raise RuntimeError(f"http_{response.status}")
                if step.wait_absent:
                    page.wait_for_function(
                        "(needles) => needles.every(n => !document.body.innerText.includes(n))",
                        arg=list(step.wait_absent),
                        timeout=60_000,
                    )
                _assert_expectations(page, step)
                if step.api:
                    api_response = page.request.get(step.origin + step.api, timeout=30_000)
                    entry["api_status"] = api_response.status
                    if api_response.status >= 500:
                        raise RuntimeError(f"api_http_{api_response.status}")
                page.screenshot(
                    path=str(directory / f"step-{step.number:02d}.png"),
                    full_page=True,
                    animations="disabled",
                )
                entry["outcome"] = "captured"
            except Exception as error:  # recorded, never hidden
                entry["outcome"] = "failed"
                entry["reason"] = str(error)[:200]
            entry["offset_ms"] = round((time.perf_counter() - started) * 1000)
            records.append(entry)
    finally:
        page.close()
        context.close()

    if video is not None:
        try:
            shutil.move(video.path(), directory / "video.webm")
        except OSError:
            pass
    shutil.rmtree(raw_video, ignore_errors=True)

    captured = [record for record in records if record["outcome"] == "captured"]
    (directory / "captions.vtt").write_text(build_vtt(captured), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "scenario": scene.slug,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "steps": records,
        "blocked_requests": len(blocked),
        "skipped_account_steps": document["account"],
        "media": {
            "video": f"{build_tutorials.MEDIA_KEY_ROOT}/{scene.slug}/video.webm",
            "captions": f"{build_tutorials.MEDIA_KEY_ROOT}/{scene.slug}/captions.vtt",
            "images": {
                f"step-{record['number']:02d}": (
                    f"{build_tutorials.MEDIA_KEY_ROOT}/{scene.slug}/step-{record['number']:02d}.png"
                )
                for record in captured
            },
        },
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def capture(out_root: Path, only: set[str] | None = None) -> list[dict]:
    from playwright.sync_api import sync_playwright

    documents = {document["key"]: document for document in build_tutorials.load_scenarios()}
    manifests: list[dict] = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch(args=["--no-sandbox"])
        try:
            for scene in SCENES:
                if only and scene.slug not in only:
                    continue
                manifests.append(
                    _capture_scene(browser, scene, out_root / scene.slug, documents[scene.slug])
                )
        finally:
            browser.close()
    return manifests


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--scenario",
        action="append",
        choices=[scene.slug for scene in SCENES],
        help="record only this scene (repeatable)",
    )
    args = parser.parse_args(argv)
    only = set(args.scenario) if args.scenario else None
    if args.dry_run:
        print(json.dumps(plan_document(only), ensure_ascii=False, indent=2))
        return 0
    manifests = capture(args.out, only)
    failed = sum(
        1 for manifest in manifests for step in manifest["steps"] if step["outcome"] == "failed"
    )
    print(f"captured_scenes={len(manifests)} failed_steps={failed} out={args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
