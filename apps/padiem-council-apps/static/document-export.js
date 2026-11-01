// 2026-11-01: result downloads in 한글(HWPX)·워드(DOCX) — fully client-side.
// No server round trip: the bytes are built in the browser and handed to the
// usual <a download> flow. The ZIP writer below is this app's own (STORE
// method, UTF-8 names — a spec-valid zip Word and 한글 both read). The HWPX
// package skeleton (mimetype/version.xml/container/manifest/settings/
// content.hpf/header.xml/section0.xml, 함초롬바탕 charPr·paraPr set) is adapted
// from @kimdayoun/hwpx-mcp (MIT, © 2024 mjyoo; enhanced by Dayoooun; fork of
// mjyoo2/hwp-extension) — the notice lives in THIRD_PARTY_NOTICES.md. The
// DOCX part ports this repository's own deterministic OOXML exporter
// (apps/korean-ai-code-agent/src/kagent/document_export.py, #2016/#2115).
// No third-party JavaScript ships in this file.
(function (root) {
  "use strict";

  const HWPX_MIME = "application/hwp+zip";
  const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

  // ── bytes helpers ────────────────────────────────────────────────────────
  const encoder = new TextEncoder();
  function utf8(text) { return encoder.encode(String(text)); }

  function escapeXml(text) {
    return String(text).replace(/[&<>"']/g, (ch) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" }[ch]
    ));
  }

  let crcTable = null;
  function crc32(bytes) {
    if (!crcTable) {
      crcTable = new Uint32Array(256);
      for (let n = 0; n < 256; n += 1) {
        let c = n;
        for (let k = 0; k < 8; k += 1) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
        crcTable[n] = c >>> 0;
      }
    }
    let crc = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i += 1) crc = crcTable[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    return (crc ^ 0xFFFFFFFF) >>> 0;
  }

  function dosDateTime(date) {
    const time = ((date.getHours() & 0x1F) << 11) | ((date.getMinutes() & 0x3F) << 5) | ((date.getSeconds() / 2) & 0x1F);
    const day = (((date.getFullYear() - 1980) & 0x7F) << 9) | (((date.getMonth() + 1) & 0x0F) << 5) | (date.getDate() & 0x1F);
    return { time, day };
  }

  // Minimal ZIP writer (STORE): spec-valid local headers + central directory
  // + EOCD. UTF-8 filename flag is set, so Korean folder/file names stay
  // readable. Entries keep the given order — HWPX wants `mimetype` first.
  function buildZip(entries, now) {
    const clock = dosDateTime(now || new Date());
    const chunks = [];
    const central = [];
    let offset = 0;
    const u16 = (v) => new Uint8Array([v & 0xFF, (v >>> 8) & 0xFF]);
    const u32 = (v) => new Uint8Array([v & 0xFF, (v >>> 8) & 0xFF, (v >>> 16) & 0xFF, (v >>> 24) & 0xFF]);

    entries.forEach((entry) => {
      const name = utf8(entry.name);
      const data = entry.data || new Uint8Array(0);
      const crc = entry.dir ? 0 : crc32(data);
      const head = [
        u32(0x04034B50), u16(20), u16(0x0800), u16(0),
        u16(clock.time), u16(clock.day),
        u32(crc), u32(data.length), u32(data.length),
        u16(name.length), u16(0), name,
      ];
      chunks.push(...head, data);
      central.push([
        u32(0x02014B50), u16(20), u16(20), u16(0x0800), u16(0),
        u16(clock.time), u16(clock.day),
        u32(crc), u32(data.length), u32(data.length),
        u16(name.length), u16(0), u16(0), u16(0), u16(0), u32(0),
        u32(offset), name,
      ]);
      offset += head.reduce((n, part) => n + part.length, 0) + data.length;
    });

    let centralSize = 0;
    central.forEach((parts) => { centralSize += parts.reduce((n, part) => n + part.length, 0); });
    chunks.push(...central.flat());
    chunks.push(
      u32(0x06054B50), u16(0), u16(0), u16(entries.length), u16(entries.length),
      u32(centralSize), u32(offset), u16(0),
    );
    const total = chunks.reduce((n, part) => n + part.length, 0);
    const out = new Uint8Array(total);
    let at = 0;
    chunks.forEach((part) => { out.set(part, at); at += part.length; });
    return out;
  }

  // ── the block model shared by both formats ───────────────────────────────
  // {kind:'title'|'heading'|'period'|'para'|'blank', text}
  const HEADING_RE = /^\s*(?:제?\s*\d+\s*장|\d+\s*[.)]|[IVX]+\.)\s*\S/;
  const PERIOD_RE = /\d{4}[.\-]\d{1,2}[.\-]\d{1,2}\s*(?:~|–|부터|-)\s*\d{4}[.\-]\d{1,2}[.\-]\d{1,2}|^\s*기간\s*[:：]/;

  function blocksFromText(text, options) {
    const opts = options || {};
    const blocks = [];
    const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    let first = true;
    lines.forEach((raw) => {
      const line = raw.replace(/\s+$/, "");
      if (!line.trim()) {
        if (blocks.length && blocks[blocks.length - 1].kind !== "blank") blocks.push({ kind: "blank" });
        return;
      }
      if (first && opts.firstLineTitle) {
        // The book draft opens with its title (optionally "1. 제목") — the
        // same first line the book file name rule reads.
        blocks.push({ kind: "title", text: line.replace(/^\s*\d+\.\s*/, "").trim() });
      } else if (opts.headings && HEADING_RE.test(line)) {
        blocks.push({ kind: "heading", text: line.trim() });
      } else if (first && opts.firstLineTitle && PERIOD_RE.test(line)) {
        blocks.push({ kind: "period", text: line.trim() });
      } else {
        blocks.push({ kind: "para", text: line.trim() });
      }
      first = false;
    });
    return blocks;
  }

  // ── HWPX (OWPML package, adapted from @kimdayoun/hwpx-mcp, MIT) ──────────
  const HWPX_NAMESPACES = 'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" ' +
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" ' +
    'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" ' +
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" ' +
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" ' +
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" ' +
    'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" ' +
    'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" ' +
    'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" ' +
    'xmlns:dc="http://purl.org/dc/elements/1.1/" ' +
    'xmlns:opf="http://www.idpf.org/2007/opf/" ' +
    'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" ' +
    'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" ' +
    'xmlns:epub="http://www.idpf.org/2007/ops" ' +
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"';

  // charPr set: 0 = 본문(10pt), 1 = 제목(20pt bold), 2 = 소제목(14pt bold).
  // Bold is the <hh:bold/> child, exactly what the reference writes.
  function hwpxCharPr(id, height, bold) {
    return '      <hh:charPr id="' + id + '" height="' + height + '" textColor="#000000" shadeColor="none" ' +
      'useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="1">\n' +
      '        <hh:fontRef hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>\n' +
      '        <hh:ratio hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>\n' +
      '        <hh:spacing hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>\n' +
      '        <hh:relSz hangul="100" latin="100" hanja="100" japanese="100" other="100" symbol="100" user="100"/>\n' +
      '        <hh:offset hangul="0" latin="0" hanja="0" japanese="0" other="0" symbol="0" user="0"/>\n' +
      (bold ? '        <hh:bold/>\n' : "") +
      '      </hh:charPr>\n';
  }

  function hwpxHeader(charProperties) {
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' +
      '<hh:head ' + HWPX_NAMESPACES + ' version="1.1" secCnt="1">' +
      '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>' +
      '<hh:refList><hh:fontfaces itemCnt="1"><hh:fontface lang="HANGUL" fontCnt="1">' +
      '<hh:font id="0" face="함초롬바탕" type="TTF"/></hh:fontface></hh:fontfaces>' +
      '<hh:borderFills itemCnt="2">' +
      '<hh:borderFill id="1" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">' +
      '<hh:slash type="NONE"/><hh:backSlash type="NONE"/>' +
      '<hh:leftBorder type="NONE" width="0.1mm" color="#000000"/>' +
      '<hh:rightBorder type="NONE" width="0.1mm" color="#000000"/>' +
      '<hh:topBorder type="NONE" width="0.1mm" color="#000000"/>' +
      '<hh:bottomBorder type="NONE" width="0.1mm" color="#000000"/>' +
      '<hh:diagonal type="NONE" width="0.1mm" color="#000000"/></hh:borderFill>' +
      '<hh:borderFill id="2" threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0">' +
      '<hh:slash type="NONE"/><hh:backSlash type="NONE"/>' +
      '<hh:leftBorder type="SOLID" width="0.12mm" color="#000000"/>' +
      '<hh:rightBorder type="SOLID" width="0.12mm" color="#000000"/>' +
      '<hh:topBorder type="SOLID" width="0.12mm" color="#000000"/>' +
      '<hh:bottomBorder type="SOLID" width="0.12mm" color="#000000"/>' +
      '<hh:diagonal type="NONE" width="0.12mm" color="#000000"/></hh:borderFill>' +
      '</hh:borderFills>' +
      '<hh:charProperties itemCnt="' + charProperties.length + '">\n' + charProperties.join("") + '    </hh:charProperties>' +
      '<hh:tabProperties itemCnt="1"><hh:tabPr id="0" autoTabLeft="0" autoTabRight="0"/></hh:tabProperties>' +
      '<hh:numberings itemCnt="0"/><hh:bullets itemCnt="0"/>' +
      '<hh:paraProperties itemCnt="1"><hh:paraPr id="0" tabPrIDRef="0" condense="0" fontLineHeight="0" snapToGrid="1" ' +
      'suppressLineNumbers="0" checked="0"><hh:align horizontal="LEFT" vertical="BASELINE"/>' +
      '<hh:heading type="NONE" idRef="0" level="0"/>' +
      '<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="KEEP_WORD" widowOrphan="0" keepWithNext="0" keepLines="0" pageBreakBefore="0" lineWrap="BREAK"/>' +
      '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>' +
      '<hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/></hh:paraPr></hh:paraProperties>' +
      '<hh:styles itemCnt="1"><hh:style id="0" type="PARA" name="바탕글" engName="Body" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0" langId="1042" lockForm="0"/></hh:styles>' +
      '<hh:memoProperties itemCnt="0"/></hh:refList>' +
      '<hh:compatibleDocument targetProgram="HWP201X"/>' +
      '<hh:docOption><hh:linkinfo path="" pageInherit="0" footnoteInherit="0"/></hh:docOption>' +
      '<hh:trackChangeConfig flags="0"/></hh:head>';
  }

  // The first paragraph carries the section properties (page setup), exactly
  // like the reference skeleton; it doubles as the title paragraph. Body
  // paragraphs follow with plain charPrIDRef="0" runs.
  function hwpxSection(titleText, blocks) {
    const first = titleText || "";
    let paras = '<hp:p id="0" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">' +
      '<hp:run charPrIDRef="1"><hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0">' +
      '<hp:grid lineGrid="0" charGrid="0" wongoji="0"/>' +
      '<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>' +
      '<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>' +
      '<hp:pagePr landscape="0" width="59528" height="84188" gutterType="LEFT_ONLY">' +
      '<hp:pageMar header="4252" footer="4252" left="8504" right="8504" top="5668" bottom="4252" gutter="0"/></hp:pagePr>' +
      '<hp:footNotePr><hp:autoNumFormat type="DIGIT"/><hp:noteLine length="-1" type="SOLID" width="0.12mm" color="#000000"/>' +
      '<hp:noteSpacing aboveLine="850" belowLine="567" betweenNotes="283"/><hp:numbering type="CONTINUOUS" newNum="1"/>' +
      '<hp:placement place="EACH_COLUMN" beneathText="0"/></hp:footNotePr>' +
      '<hp:endNotePr><hp:autoNumFormat type="DIGIT"/><hp:noteLine length="14692" type="SOLID" width="0.12mm" color="#000000"/>' +
      '<hp:noteSpacing aboveLine="850" belowLine="567" betweenNotes="0"/><hp:numbering type="CONTINUOUS" newNum="1"/>' +
      '<hp:placement place="END_OF_DOCUMENT" beneathText="0"/></hp:endNotePr></hp:secPr>' +
      '<hp:t>' + escapeXml(first) + '</hp:t></hp:run></hp:p>';
    let id = 1;
    blocks.forEach((block) => {
      const t = escapeXml(block.text || "");
      const charRef = block.kind === "heading" ? '2' : '0';
      if (block.kind === "blank") {
        paras += '<hp:p id="' + id + '" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0"><hp:t></hp:t></hp:run></hp:p>';
      } else if (block.kind === "title") {
        paras += '<hp:p id="' + id + '" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="1"><hp:t>' + t + '</hp:t></hp:run></hp:p>';
      } else if (block.kind === "heading") {
        paras += '<hp:p id="' + id + '" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="2"><hp:t>' + t + '</hp:t></hp:run></hp:p>';
      } else {
        paras += '<hp:p id="' + id + '" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0"><hp:t>' + t + '</hp:t></hp:run></hp:p>';
      }
      id += 1;
    });
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hs:sec ' + HWPX_NAMESPACES + '>' + paras + '</hs:sec>';
  }

  function buildHwpx(options) {
    const opts = options || {};
    const title = String(opts.title || "").trim() || "문서";
    const creator = String(opts.creator || "PADIEM 의원3종");
    const now = new Date().toISOString();
    const blocks = opts.blocks || [];
    const charProperties = [hwpxCharPr(0, 1000, false), hwpxCharPr(1, 2000, true), hwpxCharPr(2, 1400, true)];
    const firstBlock = blocks.find((block) => block.kind === "title");
    const entries = [
      { name: "mimetype", data: utf8(HWPX_MIME) },
      { name: "version.xml", data: utf8('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' +
        '<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tagetApplication="WORDPROCESSOR" ' +
        'major="5" minor="1" micro="1" buildNumber="0" os="1" xmlVersion="1.5" application="Hancom Office Hangul" ' +
        'appVersion="14, 0, 0, 0 WIN32LEWindows_10"/>') },
      { name: "META-INF/container.xml", data: utf8('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' +
        '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">' +
        '<ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/></ocf:rootfiles></ocf:container>') },
      { name: "META-INF/manifest.xml", data: utf8('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' +
        '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>') },
      { name: "settings.xml", data: utf8('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' +
        '<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">' +
        '<ha:CaretPosition listIDRef="0" paraIDRef="0" pos="0"/></ha:HWPApplicationSetting>') },
      { name: "Contents/content.hpf", data: utf8('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' +
        '<opf:package ' + HWPX_NAMESPACES + ' version="" unique-identifier="" id="">' +
        '<opf:metadata><opf:title>' + escapeXml(title) + '</opf:title><opf:language>ko</opf:language>' +
        '<opf:meta name="creator" content="text">' + escapeXml(creator) + '</opf:meta>' +
        '<opf:meta name="CreatedDate" content="text">' + now + '</opf:meta>' +
        '<opf:meta name="ModifiedDate" content="text">' + now + '</opf:meta></opf:metadata>' +
        '<opf:manifest><opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>' +
        '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>' +
        '<opf:item id="settings" href="settings.xml" media-type="application/xml"/></opf:manifest>' +
        '<opf:spine><opf:itemref idref="header" linear="yes"/><opf:itemref idref="section0" linear="yes"/></opf:spine></opf:package>') },
      { name: "Contents/header.xml", data: utf8(hwpxHeader(charProperties)) },
      { name: "Contents/section0.xml", data: utf8(hwpxSection(firstBlock ? firstBlock.text : "", blocks)) },
      { name: "BinData/", dir: true, data: new Uint8Array(0) },
    ];
    return buildZip(entries);
  }

  // ── DOCX (minimal WordprocessingML, ported from kagent document_export) ──
  function docxParagraph(block) {
    const t = escapeXml(block.text || "");
    if (block.kind === "title") {
      return '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="36"/></w:rPr><w:t>' + t + '</w:t></w:r></w:p>';
    }
    if (block.kind === "heading") {
      return '<w:p><w:r><w:rPr><w:b/><w:sz w:val="28"/></w:rPr><w:t>' + t + '</w:t></w:r></w:p>';
    }
    if (block.kind === "period") {
      return '<w:p><w:r><w:rPr><w:i/><w:color w:val="555555"/></w:rPr><w:t>' + t + '</w:t></w:r></w:p>';
    }
    if (block.kind === "blank") return "<w:p/>";
    return '<w:p><w:r><w:t>' + t + '</w:t></w:r></w:p>';
  }

  function buildDocx(options) {
    const opts = options || {};
    const blocks = opts.blocks && opts.blocks.length ? opts.blocks : [{ kind: "blank" }];
    const body = blocks.map(docxParagraph).join("");
    const documentXml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
      body +
      '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>' +
      '</w:body></w:document>';
    return buildZip([
      { name: "[Content_Types].xml", data: utf8('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
        '<Default Extension="xml" ContentType="application/xml"/>' +
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
        '</Types>') },
      { name: "_rels/.rels", data: utf8('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
        '</Relationships>') },
      { name: "word/document.xml", data: utf8(documentXml) },
    ]);
  }

  root.PadiemDocumentExport = {
    buildHwpx: buildHwpx,
    buildDocx: buildDocx,
    blocksFromText: blocksFromText,
    buildZip: buildZip,
    MIME: { hwpx: HWPX_MIME, docx: DOCX_MIME },
  };
})(typeof window !== "undefined" ? window : this);
