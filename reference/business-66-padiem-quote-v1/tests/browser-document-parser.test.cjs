const assert = require("node:assert/strict");
const zlib = require("node:zlib");
const Parser = require("../browser-document-parser.js");

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function u16(value) {
  return Uint8Array.from([value & 255, (value >>> 8) & 255]);
}

function u32(value) {
  return Uint8Array.from([
    value & 255,
    (value >>> 8) & 255,
    (value >>> 16) & 255,
    (value >>> 24) & 255
  ]);
}

function concat(parts) {
  const total = parts.reduce((sum, part) => sum + part.byteLength, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.byteLength;
  }
  return out;
}

function storedZip(files) {
  const encoder = new TextEncoder();
  const locals = [];
  const centrals = [];
  let localOffset = 0;

  for (const file of files) {
    const name = encoder.encode(file.name);
    const data = encoder.encode(file.text);
    const method = file.deflate ? 8 : 0;
    const compressed = method === 8
      ? Uint8Array.from(zlib.deflateRawSync(data))
      : data;
    const crc = crc32(data);
    const local = concat([
      u32(0x04034b50),
      u16(20),
      u16(0),
      u16(method),
      u16(0),
      u16(0),
      u32(crc),
      u32(compressed.byteLength),
      u32(data.byteLength),
      u16(name.byteLength),
      u16(0),
      name,
      compressed
    ]);
    locals.push(local);

    const central = concat([
      u32(0x02014b50),
      u16(file.symlink ? 0x0314 : 20),
      u16(20),
      u16(0),
      u16(method),
      u16(0),
      u16(0),
      u32(crc),
      u32(compressed.byteLength),
      u32(data.byteLength),
      u16(name.byteLength),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(file.symlink ? 0xa1ff0000 : 0),
      u32(localOffset),
      name
    ]);
    centrals.push(central);
    localOffset += local.byteLength;
  }

  const localBytes = concat(locals);
  const centralBytes = concat(centrals);
  const eocd = concat([
    u32(0x06054b50),
    u16(0),
    u16(0),
    u16(files.length),
    u16(files.length),
    u32(centralBytes.byteLength),
    u32(localBytes.byteLength),
    u16(0)
  ]);
  return concat([localBytes, centralBytes, eocd]);
}

function bufferOf(bytes) {
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

async function parse(extension, files) {
  const zip = storedZip(files);
  return Parser.parseArrayBuffer(bufferOf(zip), {
    name: "quotation" + extension,
    extension
  });
}

async function main() {
  const docx = await parse(".docx", [
    {
      name: "word/document.xml",
      deflate: true,
      text: '<?xml version="1.0"?><w:document><w:p><w:r><w:t>견적번호 Q-100</w:t></w:r></w:p><w:p><w:r><w:t>품목 배관 12000</w:t></w:r></w:p></w:document>'
    }
  ]);
  assert.equal(docx.ok, true);
  assert.match(docx.text, /Q-100/);
  assert.match(docx.text, /12000/);

  const pptx = await parse(".pptx", [
    {
      name: "ppt/slides/slide1.xml",
      text: '<p:sld><a:t>테스트상사</a:t><a:t>공급가 30000</a:t></p:sld>'
    }
  ]);
  assert.equal(pptx.ok, true);
  assert.match(pptx.text, /테스트상사/);
  assert.match(pptx.text, /30000/);

  const xlsx = await parse(".xlsx", [
    {
      name: "xl/sharedStrings.xml",
      text: '<sst><si><t>품목</t></si><si><t>알루미늄</t></si></sst>'
    },
    {
      name: "xl/worksheets/sheet1.xml",
      text: '<worksheet><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1"><v>5500</v></c></row></sheetData></worksheet>'
    }
  ]);
  assert.equal(xlsx.ok, true);
  assert.match(xlsx.text, /품목/);
  assert.match(xlsx.text, /알루미늄/);
  assert.match(xlsx.text, /5500/);

  const hwpx = await parse(".hwpx", [
    {
      name: "Contents/section0.xml",
      text: '<hp:sec><hp:p><hp:run><hp:t>우리회사 견적서</hp:t></hp:run></hp:p><hp:t>합계 99000</hp:t></hp:sec>'
    }
  ]);
  assert.equal(hwpx.ok, true);
  assert.match(hwpx.text, /우리회사 견적서/);
  assert.match(hwpx.text, /99000/);

  const pdfBytes = new TextEncoder().encode("%PDF-1.7\nsynthetic");
  const pdf = await Parser.parseArrayBuffer(bufferOf(pdfBytes), {
    name: "quotation.pdf",
    extension: ".pdf"
  });
  assert.deepEqual(pdf, {
    ok: false,
    code: "pdf_browser_parser_dependency_missing",
    residual: true
  });

  const traversal = await parse(".docx", [
    { name: "../evil.xml", text: "<x>evil</x>" },
    { name: "word/document.xml", text: "<w:document><w:t>safe</w:t></w:document>" }
  ]);
  assert.equal(traversal.ok, false);
  assert.equal(traversal.code, "zip_path_traversal");

  const symlink = await parse(".docx", [
    { name: "word/document.xml", text: "<w:document><w:t>safe</w:t></w:document>" },
    { name: "word/link.xml", text: "target", symlink: true }
  ]);
  assert.equal(symlink.ok, false);
  assert.equal(symlink.code, "zip_symlink_rejected");

  let terminated = 0;
  class SilentWorker {
    constructor(url) {
      this.url = url;
      this.onmessage = null;
      this.onerror = null;
    }
    postMessage() {}
    terminate() { terminated += 1; }
  }

  const tiny = Uint8Array.from([1, 2, 3, 4]);
  const file = {
    arrayBuffer: async () => bufferOf(tiny)
  };
  const timedOut = await Parser.parseDocumentFile(
    file,
    {
      name: "q.docx",
      extension: ".docx",
      mediaType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      byteSize: tiny.byteLength,
      category: "native_document"
    },
    { WorkerCtor: SilentWorker, timeoutMs: 5 }
  );
  assert.deepEqual(timedOut, { ok: false, code: "browser_parser_timeout" });
  assert.equal(terminated, 1);

  let posted = null;
  let successTerminated = 0;
  class SuccessWorker {
    constructor() {
      this.onmessage = null;
      this.onerror = null;
    }
    postMessage(message) {
      posted = message;
      queueMicrotask(() => this.onmessage({
        data: {
          ok: true,
          kind: "local_text",
          text: "견적번호 Q-1",
          textChars: 8,
          byteSize: tiny.byteLength,
          parser: "test"
        }
      }));
    }
    terminate() { successTerminated += 1; }
  }

  const workerSuccess = await Parser.parseDocumentFile(
    file,
    {
      name: "q.docx",
      extension: ".docx",
      mediaType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      byteSize: tiny.byteLength,
      category: "native_document"
    },
    { WorkerCtor: SuccessWorker, timeoutMs: 100 }
  );
  assert.equal(workerSuccess.ok, true);
  assert.equal(posted.type, "parse");
  assert.equal(posted.meta.name, "q.docx");
  assert.equal(successTerminated, 1);

  console.log("B66_BROWSER_DOCUMENT_PARSER_POC=PASS");
  console.log("BROWSER_ZIP_XML_FORMATS=DOCX,PPTX,XLSX,HWPX");
  console.log("PDF_BROWSER_PATH=RESIDUAL_LOCAL_PDF_PARSER_REQUIRED");
  console.log("DEFLATE_RAW_EXTRACTION=PASS");
  console.log("ZIP_SYMLINK_REJECTED=YES");
  console.log("WORKER_TIMEOUT_TERMINATES=YES");
  console.log("PROVIDER_CALLS=0");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
