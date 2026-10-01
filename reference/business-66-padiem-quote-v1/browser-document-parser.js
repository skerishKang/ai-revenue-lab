/* B66 browser-first native-document parser POC (#3293).
   Local-only document extraction. No model/provider/network authority.
   ZIP/XML formats are parsed with bounded archive rules.
   PDF is signature-checked and left as a truthful residual until a reviewed
   local PDF parser bundle is adopted. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.B66BrowserDocumentParser = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var MAX_INPUT_BYTES = 2 * 1024 * 1024;
  var MAX_ZIP_ENTRIES = 256;
  var MAX_TOTAL_UNCOMPRESSED_BYTES = 32 * 1024 * 1024;
  var MAX_ENTRY_BYTES = 8 * 1024 * 1024;
  var MAX_EXPANSION_RATIO = 100;
  var MAX_TEXT_CHARS = 32000;
  var DEFAULT_TIMEOUT_MS = 5000;
  var WORKER_URL = "browser-document-parser-worker.js";

  function codedError(code) {
    var error = new Error(code);
    error.code = code;
    return error;
  }

  function fail(code) {
    throw codedError(code);
  }

  function extensionOf(name) {
    if (typeof name !== "string") return "";
    var lower = name.trim().toLowerCase();
    var index = lower.lastIndexOf(".");
    return index >= 0 ? lower.slice(index) : "";
  }

  function checkedBytes(buffer) {
    if (!(buffer instanceof ArrayBuffer)) fail("invalid_array_buffer");
    if (buffer.byteLength <= 0) fail("empty_file");
    if (buffer.byteLength > MAX_INPUT_BYTES) fail("document_too_large");
    return new Uint8Array(buffer);
  }

  function u16(view, offset) {
    return view.getUint16(offset, true);
  }

  function u32(view, offset) {
    return view.getUint32(offset, true);
  }

  function decodeUtf8(bytes) {
    if (typeof TextDecoder !== "function") fail("text_decoder_unavailable");
    return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
  }

  function xmlDecode(value) {
    return String(value || "")
      .replace(/&#x([0-9a-fA-F]+);/g, function (_, hex) {
        var cp = parseInt(hex, 16);
        return Number.isFinite(cp) ? String.fromCodePoint(cp) : "";
      })
      .replace(/&#([0-9]+);/g, function (_, decimal) {
        var cp = parseInt(decimal, 10);
        return Number.isFinite(cp) ? String.fromCodePoint(cp) : "";
      })
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, "\"")
      .replace(/&apos;/g, "'")
      .replace(/&amp;/g, "&");
  }

  function normalizeText(text) {
    var normalized = String(text || "")
      .replace(/\r\n?/g, "\n")
      .replace(/[\t\u00a0 ]+/g, " ")
      .replace(/ *\n */g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
    if (!normalized) fail("document_text_empty");
    if (normalized.length > MAX_TEXT_CHARS) fail("local_text_too_large");
    return normalized;
  }

  function tagText(xml, localName) {
    if (!/^[A-Za-z0-9_-]+$/.test(localName)) fail("invalid_xml_tag");
    var pattern = new RegExp(
      "<(?:[A-Za-z_][\\w.-]*:)?" + localName +
      "\\b[^>]*>([\\s\\S]*?)<\\/(?:[A-Za-z_][\\w.-]*:)?" +
      localName + "\\s*>",
      "gi"
    );
    var out = [];
    var total = 0;
    var match;
    while ((match = pattern.exec(xml)) !== null) {
      var value = xmlDecode(match[1].replace(/<[^>]*>/g, ""));
      if (value) {
        out.push(value);
        total += value.length;
      }
      if (total > MAX_TEXT_CHARS) fail("local_text_too_large");
    }
    return out;
  }

  function genericXmlText(xml) {
    return xmlDecode(
      String(xml)
        .replace(/<\?xml[\s\S]*?\?>/gi, " ")
        .replace(/<!--[\s\S]*?-->/g, " ")
        .replace(/<[^>]+>/g, "\n")
    );
  }

  function safeZipName(name) {
    if (!name) fail("zip_invalid_name");
    var normalized = name.replace(/\\/g, "/");
    if (normalized.charAt(0) === "/" || /^[A-Za-z]:/.test(normalized)) {
      fail("zip_path_traversal");
    }
    var parts = normalized.split("/");
    if (parts.some(function (part) { return part === ".."; })) {
      fail("zip_path_traversal");
    }
    if (normalized.indexOf("\0") >= 0) fail("zip_invalid_name");
    return normalized;
  }

  function findEocd(bytes) {
    var min = Math.max(0, bytes.length - 65557);
    for (var i = bytes.length - 22; i >= min; i -= 1) {
      if (
        bytes[i] === 0x50 && bytes[i + 1] === 0x4b &&
        bytes[i + 2] === 0x05 && bytes[i + 3] === 0x06
      ) return i;
    }
    fail("zip_eocd_missing");
  }

  function crc32(bytes) {
    var crc = 0xffffffff;
    for (var i = 0; i < bytes.length; i += 1) {
      crc ^= bytes[i];
      for (var bit = 0; bit < 8; bit += 1) {
        crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
      }
    }
    return (crc ^ 0xffffffff) >>> 0;
  }

  function parseZipDirectory(bytes) {
    if (
      bytes.length < 4 ||
      bytes[0] !== 0x50 || bytes[1] !== 0x4b ||
      [0x03, 0x05, 0x07].indexOf(bytes[2]) === -1
    ) fail("zip_magic_mismatch");

    var view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    var eocd = findEocd(bytes);
    var disk = u16(view, eocd + 4);
    var centralDisk = u16(view, eocd + 6);
    var diskEntries = u16(view, eocd + 8);
    var totalEntries = u16(view, eocd + 10);
    var centralSize = u32(view, eocd + 12);
    var centralOffset = u32(view, eocd + 16);

    if (disk !== 0 || centralDisk !== 0 || diskEntries !== totalEntries) {
      fail("zip_multidisk_unsupported");
    }
    if (
      totalEntries === 0xffff ||
      centralSize === 0xffffffff ||
      centralOffset === 0xffffffff
    ) fail("zip64_unsupported");
    if (totalEntries <= 0 || totalEntries > MAX_ZIP_ENTRIES) {
      fail("zip_entry_count_exceeded");
    }
    if (centralOffset + centralSize > bytes.length || centralOffset >= eocd) {
      fail("zip_central_directory_invalid");
    }

    var entries = [];
    var cursor = centralOffset;
    var claimedTotal = 0;

    for (var index = 0; index < totalEntries; index += 1) {
      if (cursor + 46 > bytes.length || u32(view, cursor) !== 0x02014b50) {
        fail("zip_central_entry_invalid");
      }
      var flags = u16(view, cursor + 8);
      var method = u16(view, cursor + 10);
      var crc = u32(view, cursor + 16);
      var compressedSize = u32(view, cursor + 20);
      var uncompressedSize = u32(view, cursor + 24);
      var nameLength = u16(view, cursor + 28);
      var extraLength = u16(view, cursor + 30);
      var commentLength = u16(view, cursor + 32);
      var localOffset = u32(view, cursor + 42);

      if (flags & 0x0001) fail("encrypted_document_unsupported");
      if (
        compressedSize === 0xffffffff ||
        uncompressedSize === 0xffffffff ||
        localOffset === 0xffffffff
      ) fail("zip64_unsupported");
      if (method !== 0 && method !== 8) fail("zip_compression_unsupported");
      if (uncompressedSize > MAX_ENTRY_BYTES) fail("zip_entry_too_large");
      if (
        compressedSize > 0 &&
        uncompressedSize / compressedSize > MAX_EXPANSION_RATIO
      ) fail("zip_expansion_ratio_exceeded");

      var nameStart = cursor + 46;
      var nameEnd = nameStart + nameLength;
      var next = nameEnd + extraLength + commentLength;
      if (nameEnd > bytes.length || next > bytes.length) fail("zip_entry_bounds_invalid");

      var name = safeZipName(decodeUtf8(bytes.subarray(nameStart, nameEnd)));
      claimedTotal += uncompressedSize;
      if (claimedTotal > MAX_TOTAL_UNCOMPRESSED_BYTES) {
        fail("zip_total_uncompressed_exceeded");
      }

      entries.push({
        name: name,
        method: method,
        crc: crc,
        compressedSize: compressedSize,
        uncompressedSize: uncompressedSize,
        localOffset: localOffset
      });
      cursor = next;
    }
    return entries;
  }

  async function inflateRawBounded(compressed, expectedSize) {
    if (typeof DecompressionStream !== "function") {
      fail("browser_deflate_unavailable");
    }
    var stream;
    try {
      stream = new Blob([compressed]).stream().pipeThrough(
        new DecompressionStream("deflate-raw")
      );
    } catch (_) {
      fail("browser_deflate_unavailable");
    }

    var reader = stream.getReader();
    var chunks = [];
    var total = 0;
    try {
      while (true) {
        var part = await reader.read();
        if (part.done) break;
        var chunk = part.value;
        total += chunk.byteLength;
        if (total > MAX_ENTRY_BYTES || total > expectedSize) {
          try { await reader.cancel(); } catch (_) {}
          fail("zip_inflate_bound_exceeded");
        }
        chunks.push(chunk);
      }
    } finally {
      try { reader.releaseLock(); } catch (_) {}
    }
    if (total !== expectedSize) fail("zip_uncompressed_size_mismatch");

    var output = new Uint8Array(total);
    var offset = 0;
    chunks.forEach(function (chunk) {
      output.set(chunk, offset);
      offset += chunk.byteLength;
    });
    return output;
  }

  async function entryBytes(archive, entry) {
    var view = new DataView(archive.buffer, archive.byteOffset, archive.byteLength);
    var offset = entry.localOffset;
    if (offset + 30 > archive.length || u32(view, offset) !== 0x04034b50) {
      fail("zip_local_header_invalid");
    }
    var flags = u16(view, offset + 6);
    var method = u16(view, offset + 8);
    var nameLength = u16(view, offset + 26);
    var extraLength = u16(view, offset + 28);
    if (flags & 0x0001) fail("encrypted_document_unsupported");
    if (method !== entry.method) fail("zip_method_mismatch");

    var dataStart = offset + 30 + nameLength + extraLength;
    var dataEnd = dataStart + entry.compressedSize;
    if (dataEnd > archive.length || dataEnd < dataStart) fail("zip_entry_bounds_invalid");

    var compressed = archive.subarray(dataStart, dataEnd);
    var output;
    if (entry.method === 0) {
      if (entry.compressedSize !== entry.uncompressedSize) {
        fail("zip_stored_size_mismatch");
      }
      output = new Uint8Array(compressed);
    } else {
      output = await inflateRawBounded(compressed, entry.uncompressedSize);
    }
    if (output.byteLength !== entry.uncompressedSize) fail("zip_uncompressed_size_mismatch");
    if (crc32(output) !== entry.crc) fail("zip_crc_mismatch");
    return output;
  }

  function sortNatural(a, b) {
    return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
  }

  async function selectedXml(archive, entries, predicate) {
    var selected = entries.filter(function (entry) {
      return !entry.name.endsWith("/") && predicate(entry.name);
    }).sort(sortNatural);
    if (!selected.length) fail("document_structure_missing");

    var result = [];
    for (var i = 0; i < selected.length; i += 1) {
      var raw = await entryBytes(archive, selected[i]);
      result.push({ name: selected[i].name, xml: decodeUtf8(raw) });
    }
    return result;
  }

  function docxText(xmlFiles) {
    var out = [];
    xmlFiles.forEach(function (file) {
      var values = tagText(file.xml, "t");
      if (values.length) out.push(values.join(" "));
    });
    return normalizeText(out.join("\n"));
  }

  function pptxText(xmlFiles) {
    var slides = [];
    xmlFiles.forEach(function (file) {
      var values = tagText(file.xml, "t");
      if (values.length) slides.push(values.join(" "));
    });
    return normalizeText(slides.join("\n"));
  }

  function sharedStrings(xml) {
    var result = [];
    var si = /<(?:[A-Za-z_][\w.-]*:)?si\b[^>]*>([\s\S]*?)<\/(?:[A-Za-z_][\w.-]*:)?si\s*>/gi;
    var match;
    var total = 0;
    while ((match = si.exec(xml)) !== null) {
      var text = tagText(match[1], "t").join("");
      result.push(text);
      total += text.length;
      if (total > MAX_TEXT_CHARS) fail("local_text_too_large");
    }
    return result;
  }

  function attr(attrs, name) {
    var pattern = new RegExp("\\b" + name + "\\s*=\\s*[\\\"']([^\\\"']*)[\\\"']", "i");
    var match = pattern.exec(attrs);
    return match ? xmlDecode(match[1]) : "";
  }

  function xlsxSheetText(xml, shared) {
    var rows = [];
    var total = 0;
    var rowRe = /<(?:[A-Za-z_][\w.-]*:)?row\b[^>]*>([\s\S]*?)<\/(?:[A-Za-z_][\w.-]*:)?row\s*>/gi;
    var rowMatch;
    while ((rowMatch = rowRe.exec(xml)) !== null) {
      var cells = [];
      var cellRe = /<(?:[A-Za-z_][\w.-]*:)?c\b([^>]*)>([\s\S]*?)<\/(?:[A-Za-z_][\w.-]*:)?c\s*>/gi;
      var cellMatch;
      while ((cellMatch = cellRe.exec(rowMatch[1])) !== null) {
        var attrs = cellMatch[1];
        var body = cellMatch[2];
        var type = attr(attrs, "t");
        var value = "";
        if (type === "inlineStr") {
          value = tagText(body, "t").join("");
        } else {
          var v = /<(?:[A-Za-z_][\w.-]*:)?v\b[^>]*>([\s\S]*?)<\/(?:[A-Za-z_][\w.-]*:)?v\s*>/i.exec(body);
          var raw = v ? xmlDecode(v[1].replace(/<[^>]*>/g, "").trim()) : "";
          if (type === "s" && /^\d+$/.test(raw)) {
            var index = Number(raw);
            value = index >= 0 && index < shared.length ? shared[index] : "";
          } else {
            value = raw;
          }
        }
        cells.push(value);
      }
      if (cells.some(function (cell) { return cell !== ""; })) {
        var row = cells.join("\t");
        rows.push(row);
        total += row.length;
      }
      if (total > MAX_TEXT_CHARS) fail("local_text_too_large");
    }
    return rows.join("\n");
  }

  function hwpxText(xmlFiles) {
    var sections = [];
    xmlFiles.forEach(function (file) {
      var values = tagText(file.xml, "t");
      var text = values.length ? values.join(" ") : genericXmlText(file.xml);
      if (text.trim()) sections.push(text);
    });
    return normalizeText(sections.join("\n"));
  }

  async function parseZipDocument(bytes, extension) {
    var entries = parseZipDirectory(bytes);

    if (extension === ".docx") {
      var docx = await selectedXml(bytes, entries, function (name) {
        return /^word\/(?:document|header\d+|footer\d+)\.xml$/i.test(name);
      });
      if (!docx.some(function (file) { return /^word\/document\.xml$/i.test(file.name); })) {
        fail("document_structure_missing");
      }
      return docxText(docx);
    }

    if (extension === ".pptx") {
      return pptxText(await selectedXml(bytes, entries, function (name) {
        return /^ppt\/slides\/slide\d+\.xml$/i.test(name);
      }));
    }

    if (extension === ".xlsx") {
      var sharedEntry = entries.find(function (entry) {
        return /^xl\/sharedStrings\.xml$/i.test(entry.name);
      });
      var shared = [];
      if (sharedEntry) {
        shared = sharedStrings(decodeUtf8(await entryBytes(bytes, sharedEntry)));
      }
      var sheets = await selectedXml(bytes, entries, function (name) {
        return /^xl\/worksheets\/sheet\d+\.xml$/i.test(name);
      });
      var rows = sheets.map(function (file) {
        return xlsxSheetText(file.xml, shared);
      }).filter(Boolean);
      return normalizeText(rows.join("\n"));
    }

    if (extension === ".hwpx") {
      return hwpxText(await selectedXml(bytes, entries, function (name) {
        return /^Contents\/section\d+\.xml$/i.test(name);
      }));
    }

    fail("browser_parser_unsupported_format");
  }

  async function parseArrayBuffer(buffer, meta) {
    try {
      var bytes = checkedBytes(buffer);
      var extension = meta && meta.extension
        ? String(meta.extension).toLowerCase()
        : extensionOf(meta && meta.name);

      if ([".pdf", ".docx", ".pptx", ".xlsx", ".hwpx"].indexOf(extension) < 0) {
        fail("browser_parser_unsupported_format");
      }

      if (extension === ".pdf") {
        if (
          bytes.length < 5 ||
          bytes[0] !== 0x25 || bytes[1] !== 0x50 ||
          bytes[2] !== 0x44 || bytes[3] !== 0x46 ||
          bytes[4] !== 0x2d
        ) fail("pdf_magic_mismatch");
        return {
          ok: false,
          code: "pdf_browser_parser_dependency_missing",
          residual: true
        };
      }

      var text = await parseZipDocument(bytes, extension);
      return {
        ok: true,
        kind: "local_text",
        text: text,
        textChars: text.length,
        byteSize: bytes.byteLength,
        parser: "b66-browser-zip-xml-v1"
      };
    } catch (error) {
      return {
        ok: false,
        code: error && typeof error.code === "string"
          ? error.code
          : "browser_document_parse_failed"
      };
    }
  }

  function parseDocumentFile(file, meta, options) {
    options = options || {};
    if (!file || typeof file.arrayBuffer !== "function") {
      return Promise.resolve({ ok: false, code: "file_read_unavailable" });
    }
    if (!meta || meta.category !== "native_document") {
      return Promise.resolve({ ok: false, code: "manual_only" });
    }

    var WorkerCtor = options.WorkerCtor ||
      (typeof Worker === "function" ? Worker : null);
    var timeoutMs = Number(options.timeoutMs || DEFAULT_TIMEOUT_MS);
    if (
      !WorkerCtor ||
      !Number.isFinite(timeoutMs) ||
      timeoutMs <= 0 ||
      timeoutMs > 10000
    ) {
      return Promise.resolve({ ok: false, code: "browser_worker_unavailable" });
    }

    return file.arrayBuffer().then(function (buffer) {
      if (!(buffer instanceof ArrayBuffer) || buffer.byteLength !== meta.byteSize) {
        return { ok: false, code: "file_size_changed" };
      }

      return new Promise(function (resolve) {
        var worker = null;
        var settled = false;
        var timer = null;

        function finish(result) {
          if (settled) return;
          settled = true;
          if (timer) clearTimeout(timer);
          if (worker && typeof worker.terminate === "function") {
            try { worker.terminate(); } catch (_) {}
          }
          resolve(result);
        }

        try {
          worker = new WorkerCtor(options.workerUrl || WORKER_URL);
        } catch (_) {
          finish({ ok: false, code: "browser_worker_unavailable" });
          return;
        }

        worker.onmessage = function (event) {
          var result = event && event.data;
          if (!result || typeof result !== "object") {
            finish({ ok: false, code: "browser_worker_invalid_response" });
            return;
          }
          finish(result);
        };
        worker.onerror = function () {
          finish({ ok: false, code: "browser_document_parse_failed" });
        };

        timer = setTimeout(function () {
          finish({ ok: false, code: "browser_parser_timeout" });
        }, timeoutMs);

        try {
          worker.postMessage({
            type: "parse",
            meta: {
              name: meta.name,
              extension: meta.extension,
              mediaType: meta.mediaType,
              byteSize: meta.byteSize
            },
            buffer: buffer
          }, [buffer]);
        } catch (_) {
          finish({ ok: false, code: "browser_worker_post_failed" });
        }
      });
    }).catch(function () {
      return { ok: false, code: "file_read_unavailable" };
    });
  }

  return {
    MAX_INPUT_BYTES: MAX_INPUT_BYTES,
    MAX_ZIP_ENTRIES: MAX_ZIP_ENTRIES,
    MAX_TOTAL_UNCOMPRESSED_BYTES: MAX_TOTAL_UNCOMPRESSED_BYTES,
    MAX_ENTRY_BYTES: MAX_ENTRY_BYTES,
    MAX_EXPANSION_RATIO: MAX_EXPANSION_RATIO,
    MAX_TEXT_CHARS: MAX_TEXT_CHARS,
    DEFAULT_TIMEOUT_MS: DEFAULT_TIMEOUT_MS,
    WORKER_URL: WORKER_URL,
    extensionOf: extensionOf,
    parseArrayBuffer: parseArrayBuffer,
    parseDocumentFile: parseDocumentFile
  };
});
