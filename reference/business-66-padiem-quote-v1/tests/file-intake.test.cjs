const assert = require("node:assert");
const Intake = require("../file-intake.js");

function ok(name, type, size) {
  const result = Intake.classifyFile({ name, type, size });
  assert.equal(result.ok, true, JSON.stringify(result));
  return result.value;
}

function fail(name, type, size, code) {
  const result = Intake.classifyFile({ name, type, size });
  assert.equal(result.ok, false, JSON.stringify(result));
  assert.equal(result.error, code);
}

const pdf = ok("견적서.pdf", "application/pdf", 1024);
assert.equal(pdf.category, "native_document");
assert.equal(pdf.label, "PDF");
assert.equal(pdf.mediaType, "application/pdf");

const pdfNoMime = ok("견적서.PDF", "", 1024);
assert.equal(pdfNoMime.mediaType, "application/pdf", "empty browser MIME falls back to canonical media type");

const pdfOctet = ok("견적서.pdf", "application/octet-stream", 1024);
assert.equal(pdfOctet.mediaType, "application/pdf", "generic octet-stream falls back to canonical PDF media type");

const docxZip = ok("quote.docx", "application/zip", 1024);
assert.equal(
  docxZip.mediaType,
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "generic zip DOCX falls back to canonical Office media type"
);
const hwpxZip = ok("quote.hwpx", "application/x-zip-compressed", 1024);
assert.equal(hwpxZip.mediaType, "application/hwp+zip", "generic zip HWPX falls back to canonical media type");
const pngOctet = ok("quote.png", "application/octet-stream", 1024);
assert.equal(pngOctet.mediaType, "image/png", "generic octet-stream image falls back to canonical media type");

const docx = ok(
  "quote.docx",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  2048
);
assert.equal(docx.category, "native_document");

const pptx = ok(
  "quote.pptx",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  2048
);
assert.equal(pptx.category, "native_document");

const xlsx = ok(
  "quote.xlsx",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  2048
);
assert.equal(xlsx.category, "native_document");

const hwpx = ok("quote.hwpx", "application/hwp+zip", 2048);
assert.equal(hwpx.category, "native_document");

const jpg = ok("quote.jpg", "image/jpeg", 1024);
assert.equal(jpg.category, "image");
const jpeg = ok("quote.jpeg", "", 1024);
assert.equal(jpeg.mediaType, "image/jpeg");
const png = ok("quote.png", "image/png", 1024);
assert.equal(png.category, "image");
const webp = ok("quote.webp", "image/webp", 1024);
assert.equal(webp.category, "image");

fail("quote.hwp", "application/x-hwp", 100, "legacy_hwp_unsupported");
fail("quote.exe", "application/octet-stream", 100, "unsupported_file_type");
fail("quote.pdf", "image/png", 100, "media_extension_mismatch");
fail("quote.png", "image/jpeg", 100, "media_extension_mismatch");
fail("quote.pdf", "application/pdf", 0, "empty_file");
fail("quote.pdf", "application/pdf", Intake.MAX_DOCUMENT_BYTES + 1, "document_too_large");
fail("quote.png", "image/png", Intake.MAX_IMAGE_BYTES + 1, "image_too_large");
fail("", "application/pdf", 100, "invalid_file_name");
fail("bad\u0000.pdf", "application/pdf", 100, "invalid_file_name");

assert.equal(Intake.formatBytes(1023), "1023 B");
assert.equal(Intake.formatBytes(1024), "1.0 KB");
assert.equal(Intake.formatBytes(2 * 1024 * 1024), "2.0 MB");

const source = require("node:fs").readFileSync(require("node:path").join(__dirname, "..", "file-intake.js"), "utf8");
assert.equal(source.includes("fetch("), false, "file intake preflight must not upload");
assert.equal(source.includes("XMLHttpRequest"), false, "file intake preflight must not use XHR");
assert.equal(source.includes("localStorage"), false, "raw file preflight must not persist into localStorage");
assert.equal(source.includes("sessionStorage"), false, "raw file preflight must not persist into sessionStorage");

console.log("B66_FILE_INTAKE_CLIENT_CONTRACT=PASS");
console.log("FILE_CHOOSER_PREFLIGHT_TYPES=PASS");
console.log("EMPTY_MIME_FALLBACK=PASS");
console.log("OCTET_STREAM_FALLBACK=PASS");
console.log("ZIP_MIME_OFFICE_HWPX_FALLBACK=PASS");
console.log("SPECIFIC_MIME_MISMATCH_REJECTED=PASS");
console.log("LEGACY_HWP=UNSUPPORTED");
console.log("RAW_FILE_PERSISTENCE=0");
console.log("BROWSER_UPLOAD_NETWORK=0");
