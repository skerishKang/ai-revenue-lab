(() => {
  "use strict";

  const messageList = document.getElementById("messageList");
  const accountControls = document.querySelector(".account-controls");
  const loginButton = document.getElementById("loginButton");

  if (!messageList || !accountControls) return;

  const exportButton = document.createElement("button");
  exportButton.type = "button";
  exportButton.id = "conversationExportButton";
  exportButton.className = "login-button conversation-export-button";
  exportButton.textContent = "대화 내보내기";
  exportButton.setAttribute("aria-label", "현재 대화를 텍스트 파일로 내보내기");
  exportButton.hidden = true;
  exportButton.disabled = true;

  if (loginButton) accountControls.insertBefore(exportButton, loginButton);
  else accountControls.appendChild(exportButton);

  const SKIP_SELECTOR = [
    ".typing",
    ".error-box",
    ".answer-actions",
    ".assistant-meta",
    "[hidden]",
    "[aria-hidden='true']",
  ].join(",");

  const BLOCK_TAGS = new Set([
    "ADDRESS", "ARTICLE", "ASIDE", "BLOCKQUOTE", "DIV", "DL", "DT", "DD",
    "FIGCAPTION", "FIGURE", "FOOTER", "H1", "H2", "H3", "H4", "H5", "H6",
    "HEADER", "HR", "LI", "MAIN", "NAV", "OL", "P", "PRE", "SECTION", "TABLE",
    "TBODY", "TD", "TFOOT", "TH", "THEAD", "TR", "UL",
  ]);

  function appendBreak(parts) {
    if (!parts.length || parts[parts.length - 1] === "\n") return;
    parts.push("\n");
  }

  function collectNodeText(node, parts) {
    if (node.nodeType === Node.TEXT_NODE) {
      parts.push(node.nodeValue || "");
      return;
    }
    if (!(node instanceof Element)) return;
    if (node.matches(SKIP_SELECTOR)) return;
    if (node.tagName === "BR") {
      appendBreak(parts);
      return;
    }

    const isBlock = BLOCK_TAGS.has(node.tagName);
    if (isBlock) appendBreak(parts);
    if (node.tagName === "LI") parts.push("- ");
    node.childNodes.forEach((child) => collectNodeText(child, parts));
    if (isBlock) appendBreak(parts);
  }

  function visiblePlainText(root) {
    const parts = [];
    collectNodeText(root, parts);
    return parts
      .join("")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n[ \t]+/g, "\n")
      .replace(/[ \t]{2,}/g, " ")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function collectConversation() {
    const entries = [];
    messageList.querySelectorAll(".message").forEach((article) => {
      if (!(article instanceof Element)) return;
      if (article.classList.contains("user-message")) {
        const bubble = article.querySelector(".message-bubble");
        const text = bubble ? visiblePlainText(bubble) : "";
        if (text) entries.push({ label: "나", text });
        return;
      }
      if (article.classList.contains("assistant-message")) {
        const content = article.querySelector(".assistant-content");
        const text = content ? visiblePlainText(content) : "";
        if (text) entries.push({ label: "Padiem Chat", text });
      }
    });
    return entries;
  }

  function exportFilename() {
    const now = new Date();
    const year = String(now.getFullYear());
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `Padiem-Chat-대화-${year}-${month}-${day}.txt`;
  }

  function formatConversation(entries) {
    const body = entries.map((entry) => `${entry.label}:\n${entry.text}`).join("\n\n");
    return `Padiem Chat 대화\n\n${body}\n`;
  }

  function updateExportState() {
    const hasConversation = collectConversation().length > 0;
    exportButton.hidden = !hasConversation;
    exportButton.disabled = !hasConversation;
    exportButton.setAttribute("aria-disabled", hasConversation ? "false" : "true");
  }

  function downloadConversation() {
    const entries = collectConversation();
    if (!entries.length) return;
    const blob = new Blob([formatConversation(entries)], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = exportFilename();
    anchor.hidden = true;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  exportButton.addEventListener("click", downloadConversation);

  const observer = new MutationObserver(updateExportState);
  observer.observe(messageList, { childList: true, subtree: true, characterData: true });
  updateExportState();
})();
