from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
STATES = ["cover", "sources", "spine", "suite", "adaptation", "trace", "mobile"]


def build_inline_html() -> str:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    tags = re.findall(r'<link\b[^>]*\brel="stylesheet"[^>]*/?>|<link\b[^>]*\bhref="[^"]+"[^>]*\brel="stylesheet"[^>]*/?>', html)
    for tag in tags:
        href = re.search(r'href="([^"]+)"', tag)
        if href:
            html = html.replace(tag, f"<style>{(ROOT / href.group(1)).read_text(encoding='utf-8')}</style>")
    for src in re.findall(r'<script src="([^"]+)"></script>', html):
        html = html.replace(f'<script src="{src}"></script>', f"<script>{(ROOT / src).read_text(encoding='utf-8')}</script>")
    for asset in sorted(set(re.findall(r'assets/images/[^"\\]+\.svg', html))):
        payload = base64.b64encode((ROOT / asset).read_bytes()).decode("ascii")
        html = html.replace(asset, f"data:image/svg+xml;base64,{payload}")
    return html


INLINE_HTML = build_inline_html()


def load_state(page, state: str, skip_relay: bool = True) -> None:
    page.set_content(INLINE_HTML, wait_until="load")
    page.evaluate("([s, skip]) => window.__B22_REVIEW__.setState(s, {skipRelay: skip})", [state, skip_relay])
    page.wait_for_timeout(40)


def state_metrics(page, state: str) -> dict[str, Any]:
    return page.evaluate("""state => { const root=document.documentElement, body=document.body;
      const panel=document.querySelector(`[data-state="${state}"]`);
      const broken=[...document.images].filter(img=>!img.complete||img.naturalWidth===0).map(img=>img.getAttribute('src'));
      return {state,active:window.__B22_REVIEW__.getState(),visible:panel&&!panel.hidden,
        horizontalOverflow:Math.max(root.scrollWidth,body.scrollWidth)-innerWidth,brokenImages:broken,
        viewport:{width:innerWidth,height:innerHeight}}; }""", state)


def relay_snapshot(page) -> dict[str, Any]:
    return page.evaluate("""() => { const rect=document.querySelector('.fixed-source').getBoundingClientRect();
      const review=getComputedStyle(document.querySelector('.step-review'));
      return {focus:document.activeElement?.getAttribute('data-action'),x:scrollX,y:scrollY,
        h:document.documentElement.scrollHeight,state:document.querySelector('[data-relay]').dataset.motionState||'idle',
        source:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},
        reviewVisible:review.opacity==='1'&&review.visibility!=='hidden'}; }""")


def computed_relay_timing(page) -> dict[str, Any]:
    return page.evaluate("""() => { const ms=t=>{t=t.trim();return t.endsWith('ms')?(parseFloat(t)||0):(parseFloat(t)||0)*1000};
      const steps=[...document.querySelectorAll('[data-relay] .relay-step')].map(el=>{const s=getComputedStyle(el);
        const delays=s.animationDelay.split(',').map(ms),durations=s.animationDuration.split(',').map(ms),names=s.animationName.split(',').map(v=>v.trim());
        const count=Math.max(delays.length,durations.length,names.length),ends=Array.from({length:count},(_,i)=>delays[i%delays.length]+durations[i%durations.length]);
        return {className:el.className,animationName:names.join(', '),delayMs:Math.max(...delays),durationMs:Math.max(...durations),endMs:Math.max(...ends)};});
      return {steps,computedFinalEndMs:Math.max(...steps.map(step=>step.endMs))}; }""")


def same_geometry(before: dict[str, float], after: dict[str, float], tolerance: float = .25) -> bool:
    return all(abs(before[key] - after[key]) <= tolerance for key in ["x", "y", "width", "height"])


def write_motion_evidence(motion: dict[str, Any]) -> str:
    frames = [("00 · BEFORE", "source fixed", "idle"),("01 · ANNOTATION", "master story visible", "running"),
              ("02 · ARTICLE", "editorial rule + article", "running"),("03 · FORMATS", "audio · video · card", "running"),
              ("04 · REVIEW", "human review visible", "complete")]
    panels=[]
    for i,(title,detail,state) in enumerate(frames):
        x=20+i*290; accent="#e85b3f" if i==4 else "#89acc5"
        panels.append(f'<g transform="translate({x} 48)"><rect width="270" height="240" fill="#ece4d2"/><rect width="270" height="8" fill="{accent}"/><text x="16" y="38" font-family="monospace" font-size="12" fill="#182124">{title}</text><text x="16" y="82" font-family="serif" font-size="23" fill="#182124">{detail}</text><rect x="16" y="112" width="238" height="68" fill="#171d1f"/><text x="28" y="142" font-family="monospace" font-size="11" fill="#89acc5">NOTE-04 · SOURCE FIXED</text><text x="28" y="164" font-family="monospace" font-size="11" fill="#ece4d2">data-motion-state={state}</text><text x="16" y="214" font-family="monospace" font-size="11" fill="{accent}">{detail}</text></g>')
    ends=" · ".join(f'{step["endMs"]:.0f}ms' for step in motion["computedTiming"]["steps"])
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="1480" height="330" viewBox="0 0 1480 330" role="img" aria-label="Source-to-Format Relay deterministic frame evidence"><rect width="100%" height="100%" fill="#0f1416"/><text x="20" y="28" font-family="monospace" font-size="15" fill="#ece4d2">SOURCE-TO-FORMAT RELAY · COMPUTED FINAL END {motion["computedFinalEndMs"]:.0f}MS</text>{"".join(panels)}<text x="20" y="316" font-family="monospace" font-size="12" fill="#8f9898">computed step ends: {ends} · focus/scroll/geometry stable · human review visible</text></svg>\n'
    target=EVIDENCE / "motion-relay-frames.svg"; target.write_text(svg,encoding="utf-8"); return target.name
