/* #3782: show one owner-scoped browser capture beside the ordinary answer.
 * The existing lifecycle owns progress and its elapsed clock. This adapter
 * supplies only the server-bound Claw run id and a typed PNG display reference.
 * No local path, page URL, model HTML, action or approval control is accepted.
 */
(function () {
  "use strict";
  const MARKER = /\[pc-browser-capture:(dsp_[0-9a-f]{32})\]/;
  const PNG = [137, 80, 78, 71, 13, 10, 26, 10];
  const states = new WeakMap();
  const active = new Set();
  let suspended = false;

  function runIdForProgress(response, payload, clawRequest) {
    if (!clawRequest) return payload && payload.pc_run_id;
    const value = response && response.headers && response.headers.get("X-Padiem-Claw-Run-Id");
    return typeof value === "string" && /^run_[0-9a-f]{24}$/.test(value) ? value : null;
  }

  function dispose(state, removeImage) {
    state.controller.abort();
    if (state.url) URL.revokeObjectURL(state.url);
    if (removeImage && state.image) state.image.remove();
    active.delete(state);
    if (states.get(state.content) === state) states.delete(state.content);
  }

  function cleanDetached() {
    for (const state of active) {
      if (!state.content.isConnected || (state.image && !state.image.isConnected)) dispose(state, false);
    }
  }

  function removeMarker(content, marker, doc) {
    const walker = doc.createTreeWalker(content, 4); // SHOW_TEXT, no HTML parsing.
    let node;
    while ((node = walker.nextNode())) {
      if (node.nodeValue.includes(marker)) node.nodeValue = node.nodeValue.replace(marker, "");
    }
  }

  async function capture(content, doc, fetcher) {
    if (!content || states.has(content)) return;
    const found = MARKER.exec(content.textContent || "");
    if (!found) return;
    const state = { content, marker: found[0], controller: new AbortController(), image: null, url: null };
    states.set(content, state);
    active.add(state);
    try {
      const response = await fetcher("/api/claw/connector/browser-captures/" + found[1], {
        method: "GET", credentials: "same-origin", cache: "no-store",
        headers: { Accept: "image/png" }, signal: state.controller.signal,
      });
      if (!response || response.status !== 200) throw new Error("capture_unavailable");
      const type = (response.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
      const expected = response.headers.get("x-padiem-browser-capture-sha256") || "";
      if (type !== "image/png" || !/^[0-9a-f]{64}$/.test(expected)) throw new Error("capture_invalid");
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.length < 33 || PNG.some((value, index) => bytes[index] !== value)
          || bytes[12] !== 73 || bytes[13] !== 72 || bytes[14] !== 68 || bytes[15] !== 82) {
        throw new Error("capture_invalid");
      }
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      const actual = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("");
      if (actual !== expected || state.controller.signal.aborted || !content.isConnected
          || !content.textContent.includes(state.marker)) throw new Error("capture_invalid");
      state.url = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
      const image = doc.createElement("img");
      image.src = state.url;
      image.alt = (doc.documentElement.lang || "ko").startsWith("en")
        ? "PC browser screen capture" : "PC 브라우저 화면 캡처";
      image.className = "pc-browser-capture-image";
      image.style.maxWidth = "100%";
      image.style.height = "auto";
      image.setAttribute("referrerpolicy", "no-referrer");
      state.image = image;
      removeMarker(content, state.marker, doc);
      content.appendChild(image);
    } catch (_) {
      // Keep the textual reference. A display failure neither changes the
      // completed tool result nor turns the answer into an error screen.
      if (state.url) URL.revokeObjectURL(state.url);
      state.url = null;
      if (!content.isConnected || state.controller.signal.aborted) dispose(state, false);
    }
  }

  function scan(root, doc, fetcher) {
    cleanDetached();
    if (suspended || !root || !root.querySelectorAll) return;
    const contents = root.matches && root.matches(".assistant-content")
      ? [root] : root.querySelectorAll(".assistant-content");
    for (const content of contents) void capture(content, doc, fetcher);
  }

  function clear() {
    for (const state of Array.from(active)) dispose(state, true);
  }

  function init(doc, fetcher) {
    const list = doc.getElementById("messageList");
    if (!list) return;
    fetcher = fetcher || window.fetch.bind(window);
    scan(list, doc, fetcher);
    const observer = new MutationObserver(() => scan(list, doc, fetcher));
    observer.observe(list, { childList: true, subtree: true, characterData: true });
    window.addEventListener("pagehide", clear);
    window.addEventListener("padiem:account-changed", () => { suspended = true; clear(); });
    for (const name of ["padiem:auth-state", "padiem:auth-changed"]) {
      window.addEventListener(name, event => {
        if (event.detail && event.detail.authenticated === false) {
          suspended = true;
          clear();
        } else if (event.detail && event.detail.authenticated === true) {
          suspended = false;
          scan(list, doc, fetcher);
        }
      });
    }
    return () => { observer.disconnect(); clear(); };
  }

  const api = Object.freeze({ runIdForProgress, scan, init });
  if (typeof window !== "undefined") {
    window.PadiemPcBrowserSurface = api;
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => init(document));
    else init(document);
  }
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
