"use strict";
const assert = require("node:assert/strict");
const Layout = require("../quote-multipage-plan.js");
const measure = (s) => Array.from(s).length * 4;
const geometry = Object.freeze({
  page_width_pt: 595, page_height_pt: 842,
  first_rows_top_pt: 345, continuation_rows_top_pt: 150,
  rows_bottom_pt: 700, final_section_height_pt: 120,
  name_column_width_pt: 180, line_height_pt: 12,
  row_vertical_padding_pt: 3, minimum_row_height_pt: 22
});
function fixture(n, name = "품목") {
  return Array.from({length: n}, (_, i) => ({
    name: name + " " + (i+1), qty: i+1, unitPrice: 1000+i
  }));
}
function run(rows, g = geometry, bytes = 4096) {
  return Layout.planPages(rows, {geometry: g, measureNamePt: measure, contentBytes: bytes});
}
function error(code, fn) {
  assert.throws(fn, (e) => e.code === code);
}
for (const count of [1, 2, 3, 4, 10, 25, 100, 101, 125, 500]) {
  const rows = fixture(count), original = JSON.stringify(rows);
  const pages = run(rows);
  assert.deepEqual(pages.flatMap((p) => p.rows.map((r) => r.source_index)),
    Array.from({length: count}, (_, i) => i));
  assert.deepEqual(pages.flatMap((p) => p.rows.map((r) => r.printed_number)),
    Array.from({length: count}, (_, i) => i+1));
  assert.equal(JSON.stringify(rows), original);
  assert.deepEqual(pages.map(p => p.number),
    Array.from({length: pages.length}, (_, i) => i+1));
  assert.equal(pages.filter(p => p.show_totals_and_terms).length, 1);
  assert.equal(pages.at(-1).show_totals_and_terms, true);
  pages.forEach((p) => {
    assert.equal(p.total_pages, pages.length);
    const floor = p.first_page ? 345 : 150;
    const ceiling = p.show_totals_and_terms ? 580 : 700;
    p.rows.forEach((r) => {
      assert.ok(r.top_pt >= floor);
      assert.ok(r.top_pt + r.height_pt <= ceiling + 1e-7);
    });
  });
}
const long = "장기공사비용" .repeat(42);
const wrapped = run(fixture(101, long));
wrapped.flatMap(p => p.rows).forEach((r) => {
  assert.equal(r.wrapped_name.map((line, i) =>
    (r.hard_break_before[i] ? "\n" : "") + line).join(""), long + " " + r.printed_number);
  assert.ok(r.wrapped_name.every(s => measure(s) <= 180));
});
const multiline = "철거공사\n재설치공사\n마감검수";
const hard = run([{name: multiline}])[0].rows[0];
assert.equal(hard.wrapped_name.map((line, i) =>
  (hard.hard_break_before[i] ? "\n" : "") + line).join(""), multiline);
const boundary = {...geometry,
  first_rows_top_pt: 480, continuation_rows_top_pt: 480,
  rows_bottom_pt: 680, final_section_height_pt: 100};
assert.equal(run(fixture(4), boundary).length, 1);
assert.deepEqual(run(fixture(5), boundary).map(p => p.rows.length), [4, 1]);
error("row_exceeds_page", () => run(fixture(1, "너무긴품목".repeat(700))));
error("request_too_large", () => run(fixture(101), geometry, 1024*1024+1));
error("invalid_certified_geometry", () => run(fixture(1), {...geometry, page_width_pt: 650}));
error("unrenderable_glyph", () => run(fixture(1), {...geometry, name_column_width_pt: 1}));
error("invalid_item_text", () => run([{name: "wrong\rtext"}]));
error("invalid_items", () => run([]));
assert.equal(Layout.CONTRACT, "b66.cgi.dynamic-a4-layout.v1");
console.log("B66_MULTIPAGE_PLAN=PASS; accepted_item_counts=1,2,3,4,10,25,100,101,125,500");
