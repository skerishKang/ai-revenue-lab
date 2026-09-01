(() => {
  "use strict";

  const messageList = document.getElementById("messageList");
  const accountControls =
    document.querySelector(".account-controls") ||
    document.querySelector(".sidebar-account") ||
    document.querySelector(".sidebar-bottom");
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

  if (loginButton && accountControls.contains(loginButton)) {
    let ref = loginButton;
    while (ref.parentElement && ref.parentElement !== accountControls) {
      ref = ref.parentElement;
    }
    if (ref.parentElement === accountControls) {
      accountControls.insertBefore(exportButton, ref);
    } else {
      accountControls.appendChild(exportButton);
    }
  } else {
    accountControls.appendChild(exportButton);
  }

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

  const lifecycleApi = () => window.PadiemChatLifecycle || { isCompleted: () => false };

  function exportableAssistantText(article) {
    if (!(article instanceof Element)) return "";
    if (!lifecycleApi().isCompleted(article)) return "";
    const content = article.querySelector(".assistant-content");
    if (!content || content.querySelector(".typing") || content.querySelector(".error-box")) return "";
    return visiblePlainText(content);
  }

  function hasIncompleteAssistant() {
    return Array.from(messageList.querySelectorAll(".assistant-message")).some(
      (article) => !lifecycleApi().isCompleted(article)
    );
  }

  function hasSettledAssistant() {
    return Array.from(messageList.querySelectorAll(".assistant-message")).some(
      (article) => Boolean(exportableAssistantText(article))
    );
  }

  function collectConversation() {
    if (hasIncompleteAssistant()) return [];
    const entries = [];
    let pendingUser = null;
    messageList.querySelectorAll(".message").forEach((article) => {
      if (!(article instanceof Element)) return;
      if (article.classList.contains("user-message")) {
        const bubble = article.querySelector(".message-bubble");
        const text = bubble ? visiblePlainText(bubble) : "";
        pendingUser = text ? { label: "나", text } : null;
        return;
      }
      if (article.classList.contains("assistant-message")) {
        const text = exportableAssistantText(article);
        if (!text) {
          pendingUser = null;
          return;
        }
        if (pendingUser) {
          entries.push(pendingUser);
          pendingUser = null;
        }
        entries.push({ label: "Padiem Chat", text });
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
    const settled = hasSettledAssistant();
    const usable = settled && !hasIncompleteAssistant();
    exportButton.hidden = !settled;
    exportButton.disabled = !usable;
    exportButton.setAttribute("aria-disabled", usable ? "false" : "true");
  }

  function downloadConversation() {
    if (hasIncompleteAssistant() || exportButton.disabled) return;
    const entries = collectConversation();
    if (!entries.some((entry) => entry.label === "Padiem Chat")) return;
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
  messageList.addEventListener("padiem:message-lifecycle", updateExportState);
  updateExportState();

  function ensureSidebarOpenForExport() {
    const shellEl = document.querySelector(".app-shell");
    const mobile = window.matchMedia("(max-width: 920px)").matches;
    if (!mobile) return;
    if (shellEl && !shellEl.classList.contains("sidebar-open")) {
      shellEl.classList.add("sidebar-open");
      const menu = document.getElementById("mobileMenu");
      if (menu) menu.setAttribute("aria-expanded", "true");
      const scrim = document.getElementById("sidebarScrim");
      if (scrim) scrim.hidden = false;
    }
  }

  document.addEventListener("padiem:request-export", () => {
    ensureSidebarOpenForExport();
  });
})();
