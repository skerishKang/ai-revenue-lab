/* B67 browser PDF page parser session (#3329).
 *
 * Product-facing code owns the browser Worker lifecycle and resource bounds.
 * PDF.js is loaded inside the dedicated module Worker from a locally packaged,
 * pinned asset. Raw PDF bytes are transferred only after the Worker reports
 * ready, and the Worker is terminated after success, failure, timeout or
 * cancellation.
 */
(function (global) {
  "use strict";

  var PINNED_PDFJS_VERSION = "6.3.289";
  var SCRIPT_URL = global.document && global.document.currentScript
    ? global.document.currentScript.src
    : null;
  var DEFAULT_WORKER_URL = SCRIPT_URL
    ? new URL("pdf-page-parser-worker.mjs", SCRIPT_URL).href
    : "./pdf-page-parser-worker.mjs";

  var LIMITS = Object.freeze({
    maxBytes: 16 * 1024 * 1024,
    maxPages: 512,
    maxPageChars: 40000,
    maxTotalChars: 2000000,
    readyTimeoutMs: 5000,
    parseTimeoutMs: 10000
  });

  function resultError(code) {
    return { ok: false, code: code };
  }

  function asArrayBuffer(value) {
    if (value instanceof ArrayBuffer) return value;
    if (ArrayBuffer.isView(value)) {
      return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength);
    }
    throw new TypeError("PDF parser input must be an ArrayBuffer or typed array");
  }

  function boundedTimeout(value, fallback, maximum) {
    if (value === undefined || value === null) return fallback;
    if (!Number.isInteger(value) || value < 1 || value > maximum) {
      throw new TypeError("PDF parser timeout is outside the reviewed bound");
    }
    return value;
  }

  function validateWorkerResult(payload) {
    if (!payload || typeof payload !== "object" || typeof payload.ok !== "boolean") {
      return resultError("pdf_worker_invalid_result");
    }
    if (payload.ok === false) {
      return typeof payload.code === "string"
        ? payload
        : resultError("pdf_worker_invalid_result");
    }
    if (payload.parser !== "pdfjs-dist" || payload.parser_version !== PINNED_PDFJS_VERSION) {
      return resultError("pdf_parser_version_mismatch");
    }
    if (!Number.isInteger(payload.page_count) || payload.page_count < 1 || payload.page_count > LIMITS.maxPages) {
      return resultError("pdf_worker_invalid_result");
    }
    if (!Array.isArray(payload.pages) || payload.pages.length !== payload.page_count) {
      return resultError("pdf_worker_invalid_result");
    }

    var totalChars = 0;
    var missingTextPages = [];
    for (var index = 0; index < payload.pages.length; index += 1) {
      var page = payload.pages[index];
      if (!page || page.page_number !== index + 1 || typeof page.text !== "string") {
        return resultError("pdf_worker_invalid_result");
      }
      if (page.text.length > LIMITS.maxPageChars || page.text_chars !== page.text.length) {
        return resultError("pdf_worker_invalid_result");
      }
      totalChars += page.text.length;
      if (totalChars > LIMITS.maxTotalChars) {
        return resultError("pdf_worker_invalid_result");
      }
      if (page.native_text !== (page.text.length > 0)) {
        return resultError("pdf_worker_invalid_result");
      }
      if (!page.native_text) missingTextPages.push(page.page_number);
    }
    if (payload.total_text_chars !== totalChars) {
      return resultError("pdf_worker_invalid_result");
    }
    if (JSON.stringify(payload.ocr_candidate_pages || []) !== JSON.stringify(missingTextPages)) {
      return resultError("pdf_worker_invalid_result");
    }
    return payload;
  }

  function prepareParser(options) {
    var opts = options || {};
    var WorkerCtor = opts.WorkerCtor || global.Worker;
    if (typeof WorkerCtor !== "function") {
      return Promise.reject(new Error("Web Worker is unavailable"));
    }
    var workerUrl = opts.workerUrl || DEFAULT_WORKER_URL;
    var readyTimeoutMs = boundedTimeout(
      opts.readyTimeoutMs,
      LIMITS.readyTimeoutMs,
      LIMITS.readyTimeoutMs
    );
    var worker = new WorkerCtor(workerUrl, {
      type: "module",
      name: "b67-pdf-page-parser"
    });
    var terminated = false;
    var used = false;

    function terminate() {
      if (!terminated) {
        terminated = true;
        worker.terminate();
      }
    }

    return new Promise(function (resolve, reject) {
      var readyTimer = global.setTimeout(function () {
        terminate();
        reject(new Error("PDF parser Worker did not become ready"));
      }, readyTimeoutMs);

      worker.onerror = function () {
        global.clearTimeout(readyTimer);
        terminate();
        reject(new Error("PDF parser Worker failed during startup"));
      };

      worker.onmessage = function (event) {
        var data = event && event.data;
        if (!data || data.type !== "ready") return;
        global.clearTimeout(readyTimer);
        if (data.parser !== "pdfjs-dist" || data.parser_version !== PINNED_PDFJS_VERSION) {
          terminate();
          reject(new Error("PDF parser dependency version mismatch"));
          return;
        }

        resolve({
          parser: data.parser,
          parserVersion: data.parser_version,
          parseArrayBuffer: function (input, parseOptions) {
            if (used || terminated) {
              return Promise.resolve(resultError("pdf_parser_session_closed"));
            }
            used = true;
            var parseOpts = parseOptions || {};
            var buffer;
            var parseTimeoutMs;
            try {
              buffer = asArrayBuffer(input);
              parseTimeoutMs = boundedTimeout(
                parseOpts.timeoutMs,
                LIMITS.parseTimeoutMs,
                LIMITS.parseTimeoutMs
              );
            } catch (error) {
              terminate();
              throw error;
            }
            if (buffer.byteLength < 5) {
              terminate();
              return Promise.resolve(resultError("pdf_too_small"));
            }
            if (buffer.byteLength > LIMITS.maxBytes) {
              terminate();
              return Promise.resolve(resultError("pdf_too_large"));
            }
            var signal = parseOpts.signal || null;

            return new Promise(function (finish) {
              var settled = false;
              var parseTimer = null;

              function done(result) {
                if (settled) return;
                settled = true;
                if (parseTimer !== null) global.clearTimeout(parseTimer);
                if (signal && typeof signal.removeEventListener === "function") {
                  signal.removeEventListener("abort", onAbort);
                }
                terminate();
                finish(result);
              }

              function onAbort() {
                done(resultError("pdf_parse_cancelled"));
              }

              if (signal && signal.aborted) {
                done(resultError("pdf_parse_cancelled"));
                return;
              }
              if (signal && typeof signal.addEventListener === "function") {
                signal.addEventListener("abort", onAbort, { once: true });
              }

              parseTimer = global.setTimeout(function () {
                done(resultError("pdf_parser_timeout"));
              }, parseTimeoutMs);

              worker.onerror = function () {
                done(resultError("pdf_worker_failed"));
              };
              worker.onmessage = function (parseEvent) {
                var payload = parseEvent && parseEvent.data;
                if (!payload || payload.type !== "result") return;
                done(validateWorkerResult(payload.result));
              };

              worker.postMessage({
                type: "parse",
                buffer: buffer,
                limits: LIMITS
              }, [buffer]);
            });
          },
          parseFile: function (file, parseOptions) {
            if (used || terminated) {
              return Promise.resolve(resultError("pdf_parser_session_closed"));
            }
            if (!file || typeof file.arrayBuffer !== "function") {
              used = true;
              terminate();
              return Promise.resolve(resultError("pdf_file_required"));
            }
            if (!Number.isInteger(file.size) || file.size < 5) {
              used = true;
              terminate();
              return Promise.resolve(resultError("pdf_too_small"));
            }
            if (file.size > LIMITS.maxBytes) {
              used = true;
              terminate();
              return Promise.resolve(resultError("pdf_too_large"));
            }
            return file.arrayBuffer().then(function (buffer) {
              return this.parseArrayBuffer(buffer, parseOptions);
            }.bind(this), function () {
              used = true;
              terminate();
              return resultError("pdf_file_read_failed");
            });
          },
          close: function () {
            used = true;
            terminate();
          }
        });
      };
    });
  }

  function parseArrayBuffer(input, options) {
    var opts = options || {};
    return prepareParser(opts).then(function (session) {
      return session.parseArrayBuffer(input, opts);
    }).catch(function () {
      return resultError("pdf_worker_start_failed");
    });
  }

  global.B67PdfPageParser = Object.freeze({
    PINNED_PDFJS_VERSION: PINNED_PDFJS_VERSION,
    LIMITS: LIMITS,
    prepareParser: prepareParser,
    parseArrayBuffer: parseArrayBuffer
  });
})(window);
