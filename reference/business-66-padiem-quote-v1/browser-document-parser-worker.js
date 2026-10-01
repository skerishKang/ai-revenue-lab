/* Dedicated B66 document parser worker (#3293). */
"use strict";

importScripts("./browser-document-parser.js");

self.onmessage = async function (event) {
  var data = event && event.data;
  if (!data || data.type !== "parse" || !(data.buffer instanceof ArrayBuffer)) {
    self.postMessage({ ok: false, code: "browser_worker_invalid_request" });
    return;
  }

  var parser = self.B66BrowserDocumentParser;
  if (!parser || typeof parser.parseArrayBuffer !== "function") {
    self.postMessage({ ok: false, code: "browser_worker_parser_unavailable" });
    return;
  }

  var result;
  try {
    result = await parser.parseArrayBuffer(data.buffer, data.meta || {});
  } catch (_) {
    result = { ok: false, code: "browser_document_parse_failed" };
  }
  self.postMessage(result);
};
