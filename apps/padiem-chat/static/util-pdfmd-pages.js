/* PDF to Markdown compare view: page numbering and the original page pane (#7834).
 *
 * Two pieces that the screen needs and the utility module had grown into:
 *
 * * Page numbering. The number a control asks for is the answer; the Markdown
 *   pane's scroll position is only evidence about where the text happens to be.
 *   Reading the page back out of geometry is what used to undo a page change:
 *   the last page of a document cannot be scrolled to the top, so the pane
 *   answered "the page before it" and overwrote the number just typed.
 * * The original pane. It shows one image of the page being compared, rendered
 *   by the app itself. A same-origin frame of the PDF depended on the page
 *   policy allowing that frame and on the browser carrying an inline PDF
 *   viewer; both could say no and the pane looked empty.
 *
 * Both are plain DOM and plain arithmetic, so they live beside the utility and
 * keep `util-pdfmd.js` inside its size ceiling.
 */
(() => {
  "use strict";

  function splitMarkdownPages(markdown) {
    const source = String(markdown || "");
    const marker = /<!--\s*padiem:page\s+(\d+)\s*-->/g;
    const matches = Array.from(source.matchAll(marker));
    if (!matches.length) return [{ number: 1, text: source }];
    return matches.map((match, index) => {
      const start = match.index + match[0].length;
      const end = index + 1 < matches.length ? matches[index + 1].index : source.length;
      return {
        number: Number(match[1]),
        text: source.slice(start, end).replace(/^\r?\n+/, ""),
      };
    });
  }

  function reviewPageNumbers(report) {
    const source = report && typeof report === "object" ? report : {};
    const pages = new Set();
    (Array.isArray(source.pages) ? source.pages : []).forEach((row) => {
      if (row && row.native_text_present === false && Number(row.number) > 0) pages.add(Number(row.number));
    });
    (Array.isArray(source.agreement) ? source.agreement : []).forEach((row) => {
      if (row && Number(row.character_coverage) < 0.99 && Number(row.page) > 0) pages.add(Number(row.page));
    });
    (Array.isArray(source.mismatches) ? source.mismatches : []).forEach((row) => {
      if (row && Number(row.page) > 0) pages.add(Number(row.page));
    });
    (Array.isArray(source.warnings) ? source.warnings : []).forEach((warning) => {
      const match = String(warning).match(/(?:^|:)unreadable_page:(\d+)/);
      if (match) pages.add(Number(match[1]));
    });
    const summary = source.agreement_summary;
    (summary && Array.isArray(summary.review_pages) ? summary.review_pages : []).forEach((page) => {
      if (Number(page) > 0) pages.add(Number(page));
    });
    return Array.from(pages).sort((a, b) => a - b);
  }

  // Page controls (#7834). The number the owner asked for is the answer; the
  // scroll position is only evidence about the Markdown pane. Reading the page
  // back from geometry is what used to undo a page change: on the last page the
  // pane cannot scroll far enough to put that page at the top, so the scroll
  // listener decided the owner was still on the page before it.
  function pageTarget(requested, count) {
    const total = Math.max(1, Number(count) || 1);
    const value = Number(requested);
    if (!Number.isFinite(value)) return 1;
    return Math.max(1, Math.min(total, Math.round(value)));
  }

  function pageForScroll(rows, viewTop, tolerance, atEnd) {
    const limit = Number(tolerance) || 0;
    let page = null;
    let last = null;
    (Array.isArray(rows) ? rows : []).forEach((row) => {
      const number = Number(row && row.page);
      const top = Number(row && row.top);
      if (!(number > 0)) return;
      last = number;
      if (Number.isFinite(top) && top - viewTop <= limit) page = number;
    });
    // At the end of a longer document the pane cannot put the final page at the
    // top, so the top edge still belongs to the page before it. The end of the
    // scroll means the last page, and saying so keeps the number and the
    // original page image on the page the owner actually reached.
    if (atEnd && last !== null) return last;
    return page;
  }

  // One page of the item's original, rendered by the server. Rendering is done
  // per page, so a page that cannot be rendered (beyond the document, a damaged
  // original) answers 404 and this pane says so instead of showing a broken
  // image next to real Markdown.
  function originalPane(el) {
    const pane = el("div", "pdfmd-pane");
    pane.appendChild(el("span", "pdfmd-pane-label", "원본 PDF"));
    const image = document.createElement("img");
    image.className = "pdfmd-original-page";
    image.alt = "원본 PDF";
    image.decoding = "async";
    pane.appendChild(image);
    const notice = el("p", "pdfmd-warn", "");
    notice.hidden = true;
    pane.appendChild(notice);
    const openButton = el("button", "pdfmd-btn", "원본 PDF 열기");
    openButton.type = "button";
    openButton.setAttribute("aria-label", "원본 PDF를 새 창에서 열기");
    pane.appendChild(openButton);

    function itemUrl(item, suffix) {
      return item ? "/api/document-conversions/items/" + item.id + suffix : "";
    }

    image.addEventListener("error", () => {
      if (!image.getAttribute("src")) return;
      image.hidden = true;
      notice.textContent = "이 쪽의 원본을 그림으로 표시하지 못했습니다. 아래 '원본 PDF 열기'로 확인해 주세요.";
      notice.hidden = false;
    });
    openButton.addEventListener("click", () => {
      const href = openButton.dataset.href;
      if (href) window.open(href, "_blank", "noopener");
    });

    return {
      pane: pane,
      element: image,
      reset() {
        image.removeAttribute("src");
        notice.hidden = true;
      },
      show(item, number) {
        if (!item) return;
        openButton.dataset.href = itemUrl(item, "/original?display=inline");
        const target = itemUrl(item, "/original/" + number + ".jpeg");
        if (image.getAttribute("src") === target) return;
        notice.hidden = true;
        image.hidden = false;
        image.alt = "원본 PDF " + number + "쪽";
        image.src = target;
      },
    };
  }

  window.PadiemPdfMdPageMap = Object.freeze({
    splitPages: splitMarkdownPages,
    reviewPages: reviewPageNumbers,
    pageTarget: pageTarget,
    pageForScroll: pageForScroll,
  });
  window.PadiemPdfMdOriginalPane = Object.freeze({ create: originalPane });
})();
