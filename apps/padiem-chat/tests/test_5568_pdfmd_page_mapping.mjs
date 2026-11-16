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
