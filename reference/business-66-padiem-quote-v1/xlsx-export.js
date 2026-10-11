/* B66 · Quote Beta — native XLSX export foundation (#3496)

   Writes a real OOXML (.xlsx) package from a finalized QuoteDraft.

   This module is a FORMAT adapter only. Every business fact and every total
   comes from QuoteCore (normalizeDraft / computeDraftTotals / itemAmount /
   formatKoreanMoneyWords / computeValidUntil). Nothing here recomputes a
   quote, and no Excel formula is ever emitted, so the workbook can never
   become a second calculation authority.

   Zero dependency: the package is assembled with a bounded STORE-method ZIP
   writer (deterministic order, fixed timestamps, CRC32, UTF-8). No macros,
   no external relationships, no remote parts. */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.B66XlsxExport = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var SHEET_NAME = "견적서";
  var XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
  /* Deterministic DOS timestamp: 1980-01-01 00:00:00. Output bytes must not
     depend on wall-clock time so the same draft always yields the same file. */
  var DOS_TIME = 0;
  var DOS_DATE = 33; /* (1980-1980)<<9 | 1<<5 | 1 */
  var MAX_TEXT_CELL = 32767; /* Excel hard limit for a single cell string */
  var INVALID_SHEET_CHARS = /[\\/?*[\]:]/g;
  var INVALID_FILE_CHARS = /[\\/?*[\]:"]/g;

  /* ────────────────────────────── text helpers ────────────────────────────── */

  function xmlEscape(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&apos;");
  }

  /* Excel rejects a control character inside shared/inline strings. */
  function stripControlChars(value) {
    /* eslint-disable-next-line no-control-regex */
    return String(value == null ? "" : value).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
  }

  function cellText(value) {
    var text = stripControlChars(value);
    if (text.length > MAX_TEXT_CELL) text = text.slice(0, MAX_TEXT_CELL);
    return text;
  }

  function cleanNumber(value) {
    var n = Number(value);
    if (!isFinite(n)) return null;
    return Math.round(n * 100) / 100;
  }

  function columnName(index) {
    var name = "";
    var n = index + 1;
    while (n > 0) {
      var rem = (n - 1) % 26;
      name = String.fromCharCode(65 + rem) + name;
      n = Math.floor((n - 1) / 26);
    }
    return name;
  }

  function safeSheetName(value) {
    var name = stripControlChars(value).replace(INVALID_SHEET_CHARS, "");
    if (!name) name = SHEET_NAME;
    return name.slice(0, 31);
  }

  /* ────────────────────────────── CRC32 / ZIP ────────────────────────────── */

  var CRC_TABLE = (function () {
    var table = new Uint32Array(256);
    for (var i = 0; i < 256; i += 1) {
      var c = i;
      for (var k = 0; k < 8; k += 1) {
        c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      }
      table[i] = c >>> 0;
    }
    return table;
  })();

  function crc32(bytes) {
    var crc = 0xFFFFFFFF;
    for (var i = 0; i < bytes.length; i += 1) {
      crc = CRC_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    }
    return (crc ^ 0xFFFFFFFF) >>> 0;
  }

  function utf8Bytes(text) {
    if (typeof TextEncoder === "function") return new TextEncoder().encode(text);
    /* Bounded fallback for hosts without TextEncoder. */
    var out = [];
    for (var i = 0; i < text.length; i += 1) {
      var code = text.charCodeAt(i);
      if (code < 0x80) {
        out.push(code);
      } else if (code < 0x800) {
        out.push(0xC0 | (code >> 6), 0x80 | (code & 0x3F));
      } else if (code >= 0xD800 && code <= 0xDBFF && i + 1 < text.length) {
        var next = text.charCodeAt(i + 1);
        var cp = 0x10000 + ((code - 0xD800) << 10) + (next - 0xDC00);
        out.push(
          0xF0 | (cp >> 18),
          0x80 | ((cp >> 12) & 0x3F),
          0x80 | ((cp >> 6) & 0x3F),
          0x80 | (cp & 0x3F)
        );
        i += 1;
      } else {
        out.push(0xE0 | (code >> 12), 0x80 | ((code >> 6) & 0x3F), 0x80 | (code & 0x3F));
      }
    }
    return new Uint8Array(out);
  }

  function writeU16(view, offset, value) {
    view.setUint16(offset, value & 0xFFFF, true);
  }

  function writeU32(view, offset, value) {
    view.setUint32(offset, value >>> 0, true);
  }

  /* Minimal OOXML package writer: STORE (no compression) entries only.
     Entry order is fixed by the caller, timestamps are fixed, so the same
     inputs always produce byte-identical output. */
  function writeZip(entries) {
    var chunks = [];
    var central = [];
    var offset = 0;
    var i;

    for (i = 0; i < entries.length; i += 1) {
      var entry = entries[i];
      var nameBytes = utf8Bytes(entry.name);
      var dataBytes = entry.data;
      var checksum = crc32(dataBytes);
      var local = new Uint8Array(30 + nameBytes.length);
      var lv = new DataView(local.buffer);

      writeU32(lv, 0, 0x04034B50);
      writeU16(lv, 4, 20); /* version needed */
      writeU16(lv, 6, 0x0800); /* UTF-8 name flag */
      writeU16(lv, 8, 0); /* method: store */
      writeU16(lv, 10, DOS_TIME);
      writeU16(lv, 12, DOS_DATE);
      writeU32(lv, 14, checksum);
      writeU32(lv, 18, dataBytes.length); /* compressed size == size */
      writeU32(lv, 22, dataBytes.length);
      writeU16(lv, 26, nameBytes.length);
      writeU16(lv, 28, 0);
      local.set(nameBytes, 30);

      var centralHeader = new Uint8Array(46 + nameBytes.length);
      var cv = new DataView(centralHeader.buffer);
      writeU32(cv, 0, 0x02014B50);
      writeU16(cv, 4, 20); /* version made by */
      writeU16(cv, 6, 20); /* version needed */
      writeU16(cv, 8, 0x0800);
      writeU16(cv, 10, 0);
      writeU16(cv, 12, DOS_TIME);
      writeU16(cv, 14, DOS_DATE);
      writeU32(cv, 16, checksum);
      writeU32(cv, 20, dataBytes.length);
      writeU32(cv, 24, dataBytes.length);
      writeU16(cv, 28, nameBytes.length);
      writeU16(cv, 30, 0); /* extra */
      writeU16(cv, 32, 0); /* comment */
      writeU16(cv, 34, 0); /* disk */
      writeU16(cv, 36, 0); /* internal attrs */
      writeU32(cv, 38, 0); /* external attrs */
      writeU32(cv, 42, offset);
      centralHeader.set(nameBytes, 46);
      central.push(centralHeader);

      chunks.push(local, dataBytes);
      offset += local.length + dataBytes.length;
    }

    var centralSize = 0;
    for (i = 0; i < central.length; i += 1) centralSize += central[i].length;

    var end = new Uint8Array(22);
    var ev = new DataView(end.buffer);
    writeU32(ev, 0, 0x06054B50);
    writeU16(ev, 4, 0);
    writeU16(ev, 6, 0);
    writeU16(ev, 8, entries.length);
    writeU16(ev, 10, entries.length);
    writeU32(ev, 12, centralSize);
    writeU32(ev, 16, offset);
    writeU16(ev, 20, 0);

    var total = offset + centralSize + end.length;
    var out = new Uint8Array(total);
    var cursor = 0;
    for (i = 0; i < chunks.length; i += 1) {
      out.set(chunks[i], cursor);
      cursor += chunks[i].length;
    }
    for (i = 0; i < central.length; i += 1) {
      out.set(central[i], cursor);
      cursor += central[i].length;
    }
    out.set(end, cursor);
    return out;
  }

  /* ─────────────────────────────── sheet model ─────────────────────────────── */

  /* Style indexes must match cellXfs order in styles.xml. */
  var STYLE = {
    default: 0,
    title: 1,
    label: 2,
    money: 3,
    date: 4,
    tableHeader: 5,
    moneyStrong: 6,
    textWrap: 7
  };

  function createSheet() {
    return { rows: [], merges: [], maxColumn: 5 };
  }

  function ensureRow(sheet, rowIndex) {
    while (sheet.rows.length <= rowIndex) sheet.rows.push([]);
    return sheet.rows[rowIndex];
  }

  /* Every user-provided string is written as an inline string cell, which
     Excel can never interpret as a formula. No <f> element is emitted. */
  function putText(sheet, rowIndex, columnIndex, value, style) {
    var row = ensureRow(sheet, rowIndex);
    row[columnIndex] = {
      kind: "text",
      value: cellText(value),
      style: style === undefined ? STYLE.default : style
    };
    if (columnIndex > sheet.maxColumn) sheet.maxColumn = columnIndex;
  }

  function putNumber(sheet, rowIndex, columnIndex, value, style) {
    var n = cleanNumber(value);
    if (n === null) return;
    var row = ensureRow(sheet, rowIndex);
    row[columnIndex] = {
      kind: "number",
      value: n,
      style: style === undefined ? STYLE.money : style
    };
    if (columnIndex > sheet.maxColumn) sheet.maxColumn = columnIndex;
  }

  /* Excel serial date (days since 1899-12-30), derived only from the draft's
     own ISO date so output never depends on the wall clock. */
  function isoToSerial(isoDate) {
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(isoDate || ""));
    if (!match) return null;
    var utc = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    if (!isFinite(utc)) return null;
    return Math.round((utc - Date.UTC(1899, 11, 30)) / 86400000);
  }

  function putDate(sheet, rowIndex, columnIndex, isoDate, style) {
    var serial = isoToSerial(isoDate);
    if (serial === null) return;
    var row = ensureRow(sheet, rowIndex);
    row[columnIndex] = {
      kind: "number",
      value: serial,
      style: style === undefined ? STYLE.date : style
    };
    if (columnIndex > sheet.maxColumn) sheet.maxColumn = columnIndex;
  }

  function putLabeledValue(sheet, rowIndex, labelColumn, label, value, valueColumn, style) {
    putText(sheet, rowIndex, labelColumn, label, STYLE.label);
    if (value !== undefined && value !== null && String(value) !== "") {
      putText(sheet, rowIndex, valueColumn, value, style === undefined ? STYLE.default : style);
    }
  }

  function mergeRow(sheet, rowIndex, fromColumn, toColumn) {
    if (toColumn <= fromColumn) return;
    sheet.merges.push(
      columnName(fromColumn) + String(rowIndex + 1) + ":" + columnName(toColumn) + String(rowIndex + 1)
    );
  }

  /* ───────────────────────────── OOXML serializing ─────────────────────────── */

  function serializeCell(columnIndex, cell) {
    if (!cell) return "";
    var ref = columnName(columnIndex) + String(cell.__row + 1);
    var styleAttr = cell.style ? ' s="' + cell.style + '"' : "";
    if (cell.kind === "number") {
      return '<c r="' + ref + '"' + styleAttr + '><v>' + cell.value + "</v></c>";
    }
    if (String(cell.value) === "") return "";
    return (
      '<c r="' + ref + '" t="inlineStr"' + styleAttr +
      '><is><t xml:space="preserve">' + xmlEscape(cell.value) + "</t></is></c>"
    );
  }

  function serializeRows(sheet) {
    var xml = "";
    for (var r = 0; r < sheet.rows.length; r += 1) {
      var row = sheet.rows[r];
      var hasContent = false;
      for (var c = 0; c < row.length; c += 1) {
        if (row[c] && !(row[c].kind === "text" && String(row[c].value) === "")) {
          hasContent = true;
          break;
        }
      }
      if (!hasContent) continue;
      var cells = "";
      for (var i = 0; i < row.length; i += 1) {
        var cell = row[i];
        if (!cell) continue;
        if (cell.kind === "text" && String(cell.value) === "") continue;
        cell.__row = r;
        cells += serializeCell(i, cell);
      }
      xml += '<row r="' + (r + 1) + '">' + cells + "</row>";
    }
    return xml;
  }

  function buildWorksheetXml(sheet, options) {
    var lastColumn = columnName(sheet.maxColumn);
    var lastRow = sheet.rows.length;
    var widths = (options && options.columnWidths) || [10, 38, 8, 10, 14, 16];
    var cols = "";
    for (var i = 0; i < widths.length; i += 1) {
      cols += '<col min="' + (i + 1) + '" max="' + (i + 1) + '" width="' + widths[i] + '" customWidth="1"/>';
    }
    var merges = "";
    if (sheet.merges.length) {
      merges =
        '<mergeCells count="' + sheet.merges.length + '">' +
        sheet.merges.map(function (ref) { return '<mergeCell ref="' + ref + '"/>'; }).join("") +
        "</mergeCells>";
    }
    var orientation = (options && options.orientation) || "portrait";
    return (
      XML_HEADER +
      '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
      '<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>' +
      '<dimension ref="A1:' + lastColumn + lastRow + '"/>' +
      '<sheetViews><sheetView workbookViewId="0">' +
      '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>' +
      "</sheetView></sheetViews>" +
      '<sheetFormatPr defaultRowHeight="16"/>' +
      (cols ? "<cols>" + cols + "</cols>" : "") +
      "<sheetData>" + serializeRows(sheet) + "</sheetData>" +
      merges +
      '<pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>' +
      '<pageSetup paperSize="9" orientation="' + xmlEscape(orientation) + '" fitToWidth="1" fitToHeight="0"/>' +
      "</worksheet>"
    );
  }

  function buildStylesXml() {
    return (
      XML_HEADER +
      '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
      '<numFmts count="2">' +
      '<numFmt numFmtId="164" formatCode="#,##0"/>' +
      '<numFmt numFmtId="165" formatCode="yyyy\\-mm\\-dd"/>' +
      "</numFmts>" +
      '<fonts count="3">' +
      '<font><sz val="10"/><name val="Malgun Gothic"/></font>' +
      '<font><b/><sz val="18"/><name val="Malgun Gothic"/></font>' +
      '<font><b/><sz val="10"/><name val="Malgun Gothic"/></font>' +
      "</fonts>" +
      '<fills count="3">' +
      '<fill><patternFill patternType="none"/></fill>' +
      '<fill><patternFill patternType="gray125"/></fill>' +
      '<fill><patternFill patternType="solid"><fgColor rgb="FFEFEFEF"/><bgColor indexed="64"/></patternFill></fill>' +
      "</fills>" +
      '<borders count="2">' +
      "<border><left/><right/><top/><bottom/><diagonal/></border>" +
      '<border><left style="thin"><color indexed="64"/></left><right style="thin"><color indexed="64"/></right>' +
      '<top style="thin"><color indexed="64"/></top><bottom style="thin"><color indexed="64"/></bottom><diagonal/></border>' +
      "</borders>" +
      '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
      '<cellXfs count="8">' +
      '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>' +
      '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1">' +
      '<alignment horizontal="center" vertical="center"/></xf>' +
      '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>' +
      '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>' +
      '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>' +
      '<xf numFmtId="0" fontId="2" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">' +
      '<alignment horizontal="center" vertical="center" wrapText="1"/></xf>' +
      '<xf numFmtId="164" fontId="2" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>' +
      '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">' +
      '<alignment vertical="top" wrapText="1"/></xf>' +
      "</cellXfs>" +
      '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>' +
      "</styleSheet>"
    );
  }

  function buildContentTypesXml() {
    return (
      XML_HEADER +
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
      '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
      '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' +
      "</Types>"
    );
  }

  function buildRootRelsXml() {
    return (
      XML_HEADER +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
      "</Relationships>"
    );
  }

  function buildWorkbookXml(sheetName) {
    return (
      XML_HEADER +
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
      '<workbookPr/><sheets><sheet name="' + xmlEscape(sheetName) + '" sheetId="1" r:id="rId1"/></sheets>' +
      "</workbook>"
    );
  }

  function buildWorkbookRelsXml() {
    return (
      XML_HEADER +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
      '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
      "</Relationships>"
    );
  }

  /* ───────────────────────────── workbook building ─────────────────────────── */

  function resolveCore(options) {
    var candidate =
      (options && options.core) ||
      (typeof window !== "undefined" && window.QuoteCore) ||
      (typeof globalThis !== "undefined" && globalThis.QuoteCore) ||
      null;
    if (!candidate || typeof candidate.computeDraftTotals !== "function") return null;
    return candidate;
  }

  /* Builds the semantic quotation sheet. All money values are written as
     numbers taken from QuoteCore; all text is written as inline strings. */
  function buildSheet(draft, totals, core, options) {
    var sheet = createSheet();
    var opts = options || {};
    var meta = draft.meta || {};
    var sender = draft.sender || {};
    var recipient = draft.recipient || {};
    var items = (totals && totals.effectiveItems) || draft.items || [];
    var row = 0;

    /* Title */
    putText(sheet, row, 0, opts.titleText || "견 적 서", STYLE.title);
    mergeRow(sheet, row, 0, sheet.maxColumn);
    row += 2;

    /* Header block */
    putText(sheet, row, 0, "견적번호", STYLE.label);
    putText(sheet, row, 1, meta.quoteNo || "", STYLE.default);
    putText(sheet, row, 2, "견적일자", STYLE.label);
    putDate(sheet, row, 3, meta.issueDate);
    putText(sheet, row, 4, "건 명", STYLE.label);
    putText(sheet, row, 5, meta.projectName || "", STYLE.default);
    row += 1;

    putLabeledValue(
      sheet, row, 0, "받는 업체",
      [recipient.company, recipient.person].filter(Boolean).join(" / "), 1
    );
    putLabeledValue(sheet, row, 2, "담당자", recipient.person || "", 3);
    putLabeledValue(sheet, row, 4, "받는 주소", recipient.address || "", 5);
    row += 2;

    /* Supplier block */
    putText(sheet, row, 0, "공급자", STYLE.label);
    row += 1;
    putLabeledValue(sheet, row, 0, "회사명", sender.company || "", 1);
    putLabeledValue(sheet, row, 2, "대표자", sender.rep || "", 3);
    putLabeledValue(sheet, row, 4, "담당자", sender.contactPerson || "", 5);
    row += 1;
    putLabeledValue(sheet, row, 0, "사업자등록번호", sender.bizNo || "", 1);
    putLabeledValue(sheet, row, 2, "전화", sender.phone || "", 3);
    putLabeledValue(sheet, row, 4, "이메일", sender.email || "", 5);
    row += 1;
    putLabeledValue(sheet, row, 0, "주소", sender.address || "", 1);
    mergeRow(sheet, row, 1, sheet.maxColumn);
    row += 2;

    /* Validity */
    var validUntil = null;
    if (typeof core.computeValidUntil === "function" && meta.issueDate && meta.validDays) {
      validUntil = core.computeValidUntil(meta.issueDate, meta.validDays);
    }
    putLabeledValue(
      sheet, row, 0, "유효기간",
      validUntil ? "견적일로부터 " + meta.validDays + "일 (" + validUntil + ")" : "견적일로부터 " + (meta.validDays || 0) + "일",
      1
    );
    row += 2;

    /* Item table header */
    var headers = opts.itemHeaders || ["번호", "품명 및 규격", "단위", "수량", "단가", "금액"];
    for (var h = 0; h < headers.length; h += 1) {
      putText(sheet, row, h, headers[h], STYLE.tableHeader);
    }
    var tableHeaderRow = row;
    row += 1;

    /* Item rows — amounts come from QuoteCore.itemAmount via computeDraftTotals */
    var detailBySummary = {};
    if (Array.isArray(draft.detailGroups)) {
      draft.detailGroups.forEach(function (group) {
        (group.items || []).forEach(function (detail) {
          (detailBySummary[group.summaryItemId] = detailBySummary[group.summaryItemId] || []).push(detail);
        });
      });
    }

    var itemCount = 0;
    items.forEach(function (item) {
      itemCount += 1;
      putNumber(sheet, row, 0, itemCount, STYLE.default);
      putText(sheet, row, 1, item.name || "", STYLE.default);
      putText(sheet, row, 2, item.unit || "", STYLE.default);
      putNumber(sheet, row, 3, core.parseMoney(item.qty), STYLE.default);
      putNumber(sheet, row, 4, core.parseMoney(item.unitPrice), STYLE.money);
      putNumber(sheet, row, 5, core.itemAmount(item), STYLE.money);
      row += 1;

      (detailBySummary[item.id] || []).forEach(function (detail) {
        putText(sheet, row, 1, "  · " + (detail.name || ""), STYLE.default);
        if (detail.unit) putText(sheet, row, 2, detail.unit, STYLE.default);
        putNumber(sheet, row, 3, core.parseMoney(detail.qty), STYLE.default);
        putNumber(sheet, row, 4, core.parseMoney(detail.unitPrice), STYLE.money);
        putNumber(sheet, row, 5, core.itemAmount(detail), STYLE.money);
        row += 1;
      });
    });
    if (itemCount === 0) {
      putText(sheet, row, 1, "", STYLE.default);
      row += 1;
    }

    /* Totals — every value is the QuoteCore-authoritative number */
    if (totals) {
      row += 1;
      putText(sheet, row, 1, "공급가액", STYLE.label);
      putNumber(sheet, row, 5, totals.supply, STYLE.moneyStrong);
      row += 1;
      putText(sheet, row, 1, "부가세", STYLE.label);
      putNumber(sheet, row, 5, totals.vat, STYLE.money);
      row += 1;
      putText(sheet, row, 1, "총액", STYLE.label);
      putNumber(sheet, row, 5, totals.grand, STYLE.moneyStrong);
      row += 1;

      var korean = typeof core.formatKoreanMoneyWords === "function"
        ? core.formatKoreanMoneyWords(totals.grand)
        : null;
      if (korean) {
        putText(sheet, row, 1, "일금", STYLE.label);
        putText(sheet, row, 2, korean + "원정", STYLE.default);
        mergeRow(sheet, row, 2, sheet.maxColumn);
        row += 1;
      }
    }

    /* Notes */
    if (draft.memo) {
      row += 1;
      putText(sheet, row, 0, "메모 / 특기사항", STYLE.label);
      row += 1;
      putText(sheet, row, 0, draft.memo, STYLE.textWrap);
      mergeRow(sheet, row, 0, sheet.maxColumn);
    }

    return { sheet: sheet, tableHeaderRow: tableHeaderRow };
  }

  /**
   * Build a native .xlsx byte package from a finalized QuoteDraft.
   * @param {object} rawDraft canonical QuoteDraft (normalized via QuoteCore)
   * @param {object} [options] { core, sheetName, titleText, itemHeaders, orientation, columnWidths }
   * @returns {Uint8Array}
   */
  function buildWorkbook(rawDraft, options) {
    var opts = options || {};
    var core = resolveCore(opts);
    if (!core) {
      throw new Error("b66_xlsx_core_required");
    }
    var draft = core.normalizeDraft(rawDraft);
    if (!draft) {
      throw new Error("b66_xlsx_invalid_draft");
    }
    var totals = core.computeDraftTotals(draft);
    var built = buildSheet(draft, totals, core, opts);
    var sheetName = safeSheetName(opts.sheetName || SHEET_NAME);

    var entries = [
      { name: "[Content_Types].xml", data: utf8Bytes(buildContentTypesXml()) },
      { name: "_rels/.rels", data: utf8Bytes(buildRootRelsXml()) },
      { name: "xl/workbook.xml", data: utf8Bytes(buildWorkbookXml(sheetName)) },
      { name: "xl/_rels/workbook.xml.rels", data: utf8Bytes(buildWorkbookRelsXml()) },
      { name: "xl/styles.xml", data: utf8Bytes(buildStylesXml()) },
      { name: "xl/worksheets/sheet1.xml", data: utf8Bytes(buildWorksheetXml(built.sheet, opts)) }
    ];

    return writeZip(entries);
  }

  function exportXlsx(rawDraft, options) {
    return buildWorkbook(rawDraft, options);
  }

  /** Deterministic download file name for the current draft. */
  function suggestFileName(rawDraft, options) {
    var opts = options || {};
    var core = resolveCore(opts);
    var draft = (core && core.normalizeDraft(rawDraft)) || rawDraft || {};
    var quoteNo = draft && draft.meta && draft.meta.quoteNo ? String(draft.meta.quoteNo) : "";
    var safeNo = quoteNo.replace(INVALID_FILE_CHARS, "-").trim() || "quote";
    var prefix = opts.filePrefix || "CGI-견적서-";
    return (prefix + safeNo + ".xlsx").replace(/[\\/?*[\]:"]/g, "-");
  }

  return {
    SHEET_NAME: SHEET_NAME,
    buildWorkbook: buildWorkbook,
    exportXlsx: exportXlsx,
    suggestFileName: suggestFileName,
    crc32: crc32,
    xmlEscape: xmlEscape
  };
});