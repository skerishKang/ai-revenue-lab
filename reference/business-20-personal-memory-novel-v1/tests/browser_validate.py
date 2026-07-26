from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageOps
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
EVIDENCE.mkdir(exist_ok=True)
CHROMIUM = "/usr/bin/chromium"


def inline_document() -> str:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "styles.css").read_text(encoding="utf-8")
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    html = re.sub(r'<link rel="stylesheet"[^>]+>', f"<style>{css}</style>", html, count=1)
    html = re.sub(r'<script src="app\.js\?[^\"]+"></script>', f"<script>history.replaceState=()=>{{}};</script><script>{js}</script>", html, count=1)
    for path in (ROOT / "assets/images").glob("*.svg"):
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        html = html.replace(f'assets/images/{path.name}', f'data:image/svg+xml;base64,{encoded}')
    return html

DOCUMENT = inline_document()


def load_state(page, state: str) -> None:
    page.set_content(DOCUMENT, wait_until="load")
    page.evaluate("([state]) => window.__memoryNovelReview.setState(state, {updateUrl:false})", [state])


def screenshot(page, state: str, name: str, width: int, height: int, reduced: bool = False) -> dict:
    page.set_viewport_size({"width": width, "height": height})
    page.emulate_media(reduced_motion="reduce" if reduced else "no-preference")
    load_state(page, state)
    if state == "draft":
        page.wait_for_timeout(30 if reduced else 820)
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    output = EVIDENCE / name
    page.screenshot(path=str(output), full_page=False)
    with Image.open(output) as captured:
        gray = ImageOps.autocontrast(captured.convert("RGB").convert("L"))
        scale = 0.125 if width > 500 else 0.25
        compact = gray.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
        monochrome = compact.point(lambda value: 255 if value > 168 else 0, mode="1")
        monochrome = monochrome.resize((width, height), Image.Resampling.NEAREST)
        monochrome.save(output, optimize=True, compress_level=9)
    return {"state": state, "viewport": [width, height], "overflow": overflow, "file": name, "reduced": reduced}


def main() -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []
    runtime_requests: list[str] = []
    captures: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM, headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("request", lambda req: runtime_requests.append(req.url))

        captures.append(screenshot(page, "cover", "manuscript-cover-1440x1100.png", 1440, 1100))
        captures.append(screenshot(page, "source", "source-memory-1440x1100.png", 1440, 1100))
        captures.append(screenshot(page, "draft", "scene-draft-1440x1100.png", 1440, 1100))
        captures.append(screenshot(page, "map", "transformation-map-1440x1100.png", 1440, 1100))
        captures.append(screenshot(page, "versions", "two-versions-1440x1100.png", 1440, 1100))
        captures.append(screenshot(page, "proof", "author-proof-1440x1100.png", 1440, 1100))
        captures.append(screenshot(page, "proof", "tablet-author-proof-768x1024.png", 768, 1024))
        captures.append(screenshot(page, "mobile", "mobile-scene-390x844.png", 390, 844))
        captures.append(screenshot(page, "draft", "reduced-motion-1440x1100.png", 1440, 1100, reduced=True))

        page.set_viewport_size({"width": 1440, "height": 1100})
        page.emulate_media(reduced_motion="no-preference")
        load_state(page, "cover")
        page.locator('[data-state-target="cover"]').focus()
        page.keyboard.press("ArrowRight")
        keyboard_selected = page.locator('[data-state-target="source"]').get_attribute("aria-selected") == "true"
        page.keyboard.press("End")
        keyboard_end = page.locator('[data-state-target="mobile"]').get_attribute("aria-selected") == "true"

        load_state(page, "draft")
        page.evaluate("window.__memoryNovelReview.replayFold()")
        frame_paths: list[Path] = []
        for idx, delay in enumerate([0, 170, 170, 170, 170]):
            if delay:
                page.wait_for_timeout(delay)
            frame = EVIDENCE / f".fold-frame-{idx}.png"
            page.screenshot(path=str(frame), full_page=False)
            frame_paths.append(frame)
        concat_file = EVIDENCE / ".fold-frames.txt"
        lines = []
        for frame in frame_paths:
            lines.extend([f"file '{frame.name}'", "duration 0.17"])
        lines.append(f"file '{frame_paths[-1].name}'")
        concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", str(concat_file), "-t", "0.72", "-vf", "scale=320:244:flags=lanczos,fps=8",
            "-c:v", "libx264", "-preset", "veryslow", "-crf", "42", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(EVIDENCE / "fact-to-fiction-fold.mp4")
        ], check=True, cwd=EVIDENCE)
        concat_file.unlink(missing_ok=True)
        for path in frame_paths:
            path.unlink(missing_ok=True)

        labels_visible = page.evaluate("""() => ['FACT','INFERENCE','FICTION','REDACTED','AUTHOR APPROVED'].every(label => document.body.innerText.includes(label))""")
        synthetic_visible = page.evaluate("document.body.innerText.includes('합성')")
        local_image_failures = page.evaluate("""() => [...document.images].filter(img => !img.complete || img.naturalWidth === 0).map(img => img.alt)""")
        version = page.evaluate("window.__memoryNovelReview.version")
        browser.close()

    failures = []
    if any(capture["overflow"] != 0 for capture in captures): failures.append("horizontal overflow")
    if console_errors: failures.append("console errors")
    if page_errors: failures.append("page errors")
    if runtime_requests: failures.append("runtime requests")
    if local_image_failures: failures.append("local image failures")
    if not keyboard_selected or not keyboard_end: failures.append("keyboard tab switching")
    if not labels_visible or not synthetic_visible: failures.append("truth labels")
    if version != "memory-novel-20260727-1": failures.append("deterministic version")

    result = {
        "status": "pass" if not failures else "fail",
        "version": version,
        "captures": captures,
        "console_errors": console_errors,
        "page_errors": page_errors,
        "external_runtime_requests": runtime_requests,
        "local_image_failures": local_image_failures,
        "keyboard": {"arrow_right": keyboard_selected, "end": keyboard_end},
        "truth_labels_visible": labels_visible,
        "synthetic_label_visible": synthetic_visible,
        "motion_evidence": "fact-to-fiction-fold.mp4",
        "failures": failures,
        "harness_note": "Chromium validation uses an inlined document because this execution environment blocks local URL navigation; production files retain repository-local relative asset paths.",
    }
    (EVIDENCE / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
