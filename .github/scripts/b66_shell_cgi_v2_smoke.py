"""Browser contract for the B66 three-pane shell and CGI v2 renderer."""

from __future__ import annotations

import asyncio
import http.server
import os
from pathlib import Path
import socketserver
import threading

import fitz
from PIL import Image, ImageChops, ImageFilter, ImageStat
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
B66 = ROOT / "reference" / "business-66-padiem-quote-v1"
OUT = ROOT / "padiem-reports" / "b66-shell-cgi-v2"
OUT.mkdir(parents=True, exist_ok=True)
MAX_VISUAL_DIFF = 0.04


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class Server(socketserver.TCPServer):
    allow_reuse_address = True


def start_server():
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(B66), **kwargs)
    server = Server(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


async def main() -> int:
    server, thread = start_server()
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
    screen_path = OUT / "cgi-v2-screen.png"
    pdf_path = OUT / "cgi-v2.pdf"
    pdf_png_path = OUT / "cgi-v2-pdf.png"
    browser_path = os.environ.get("B66_PARITY_BROWSER", "").strip() or None

    try:
        async with async_playwright() as pw:
            launch = {"headless": True}
            if browser_path:
                launch["executable_path"] = browser_path
            browser = await pw.chromium.launch(**launch)
            context = await browser.new_context(
                viewport={"width": 1800, "height": 1300},
                device_scale_factor=1,
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_function(
                "window.B66ShellLayout && window.QuoteTemplateRenderer && window.QuoteCore"
            )

            shell = await page.evaluate(
                """() => ({
                  threePane: document.body.classList.contains('b66-three-pane'),
                  railCount: document.querySelectorAll('#shellRail').length,
                  legacyVisible: !!(document.getElementById('padiemAccountPanel') &&
                    document.getElementById('padiemAccountPanel').getClientRects().length),
                  accountInRail: document.querySelectorAll('#shellAccountRow #padiemAccountButton').length,
                  skillInRail: document.querySelectorAll('#shellSkillSelect #padiemSavedSkillSelect').length,
                  templateInRail: document.querySelectorAll('#shellQuoteTemplateSelect #templateSelect').length,
                  newQuoteCount: document.querySelectorAll('#shellNewQuote').length,
                  previewCount: document.querySelectorAll('#shellPreviewHost .preview-wrap').length,
                  quotePaperCount: document.querySelectorAll('#quotePaper').length,
                  composerCount: document.querySelectorAll('#easyComposer').length,
                  iframeCount: document.querySelectorAll('#shellPreviewHost iframe').length,
                  previewWidth: Math.round(document.getElementById('shellPreviewHost').getBoundingClientRect().width)
                })"""
            )
            assert shell["threePane"] is True
            assert shell["railCount"] == 1
            assert shell["legacyVisible"] is False
            assert shell["accountInRail"] == 1
            assert shell["skillInRail"] == 1
            assert shell["templateInRail"] == 1
            assert shell["newQuoteCount"] == 1
            assert shell["previewCount"] == 1
            assert shell["quotePaperCount"] == 1
            assert shell["composerCount"] == 1
            assert shell["iframeCount"] == 0
            assert 300 <= shell["previewWidth"] <= 1000

            await page.click(".shell-preview-collapse")
            assert await page.evaluate("document.body.classList.contains('preview-collapsed')") is True
            await page.click(".shell-preview-reopen")
            assert await page.evaluate("document.body.classList.contains('preview-collapsed')") is False

            await page.click("#shellRailToggle")
            assert await page.evaluate("document.body.classList.contains('rail-collapsed')") is True
            await page.click("#shellRailToggle")
            assert await page.evaluate("document.body.classList.contains('rail-collapsed')") is False

            switch = await page.evaluate(
                """() => {
                  const base = {
                    id: 'skill-cgi-browser-smoke',
                    name: '(주)시지아이 기본 견적서',
                    fixedDefaults: {
                      sender: {
                        company: '(주)시지아이', rep: '김범신', contactPerson: '김범신',
                        bizNo: '410-86-46283', address: '전라남도 장성군 남면 나노산단로 102(삼태리)',
                        phone: '062-576-8100', email: '', presetId: 'saved-skill'
                      },
                      validDays: 7, taxMode: 'EXCLUSIVE', memo: '',
                      calculationPolicy: { grandRounding: { mode: 'FLOOR', unit: 10000 } }
                    },
                    variableSchema: {
                      recipient: true, quoteNo: true, issueDate: true,
                      items: true, memo: true, taxMode: true
                    },
                    internalTemplate: QuoteTemplate.serializeTemplate(QuoteTemplate.builtInTemplate()),
                    provenance: {
                      sourceKind: 'file', sourceName: 'cgi-quotation.pdf',
                      sourceRef: 'source:cgi-browser-smoke',
                      capturedAt: '2026-10-06T00:00:00.000Z',
                      warnings: [], unknowns: [], evidence: []
                    },
                    createdAt: '2026-10-06T00:00:00.000Z',
                    updatedAt: '2026-10-06T00:00:00.000Z'
                  };
                  const unsigned = SavedQuoteSkill.buildSkill(base);
                  const approved = SavedQuoteSkill.buildSkill(Object.assign({}, base, {
                    approval: {
                      schemaVersion: 1, status: 'approved',
                      skillFingerprint: unsigned.fingerprint,
                      approvedBy: 'browser-smoke',
                      approvedAt: '2026-10-06T00:00:00.000Z',
                      approvalRef: 'browser-smoke'
                    }
                  }));
                  const set = B66QuoteSkillBridge.setServerSkill(approved, {});
                  const select = document.getElementById('templateSelect');
                  return {
                    set,
                    initialLayout: document.getElementById('quotePaper').getAttribute('data-layout-variant') || 'GENERIC',
                    cgiOptions: Array.from(select.options).filter(o => o.value === 'cgi-v2').length
                  };
                }"""
            )
            assert switch["set"] is True
            assert switch["initialLayout"] == "GENERIC"
            assert switch["cgiOptions"] == 1

            await page.select_option("#templateSelect", "cgi-v2")
            await page.wait_for_timeout(50)
            selected = await page.evaluate(
                """() => ({
                  selected: B66QuoteTemplateBridge.selectedId(),
                  layout: document.getElementById('quotePaper').getAttribute('data-layout-variant') || 'GENERIC',
                  cgiVisible: !document.getElementById('cgiV2Content').hidden,
                  genericHidden: document.getElementById('quoteGenericContent').hidden
                })"""
            )
            assert selected["selected"] == "cgi-v2"
            assert selected["layout"] == "cgi-v2"
            assert selected["cgiVisible"] is True
            assert selected["genericHidden"] is True

            page.once("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
            await page.click("#shellNewQuote")
            await page.wait_for_timeout(100)
            reset = await page.evaluate(
                """() => ({
                  selected: B66QuoteTemplateBridge.selectedId(),
                  layout: document.getElementById('quotePaper').getAttribute('data-layout-variant') || 'GENERIC'
                })"""
            )
            assert reset["selected"] is None
            assert reset["layout"] == "GENERIC"

            result = await page.evaluate(
                """() => {
                  const profile = B66CgiTemplateV2.approvedProfile({
                    approvedBy: 'operator:central',
                    approvedAt: '2026-10-06T00:00:00.000Z',
                    approvalRef: 'issue-3521',
                    privatePresentation: {
                      bank: '테스트은행 000-000 테스트계정',
                      fax: 'FAX : 000-000-0000'
                    }
                  });
                  const draft = QuoteCore.normalizeDraft({
                    schemaVersion: 1,
                    meta: {
                      quoteNo: 'CGI-SHELL-001',
                      issueDate: '2026-10-06',
                      validDays: 14,
                      source: 'manual',
                      projectName: '배관 교체 공사'
                    },
                    sender: {
                      company: '(주)시지아이',
                      rep: '김범신',
                      contactPerson: '김범신',
                      bizNo: '410-86-46283',
                      address: '광주광역시',
                      phone: '062-576-8100',
                      email: '',
                      presetId: 'cgi-smoke'
                    },
                    recipient: {
                      company: '대한건설',
                      person: '구매담당',
                      address: '',
                      email: ''
                    },
                    items: [{
                      id: 'item-1',
                      name: '배관',
                      spec: '',
                      unit: '미터',
                      qty: 100,
                      unitPrice: 18000
                    }],
                    tax: { mode: 'EXCLUSIVE', rate: 0.1 },
                    memo: ''
                  });
                  const model = QuoteTemplateRenderer.buildRenderModel(
                    draft,
                    profile,
                    { taxReviewRequired: false }
                  );
                  QuoteTemplateRenderer.applyRenderModel(document, model);
                  document.documentElement.style.setProperty('--b66-preview-width', '1000px');
                  return {
                    approved: !!(profile && profile.approved),
                    layout: model.layoutVariant,
                    cgiVisible: !document.getElementById('cgiV2Content').hidden,
                    genericHidden: document.getElementById('quoteGenericContent').hidden,
                    grandModel: model.totals.grandText,
                    grandCgi: document.getElementById('cgiV2GrandTop').textContent,
                    validity: document.getElementById('cgiV2Terms').innerText,
                    pageMargin: getComputedStyle(document.getElementById('quotePaper'))
                      .getPropertyValue('--quote-page-margin').trim()
                  };
                }"""
            )
            await page.wait_for_timeout(300)

            assert result["approved"] is True
            assert result["layout"] == "cgi-v2"
            assert result["cgiVisible"] is True
            assert result["genericHidden"] is True
            assert result["grandModel"] == "₩1,980,000"
            assert result["grandCgi"] == "1,980,000"
            assert "14일" in result["validity"]
            assert result["pageMargin"] == "10mm"

            paper = page.locator("#quotePaper")
            await paper.screenshot(path=str(screen_path))
            await page.pdf(
                path=str(pdf_path),
                print_background=True,
                prefer_css_page_size=True,
                scale=1,
            )
            await browser.close()

        doc = fitz.open(pdf_path)
        assert doc.page_count == 1
        pdf_page = doc[0]
        pdf_text = " ".join(pdf_page.get_text("text").split())
        pix = pdf_page.get_pixmap(matrix=fitz.Matrix(96 / 72, 96 / 72), alpha=False)
        pix.save(str(pdf_png_path))
        doc.close()

        screen = Image.open(screen_path).convert("RGB")
        pdf = Image.open(pdf_png_path).convert("RGB")
        assert abs(screen.width - pdf.width) <= 1
        assert abs(screen.height - pdf.height) <= 1
        for token in ("대한건설", "배관", "1,980,000", "테스트은행"):
            assert token in pdf_text

        if screen.size != pdf.size:
            pdf = pdf.resize(screen.size)
        size = (max(1, screen.width // 4), max(1, screen.height // 4))
        a = screen.convert("L").resize(size).filter(ImageFilter.GaussianBlur(0.7))
        b = pdf.convert("L").resize(size).filter(ImageFilter.GaussianBlur(0.7))
        mean = ImageStat.Stat(ImageChops.difference(a, b)).mean[0] / 255.0
        assert mean <= MAX_VISUAL_DIFF

        print("B66_THREE_PANE_BROWSER=PASS")
        print("B66_LEGACY_ACCOUNT_PANEL_VISIBLE=NO")
        print("B66_PRIMARY_COMPOSER_COUNT=1")
        print("B66_CANONICAL_PREVIEW_COUNT=1")
        print("B66_CGI_IFRAME_COUNT=0")
        print("B66_SAVED_SKILL_SELECTOR_IN_RAIL=PASS")
        print("B66_QUOTE_TEMPLATE_SELECTOR_IN_RAIL=PASS")
        print("B66_CGI_TEMPLATE_SELECTION=PASS")
        print("B66_NEW_QUOTE_TEMPLATE_RESET=PASS")
        print("B66_CGI_V2_BROWSER_RENDER=PASS")
        print(f"B66_CGI_V2_SCREEN_SIZE={screen.width}x{screen.height}")
        print(f"B66_CGI_V2_PDF_SIZE={pdf.width}x{pdf.height}")
        print(f"B66_CGI_V2_SCREEN_PDF_MEAN_ABS_DIFF={mean:.6f}")
        print("B66_CGI_V2_SCREEN_PDF_PARITY=PASS")
        print("MODEL_CALLS=0")
        print("PROVIDER_CALLS=0")
        return 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
