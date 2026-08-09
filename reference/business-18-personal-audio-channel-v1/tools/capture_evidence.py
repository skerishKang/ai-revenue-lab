from __future__ import annotations

import base64
import re
import json
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'evidence'
PORT = 8765
BASE_URL = 'about:blank'

def render_memory_html():
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    css_files = [
        'styles.css',
        'styles-listening.css',
        'styles-editorial.css',
        'styles-mobile.css',
        'styles-responsive.css',
    ]
    css = '\n'.join((ROOT / name).read_text(encoding='utf-8') for name in css_files)
    css = re.sub(r'@import\s+url\([^;]+;\s*', '', css)
    js = (ROOT / 'app.js').read_text(encoding='utf-8')
    html = re.sub(r'<link rel="stylesheet"[^>]+>', '<style data-source="styles.css?v=20260727.1">' + css + '</style>', html)
    html = re.sub(r'<script src="app.js\?v=20260727\.1" defer></script>', '<script data-source="app.js?v=20260727.1">' + js + '</script>', html)
    for asset in (ROOT / 'assets' / 'images').glob('*.svg'):
        encoded = base64.b64encode(asset.read_bytes()).decode('ascii')
        html = html.replace(f'assets/images/{asset.name}', f'data:image/svg+xml;base64,{encoded}')
    return html

MEMORY_HTML = render_memory_html()

def validate_page(page, state: str, viewport: tuple[int, int], screenshot: str | None = None):
    console_errors = []
    page_errors = []
    failed = []
    external = []
    page.on('console', lambda msg: console_errors.append(msg.text) if msg.type == 'error' else None)
    page.on('pageerror', lambda exc: page_errors.append(str(exc)))
    page.on('requestfailed', lambda req: failed.append({'url': req.url, 'error': req.failure}))
    page.on('request', lambda req: external.append(req.url) if not (req.url.startswith('data:') or req.url.startswith('about:')) else None)
    page.set_content(MEMORY_HTML, wait_until='load')
    page.evaluate('(state) => window.__PAC_REVIEW__.showState(state, false)', state)
    page.set_viewport_size({'width': viewport[0], 'height': viewport[1]})
    page.wait_for_timeout(80)
    metrics = page.evaluate('''() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      states: document.querySelectorAll('[data-state]').length,
      visibleStates: [...document.querySelectorAll('[data-state]')].filter(x => !x.hidden).map(x => x.dataset.state),
      syntheticText: document.body.innerText.includes('합성') && document.body.innerText.toLowerCase().includes('synthetic'),
      cssVersion: !!document.querySelector('style[data-source="styles.css?v=20260727.1"]'),
      jsVersion: !!document.querySelector('script[data-source="app.js?v=20260727.1"]'),
      images: [...document.images].map(img => ({src: img.getAttribute('src'), complete: img.complete, width: img.naturalWidth}))
    })''')
    page.keyboard.press('Tab')
    focus = page.evaluate('''() => {
      const el = document.activeElement;
      const s = getComputedStyle(el);
      return {tag: el.tagName, text: el.textContent.trim().slice(0, 40), outlineStyle: s.outlineStyle, outlineWidth: s.outlineWidth};
    }''')
    if screenshot:
        page.evaluate("document.activeElement?.blur()")
        page.screenshot(path=str(EVIDENCE / screenshot), animations='disabled')
    return {
        'state': state,
        'viewport': list(viewport),
        'horizontal_overflow': max(0, metrics['scrollWidth'] - metrics['clientWidth']),
        'states': metrics['states'],
        'visible_states': metrics['visibleStates'],
        'synthetic_disclosure': metrics['syntheticText'],
        'version_queries': metrics['cssVersion'] and metrics['jsVersion'],
        'images_ok': all(i['complete'] and i['width'] > 0 for i in metrics['images']),
        'keyboard_focus': focus,
        'console_errors': console_errors,
        'page_errors': page_errors,
        'failed_requests': failed,
        'external_requests': external,
    }


def capture_motion(browser):
    context = browser.new_context(viewport={'width': 1440, 'height': 1100})
    page = context.new_page()
    page.set_content(MEMORY_HTML, wait_until='load')
    page.evaluate("window.__PAC_REVIEW__.showState('listening', false)")
    trigger = page.locator('[data-pulse-trigger]')
    trigger.focus()
    focus_before = page.evaluate('document.activeElement.textContent.trim()')
    scroll_before = page.evaluate('window.scrollY')
    frame_paths = []
    trigger.click()
    start = time.perf_counter()
    for index, delay in enumerate([0, 90, 110, 120, 140, 170, 180]):
        if delay:
            page.wait_for_timeout(delay)
        path = EVIDENCE / f'_pulse_{index}.png'
        page.screenshot(path=str(path))
        frame_paths.append(path)
    elapsed = (time.perf_counter() - start) * 1000
    page.wait_for_timeout(80)
    focus_after = page.evaluate('document.activeElement.textContent.trim()')
    scroll_after = page.evaluate('window.scrollY')
    final = page.evaluate('''() => ({
      title: document.querySelector('[data-pulse-title]').textContent.trim(),
      citation: document.querySelector('[data-pulse-source]').textContent.trim(),
      active: document.querySelector('[data-state="listening"]').classList.contains('chapter-pulsing')
    })''')
    images = []
    for p in frame_paths:
        im = Image.open(p).convert('P', palette=Image.Palette.ADAPTIVE)
        im.thumbnail((960, 734))
        images.append(im.copy())
    gif_path = EVIDENCE / 'chapter-pulse.gif'
    images[0].save(gif_path, save_all=True, append_images=images[1:], duration=[90,110,120,140,170,180,220], loop=0, optimize=True)
    for p in frame_paths:
        p.unlink(missing_ok=True)
    context.close()
    return {
        'capture_elapsed_ms': round(elapsed),
        'specified_duration_ms': 680,
        'focus_stable': focus_before == focus_after,
        'scroll_stable': scroll_before == scroll_after,
        'final_title': final['title'],
        'final_citation': final['citation'],
        'animation_class_removed': not final['active'],
        'gif': gif_path.name,
    }


def capture_reduced(browser):
    context = browser.new_context(viewport={'width': 1440, 'height': 1100}, reduced_motion='reduce')
    page = context.new_page()
    page.set_content(MEMORY_HTML, wait_until='load')
    page.evaluate("window.__PAC_REVIEW__.showState('listening', false)")
    start = time.perf_counter()
    page.locator('[data-pulse-trigger]').click()
    page.wait_for_timeout(20)
    elapsed = (time.perf_counter() - start) * 1000
    values = page.evaluate('''() => ({
      title: document.querySelector('[data-pulse-title]').textContent.trim(),
      citationOpacity: getComputedStyle(document.querySelector('[data-pulse-source]')).opacity,
      progressWidth: getComputedStyle(document.querySelector('[data-pulse-row]'), '::before').width
    })''')
    page.screenshot(path=str(EVIDENCE / 'reduced-motion-1440x1100.png'), animations='disabled')
    context.close()
    return {'elapsed_ms': round(elapsed), **values}


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    for old in EVIDENCE.glob('*'):
        old.unlink()
    report = {'generated_at': '2026-07-27', 'served_from': BASE_URL, 'localhost_blocked': True, 'validation_mode': 'in-memory HTML via page.set_content' , 'checks': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        captures = [
            ('today', (1440,1100), 'today-edition-1440x1100.png'),
            ('listening', (1440,1100), 'listening-view-1440x1100.png'),
            ('sources', (1440,1100), 'source-shelf-1440x1100.png'),
            ('script', (1440,1100), 'episode-script-1440x1100.png'),
            ('letter', (1440,1100), 'audio-letter-1440x1100.png'),
            ('archive', (1440,1100), 'channel-archive-1440x1100.png'),
            ('mobile', (1440,1100), 'mobile-composition-1440x1100.png'),
            ('listening', (768,1024), 'listening-view-768x1024.png'),
            ('listening', (390,844), 'mobile-listening-390x844.png'),
        ]
        for state, viewport, shot in captures:
            context = browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]})
            page = context.new_page()
            report['checks'].append(validate_page(page, state, viewport, shot))
            context.close()
        report['motion'] = capture_motion(browser)
        report['reduced_motion'] = capture_reduced(browser)
        browser.close()
    report['summary'] = {
        'all_overflow_zero': all(c['horizontal_overflow'] == 0 for c in report['checks']),
        'all_console_zero': all(not c['console_errors'] and not c['page_errors'] for c in report['checks']),
        'all_assets_ok': all(c['images_ok'] and not c['failed_requests'] for c in report['checks']),
        'all_external_zero': all(not c['external_requests'] for c in report['checks']),
        'all_versions_deterministic': all(c['version_queries'] for c in report['checks']),
        'all_synthetic_disclosed': all(c['synthetic_disclosure'] for c in report['checks']),
        'seven_states': all(c['states'] == 7 for c in report['checks']),
    }
    (EVIDENCE / 'validation-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
