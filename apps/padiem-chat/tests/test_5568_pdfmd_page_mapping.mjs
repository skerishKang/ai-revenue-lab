import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = path.join(__dirname, "..", "static", "util-pdfmd.js");
const context = { window: {} };
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
