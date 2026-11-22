import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// #7834: page numbering lives in its own module beside the utility, which is
// loaded first on the page; the context is shared so it is the same window.
const pagesPath = path.join(__dirname, "..", "static", "util-pdfmd-pages.js");
const sourcePath = path.join(__dirname, "..", "static", "util-pdfmd.js");
const context = { window: {} };
vm.runInNewContext(fs.readFileSync(pagesPath, "utf8"), context);
vm.runInNewContext(fs.readFileSync(sourcePath, "utf8"), context);

test("page anchors split Markdown into matching numbered page blocks", () => {
  const markdown = [
    "<!-- padiem:page 1 -->",
    "",
    "## First page",
    "Line A",
    "<!-- padiem:page 2 -->",
    "",
    "## Second page",
    "Line B",
  ].join("\n");
  const pages = context.window.PadiemPdfMdPageMap.splitPages(markdown);
  assert.deepEqual(
    Array.from(pages, ({ number, text }) => [number, text.trim()]),
    [[1, "## First page\nLine A"], [2, "## Second page\nLine B"]],
  );
  assert.deepEqual(
    Array.from(context.window.PadiemPdfMdPageMap.reviewPages({
      warnings: ["unreadable_page:2"],
      agreement: [{ page: 3, character_coverage: 0.75 }, { page: 1, character_coverage: 1 }],
      agreement_summary: { review_pages: [4] },
    })),
    [2, 3, 4],
  );
});

test("a page chosen by a control is clamped, not read back from geometry", () => {
  const map = context.window.PadiemPdfMdPageMap;
  assert.deepEqual(
    [1, 2, 5, 7, 0, "", "3.4"].map((value) => map.pageTarget(value, 5)),
    [1, 2, 5, 5, 1, 1, 3],
  );
  const tops = [
    { page: 1, top: 0 },
    { page: 2, top: 443 },
    { page: 3, top: 879 },
  ];
  assert.equal(map.pageForScroll(tops, 443, 24, false), 2);
  // The last page cannot be scrolled to the top: geometry answers the page
  // before it, which is why a control's own choice must not be re-read.
  const clamped = [
    { page: 4, top: -294 },
    { page: 5, top: 138 },
  ];
  assert.equal(map.pageForScroll(clamped, 0, 24, false), 4);
  assert.equal(map.pageForScroll(clamped, 0, 24, true), 5);
});

test("#8316 a Markdown pipe table becomes aligned cells, not wrapped text", () => {
  const map = context.window.PadiemPdfMdPageMap;
  assert.equal(typeof map.pageBlocks, "function");
  // A tiny element factory: class -> {cls, children, text}.
  const el = (cls, kind, text) => {
    const node = { cls, kind, text, children: [], style: { cssText: "" } };
    node.appendChild = (child) => node.children.push(child);
    return node;
  };
  const md = [
    "# 견적서",
    "| 구분 | 수량 | 금액 |",
    "|---|---|---|",
    "| 상품A | 2 | 1,000,000 |",
    "| 상품B | 1 | 250,000 |",
    "합계.",
  ].join("\n");
  const blocks = map.pageBlocks(md, el);
  // One <pre> before, one table, one <pre> after; the |---| divider is dropped.
  assert.deepEqual(Array.from(blocks, (b) => b.cls),
    ["pre", "table", "pre"]);
  const table = blocks[1];
  assert.deepEqual(Array.from(table.children, (tr) => Array.from(tr.children, (c) => [c.cls, c.text])), [
    [["th", "구분"], ["th", "수량"], ["th", "금액"]],
    [["td", "상품A"], ["td", "2"], ["td", "1,000,000"]],
    [["td", "상품B"], ["td", "1"], ["td", "250,000"]],
  ]);
  // Prose keeps its byte-for-byte text in a <pre>.
  assert.equal(blocks[0].text, "# 견적서");
  assert.equal(blocks[2].text, "합계.");
  // No page text is rendered through the old single <pre> path any more.
  const source = fs.readFileSync(path.join(__dirname, "..", "static", "util-pdfmd.js"), "utf8");
  assert.match(source, /PadiemPdfMdPageMap\.pageBlocks/);
});

test("#8316 a failed original page recovers when the same page is reselected", () => {
  // The original pane is created from the module; a failed image hides it and
  // shows the notice. Re-selecting the same page must clear that state and
  // re-request the JPEG instead of early-returning on the unchanged src.
  const source = fs.readFileSync(path.join(__dirname, "..", "static", "util-pdfmd-pages.js"), "utf8");
  assert.match(source, /if \(image\.hidden \|\| !notice\.hidden\)/);
  assert.match(source, /image\.removeAttribute\("src"\)/);
  // reset() restores image visibility, so a new item is not left stuck hidden.
  const reset = source.slice(source.indexOf("reset()"), source.indexOf("show(item"));
  assert.match(reset, /image\.hidden = false/);
});
