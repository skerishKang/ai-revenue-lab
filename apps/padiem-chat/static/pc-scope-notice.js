(function (root) {
  "use strict";

  // #5573: the admitted PC scope is a one-line notice above the result. It is
  // its own element with its own role, so it is never read or copied as part
  // of the answer text.
  function render(content, notice) {
    if (!content || typeof content.insertBefore !== "function") return null;
    if (typeof notice !== "string" || !notice) return null;
    var line = root.document.createElement("p");
    line.className = "pc-scope-notice";
    line.setAttribute("role", "note");
    line.textContent = notice;
    // Always the first child: the notice describes the scope of the result
    // below it, whether the answer is already drawn (live stream completion)
    // or the container was just cleared (JSON answer, recovered result).
    content.insertBefore(line, content.firstChild || null);
    return line;
  }

  function value(result) {
    if (!result || typeof result !== "object") return null;
    var notice = result.scope_notice;
    return typeof notice === "string" && notice ? notice : null;
  }

  root.PadiemChatPcScopeNotice = Object.freeze({ render: render, value: value });
})(typeof window !== "undefined" ? window : globalThis);
