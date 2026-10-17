/* #4139 desktop lane: render a captured COM1 screen inside the conversation.
 *
 * Assistant messages are plain text, so a screenshot arrives as a
 * server-shaped marker line plus an owner-scoped retrieval reference:
 *
 *   화면 캡처 원문: GET /api/claw/connector/mesh-results/dsp_<32hex>
 *
 * This script upgrades exactly that line into an <img> fetched same-origin
 * with the owner's session. Only this relative path shape is ever fetched —
 * no browser-chosen URL can become an image — and the bytes must arrive as
 * image/jpeg, start with the JPEG magic, stay inside the existing 6 MB wire
 * envelope, and match the SHA-256 the message itself carries. Anything else
 * keeps the text reference, which stays usable on its own.
 *
 * No new focusable controls and no locale chrome copy: the image carries an
 * alt text only, so keyboard access and the surrounding UI are untouched.
 */
(function () {
  "use strict";

  var MARKER_RE = /화면 캡처 원문:\s*GET\s*(\/api\/claw\/connector\/mesh-results\/dsp_[0-9a-f]{32})/;
  var SHA_RE = /SHA-256:\s*([0-9a-f]{64})/;
  var MAX_BYTES = 6000001;
  var JPEG_MAGIC = [0xff, 0xd8, 0xff];

  function altText(doc) {
    var lang = (doc.documentElement.lang || "ko").toLowerCase();
    return lang.indexOf("en") === 0 ? "COM1 screen capture" : "COM1 화면 캡처";
  }

  function findMarker(paragraph) {
    if (!paragraph || paragraph.dataset.meshCaptureUpgraded) return null;
    var text = paragraph.textContent || "";
    var marker = MARKER_RE.exec(text);
    if (!marker) return null;
    var sha = SHA_RE.exec(text);
    return { path: marker[1], sha: sha ? sha[1] : null, paragraph: paragraph };
  }

  function isJpeg(bytes) {
    if (bytes.length < 16) return false;
    for (var i = 0; i < JPEG_MAGIC.length; i += 1) {
      if (bytes[i] !== JPEG_MAGIC[i]) return false;
    }
    return true;
  }

  async function upgrade(found, doc, fetcher) {
    var paragraph = found.paragraph;
    paragraph.dataset.meshCaptureUpgraded = "pending";
    var controller = new AbortController();
    try {
      var response = await fetcher(found.path, {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "image/jpeg" },
        signal: controller.signal,
      });
      if (!response || response.status !== 200) throw new Error("FETCH_FAILED");
      var contentType = String(
        (response.headers && response.headers.get("content-type")) || ""
      ).split(";")[0].trim().toLowerCase();
      if (contentType !== "image/jpeg") throw new Error("WRONG_TYPE");
      var lengthHeader = response.headers.get("content-length");
      if (lengthHeader != null && Number(lengthHeader) > MAX_BYTES) {
        throw new Error("TOO_LARGE");
      }
      var buffer = new Uint8Array(await response.arrayBuffer());
      if (buffer.length === 0 || buffer.length > MAX_BYTES) throw new Error("TOO_LARGE");
      if (!isJpeg(buffer)) throw new Error("NOT_JPEG");
      if (found.sha) {
        var digest = await crypto.subtle.digest("SHA-256", buffer);
        var hex = Array.prototype.map.call(new Uint8Array(digest), function (b) {
          return b.toString(16).padStart(2, "0");
        }).join("");
        if (hex !== found.sha) throw new Error("SHA_MISMATCH");
      }
      var headerSha = response.headers.get("x-oracle-mesh-content-sha256");
      if (found.sha && headerSha && headerSha.toLowerCase() !== found.sha) {
        throw new Error("SHA_MISMATCH");
      }
      var url = URL.createObjectURL(new Blob([buffer], { type: "image/jpeg" }));
      var img = doc.createElement("img");
      img.src = url;
      img.alt = altText(doc);
      img.className = "mesh-capture-image";
      img.style.maxWidth = "100%";
      img.style.height = "auto";
      img.setAttribute("referrerpolicy", "no-referrer");
      paragraph.after(img);
      paragraph.dataset.meshCaptureUpgraded = "done";
    } catch (err) {
      delete paragraph.dataset.meshCaptureUpgraded;
    }
  }

  function scan(root, doc, fetcher) {
    if (!root || !root.querySelectorAll) return;
    var paragraphs = root.querySelectorAll(".assistant-content p");
    for (var i = 0; i < paragraphs.length; i += 1) {
      var found = findMarker(paragraphs[i]);
      if (found) upgrade(found, doc, fetcher);
    }
  }

  function init(doc, fetcher) {
    fetcher = fetcher || fetch;
    var list = doc.getElementById("messageList");
    scan(doc, doc, fetcher);
    if (list && "MutationObserver" in window) {
      var observer = new MutationObserver(function (mutations) {
        for (var i = 0; i < mutations.length; i += 1) {
          var mutation = mutations[i];
          for (var j = 0; j < mutation.addedNodes.length; j += 1) {
            var node = mutation.addedNodes[j];
            if (node.nodeType !== 1) continue;
            if (node.matches && node.matches(".assistant-content p")) {
              var found = findMarker(node);
              if (found) upgrade(found, doc, fetcher);
            } else {
              scan(node, doc, fetcher);
            }
          }
        }
      });
      observer.observe(list, { childList: true, subtree: true });
    }
  }

  var api = { init: init, scan: scan };
  if (typeof window !== "undefined") {
    window.PadiemClawMeshCapture = api;
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { init(document); });
    } else {
      init(document);
    }
  }
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
