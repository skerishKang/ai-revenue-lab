/* B66 #3839: render-only deterministic A4 pagination.
 * No source assets, provider requests, QuoteCore arithmetic, or auto activation.
 * Geometry is supplied exclusively by a separately certified template manifest.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.B66MultipagePlan = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var CONTRACT = "b66.cgi.dynamic-a4-layout.v1";
  var MAX_PLAN_INPUT_BYTES = 1024 * 1024;
  var GEOMETRY = [
    "page_width_pt", "page_height_pt", "first_rows_top_pt",
    "continuation_rows_top_pt", "rows_bottom_pt",
    "final_section_height_pt", "name_column_width_pt",
    "line_height_pt", "row_vertical_padding_pt", "minimum_row_height_pt"
  ];

  function fail(code) {
    var error = new Error(code);
    error.code = code;
    throw error;
  }
  function geometryValid(geometry) {
    if (!geometry || typeof geometry !== "object" || Array.isArray(geometry)) return false;
    if (!GEOMETRY.every(function (key) {
      return Number.isFinite(geometry[key]) && geometry[key] > 0;
    })) return false;
    var g = geometry;
    return g.page_width_pt >= 590 && g.page_width_pt <= 596 &&
      g.page_height_pt >= 839 && g.page_height_pt <= 845 &&
      g.first_rows_top_pt < g.rows_bottom_pt &&
      g.continuation_rows_top_pt < g.rows_bottom_pt &&
      g.rows_bottom_pt < g.page_height_pt &&
      g.final_section_height_pt + g.minimum_row_height_pt <=
        Math.min(g.rows_bottom_pt - g.first_rows_top_pt,
                 g.rows_bottom_pt - g.continuation_rows_top_pt) &&
      2 * g.row_vertical_padding_pt + g.line_height_pt <= 20 * g.minimum_row_height_pt;
  }
  function wrappedName(value, width, measure) {
    if (typeof value !== "string" || !value ||
        /[\x00-\x09\x0B-\x1F]/.test(value) ||
        new TextEncoder().encode(value).length > MAX_PLAN_INPUT_BYTES) fail("invalid_item_text");
    var lines = [], breaks = [];
    value.split("\n").forEach(function (segment, segmentIndex) {
      var line = "", hard = segmentIndex !== 0;
      Array.from(segment).forEach(function (char) {
        var candidate = line + char;
        var len = measure(candidate);
        if (typeof len !== "number" || !Number.isFinite(len) || len < 0)
          fail("invalid_text_measure");
        if (len > width) {
          if (!line) fail("unrenderable_glyph");
          lines.push(line); breaks.push(hard); hard = false;
          line = char;
          var charWidth = measure(char);
          if (typeof charWidth !== "number" || !Number.isFinite(charWidth) ||
              charWidth < 0 || charWidth > width) fail("unrenderable_glyph");
        } else {
          line = candidate;
        }
      });
      lines.push(line); breaks.push(hard);
    });
    if (lines.map(function (line, index) {
      return (breaks[index] ? "\n" : "") + line;
    }).join("") !== value) fail("invalid_item_text");
    return { lines: lines, breaks: breaks };
  }
  function planPages(rows, opts) {
    opts = opts || {};
    var g = opts.geometry, measure = opts.measureNamePt;
    if (!Number.isInteger(opts.contentBytes) || opts.contentBytes < 1 ||
        opts.contentBytes > MAX_PLAN_INPUT_BYTES) fail("request_too_large");
    if (!Array.isArray(rows) || !rows.length) fail("invalid_items");
    if (!geometryValid(g) || typeof measure !== "function")
      fail("invalid_certified_geometry");

    var heights = rows.map(function (row) {
      if (!row || typeof row !== "object" || Array.isArray(row) ||
          typeof row.name !== "string") fail("invalid_items");
      var wrap = wrappedName(row.name, g.name_column_width_pt, measure);
      var height = Math.max(g.minimum_row_height_pt,
        2 * g.row_vertical_padding_pt + g.line_height_pt * wrap.lines.length);
      if (height > Math.min(g.rows_bottom_pt - g.first_rows_top_pt,
                            g.rows_bottom_pt - g.continuation_rows_top_pt))
        fail("row_exceeds_page");
      return { height: height, lines: wrap.lines, hardBreaks: wrap.breaks };
    });
    var suffix = Array(heights.length + 1).fill(0);
    for (var j = heights.length - 1; j >= 0; j--)
      suffix[j] = suffix[j+1] + heights[j].height;

    var pages = [], nextIndex = 0;
    while (nextIndex < heights.length) {
      var first = pages.length === 0;
      var top = first ? g.first_rows_top_pt : g.continuation_rows_top_pt;
      var full = g.rows_bottom_pt - top;
      var withTotals = full - g.final_section_height_pt;
      var isFinal = suffix[nextIndex] <= withTotals + 1e-7;
      var ceiling = top + (isFinal ? withTotals : full), y = top, placed = [];
      while (nextIndex + placed.length < heights.length) {
        var i = nextIndex + placed.length, rowPlan = heights[i];
        if (y + rowPlan.height > ceiling + 1e-7) break;
        placed.push({
          source_index: i, printed_number: i + 1, top_pt: y,
          height_pt: rowPlan.height, wrapped_name: rowPlan.lines,
          hard_break_before: rowPlan.hardBreaks
        });
        y += rowPlan.height;
      }
      if (!isFinal && placed.length === heights.length - nextIndex) placed.pop();
      if (!placed.length)
        fail(heights.length - nextIndex === 1 ? "row_exceeds_final_page" : "row_exceeds_page");
      pages.push({ first_page: first, rows: placed });
      nextIndex += placed.length;
    }
    return pages.map(function (page, index) {
      return Object.assign(page, {
        number: index + 1, total_pages: pages.length,
        show_totals_and_terms: index === pages.length - 1
      });
    });
  }
  return Object.freeze({
    CONTRACT: CONTRACT, MAX_PLAN_INPUT_BYTES: MAX_PLAN_INPUT_BYTES,
    planPages: planPages
  });
});
