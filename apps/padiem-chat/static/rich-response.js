(() => {
  "use strict";

  const messageList = document.getElementById("messageList");
  const messageInput = document.getElementById("messageInput");
  if (!messageList || !messageInput) return;

  const HEADING_PATTERN = /^(#{1,4})\s+(.+)$/;
  const UNORDERED_PATTERN = /^\s*[-+*]\s+(.+)$/;
  const ORDERED_PATTERN = /^\s*\d+[.)]\s+(.+)$/;
  const QUOTE_PATTERN = /^\s*>\s?(.*)$/;
  const FENCE_PATTERN = /^\s*```([A-Za-z0-9_+.#-]*)\s*$/;
  const FENCE_CLOSE_PATTERN = /^\s*```\s*$/;
  const TABLE_SEPARATOR_CELL = /^:?-{3,}:?$/;

  function copyText(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      return navigator.clipboard.writeText(text).then(() => true).catch(() => fallbackCopy(text));
    }
    return Promise.resolve(fallbackCopy(text));
  }

  function fallbackCopy(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    let copied = false;
    try {
      copied = typeof document.execCommand === "function" && document.execCommand("copy") === true;
    } catch (_) {
      copied = false;
    }
    textarea.remove();
    return copied;
  }

  function temporaryLabel(button, label, original) {
    button.textContent = label;
    window.setTimeout(() => {
      if (button.isConnected) button.textContent = original;
    }, 1200);
  }

  function safeTableFilename(index) {
    return `padiem-table-${String(index + 1).padStart(2, "0")}.csv`;
  }

  function csvCell(value) {
    return `"${String(value).replace(/"/g, '""')}"`;
  }

  function downloadCsv(rows, index) {
    const csv = rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
    const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = safeTableFilename(index);
    anchor.hidden = true;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function splitTableRow(line) {
    let value = String(line || "").trim();
    if (!value.includes("|")) return null;
    if (value.startsWith("|")) value = value.slice(1);
    if (value.endsWith("|")) value = value.slice(0, -1);
    const cells = value.split("|").map((cell) => cell.trim());
    return cells.length >= 2 ? cells : null;
  }

  function tableAt(lines, index) {
    if (index + 1 >= lines.length) return null;
    const header = splitTableRow(lines[index]);
    const separator = splitTableRow(lines[index + 1]);
    if (!header || !separator || header.length !== separator.length) return null;
    if (!separator.every((cell) => TABLE_SEPARATOR_CELL.test(cell))) return null;

    const rows = [];
    let cursor = index + 2;
    while (cursor < lines.length) {
      if (!lines[cursor].trim()) break;
      const row = splitTableRow(lines[cursor]);
      if (!row || row.length !== header.length) break;
      rows.push(row);
      cursor += 1;
    }
    return { header, rows, nextIndex: cursor };
  }

  function isBlockStart(lines, index) {
    const line = lines[index] || "";
    if (!line.trim()) return true;
    if (FENCE_PATTERN.test(line)) return true;
    if (HEADING_PATTERN.test(line)) return true;
    if (UNORDERED_PATTERN.test(line)) return true;
    if (ORDERED_PATTERN.test(line)) return true;
    if (QUOTE_PATTERN.test(line)) return true;
    return tableAt(lines, index) !== null;
  }

  function appendHeading(container, match) {
    const sourceLevel = match[1].length;
    const heading = document.createElement(`h${Math.min(sourceLevel + 2, 6)}`);
    heading.className = "rich-response-heading";
    heading.textContent = match[2].trim();
    container.appendChild(heading);
  }

  function appendList(container, lines, startIndex, ordered) {
    const list = document.createElement(ordered ? "ol" : "ul");
    list.className = "rich-response-list";
    const pattern = ordered ? ORDERED_PATTERN : UNORDERED_PATTERN;
    let cursor = startIndex;
    while (cursor < lines.length) {
      const match = lines[cursor].match(pattern);
      if (!match) break;
      const item = document.createElement("li");
      item.textContent = match[1].trim();
      list.appendChild(item);
      cursor += 1;
    }
    container.appendChild(list);
    return cursor;
  }

  function appendQuote(container, lines, startIndex) {
    const quote = document.createElement("blockquote");
    quote.className = "rich-response-quote";
    const parts = [];
    let cursor = startIndex;
    while (cursor < lines.length) {
      const match = lines[cursor].match(QUOTE_PATTERN);
      if (!match) break;
      parts.push(match[1]);
      cursor += 1;
    }
    quote.textContent = parts.join("\n").trim();
    container.appendChild(quote);
    return cursor;
  }

  function appendCode(container, lines, startIndex, opener) {
    const language = opener[1] || "";
    const codeLines = [];
    let cursor = startIndex + 1;
    while (cursor < lines.length && !FENCE_CLOSE_PATTERN.test(lines[cursor])) {
      codeLines.push(lines[cursor]);
      cursor += 1;
    }
    if (cursor < lines.length && FENCE_CLOSE_PATTERN.test(lines[cursor])) cursor += 1;

    const section = document.createElement("section");
    section.className = "rich-code-block";
    const header = document.createElement("div");
    header.className = "rich-code-header";
    const label = document.createElement("span");
    label.textContent = language ? language.toUpperCase() : "코드";
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "rich-code-copy";
    copy.textContent = "복사";
    const codeText = codeLines.join("\n");
    copy.addEventListener("click", async () => {
      const copied = await copyText(codeText);
      temporaryLabel(copy, copied ? "복사됨" : "복사 실패", "복사");
    });
    header.append(label, copy);

    const pre = document.createElement("pre");
    const code = document.createElement("code");
    if (language) code.dataset.language = language.toLowerCase();
    code.textContent = codeText;
    pre.appendChild(code);
    section.append(header, pre);
    container.appendChild(section);
    return cursor;
  }

  function appendTable(container, tableData, tableIndex) {
    const section = document.createElement("section");
    section.className = "rich-table-block";

    const actions = document.createElement("div");
    actions.className = "rich-table-actions";
    const label = document.createElement("span");
    label.textContent = "표";
    const download = document.createElement("button");
    download.type = "button";
    download.className = "rich-table-download";
    download.textContent = "CSV 다운로드";
    const allRows = [tableData.header, ...tableData.rows];
    download.addEventListener("click", () => downloadCsv(allRows, tableIndex));
    actions.append(label, download);

    const scroller = document.createElement("div");
    scroller.className = "rich-table-scroll";
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    tableData.header.forEach((value) => {
      const th = document.createElement("th");
      th.scope = "col";
      th.textContent = value;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    if (tableData.rows.length) {
      const tbody = document.createElement("tbody");
      tableData.rows.forEach((row) => {
        const tr = document.createElement("tr");
        row.forEach((value) => {
          const td = document.createElement("td");
          td.textContent = value;
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
    }
    scroller.appendChild(table);
    section.append(actions, scroller);
    container.appendChild(section);
  }

  function appendParagraph(container, lines, startIndex) {
    const parts = [];
    let cursor = startIndex;
    while (cursor < lines.length) {
      if (cursor !== startIndex && isBlockStart(lines, cursor)) break;
      if (!lines[cursor].trim()) break;
      parts.push(lines[cursor]);
      cursor += 1;
    }
    const paragraph = document.createElement("p");
    paragraph.className = "rich-response-paragraph";
    paragraph.textContent = parts.join("\n").trim();
    container.appendChild(paragraph);
    return cursor;
  }

  function buildRichResponse(rawText) {
    const raw = String(rawText || "").replace(/\r\n?/g, "\n");
    const lines = raw.split("\n");
    const container = document.createElement("div");
    container.className = "rich-response";
    let index = 0;
    let tableIndex = 0;

    while (index < lines.length) {
      if (!lines[index].trim()) {
        index += 1;
        continue;
      }

      const fence = lines[index].match(FENCE_PATTERN);
      if (fence) {
        index = appendCode(container, lines, index, fence);
        continue;
      }

      const tableData = tableAt(lines, index);
      if (tableData) {
        appendTable(container, tableData, tableIndex);
        tableIndex += 1;
        index = tableData.nextIndex;
        continue;
      }

      const heading = lines[index].match(HEADING_PATTERN);
      if (heading) {
        appendHeading(container, heading);
        index += 1;
        continue;
      }

      if (UNORDERED_PATTERN.test(lines[index])) {
        index = appendList(container, lines, index, false);
        continue;
      }

      if (ORDERED_PATTERN.test(lines[index])) {
        index = appendList(container, lines, index, true);
        continue;
      }

      if (QUOTE_PATTERN.test(lines[index])) {
        index = appendQuote(container, lines, index);
        continue;
      }

      index = appendParagraph(container, lines, index);
    }

    return container;
  }

  function canEnhanceAnswers() {
    return messageInput.disabled !== true;
  }

  function enhanceAssistantMessage(article) {
    if (!canEnhanceAnswers()) return;
    if (!(article instanceof Element) || article.dataset.richResponse === "true") return;
    const content = article.querySelector(".assistant-content");
    if (!content || content.querySelector(".typing") || content.querySelector(".error-box")) return;
    const rawParagraph = Array.from(content.children).find((node) => node.tagName === "P");
    if (!rawParagraph || typeof rawParagraph.textContent !== "string" || !rawParagraph.textContent.trim()) return;

    try {
      const rich = buildRichResponse(rawParagraph.textContent);
      if (!rich.childElementCount) return;
      rawParagraph.insertAdjacentElement("afterend", rich);
      rawParagraph.classList.add("rich-response-source");
      rawParagraph.hidden = true;
      article.dataset.richResponse = "true";
    } catch (_) {
      // Keep the original plain-text paragraph visible if rich rendering fails.
    }
  }

  function enhanceAllAnswers() {
    if (!canEnhanceAnswers()) return;
    messageList.querySelectorAll(".assistant-message").forEach(enhanceAssistantMessage);
  }

  const messageObserver = new MutationObserver(enhanceAllAnswers);
  messageObserver.observe(messageList, { childList: true, subtree: true });

  const lifecycleObserver = new MutationObserver(() => {
    if (canEnhanceAnswers()) enhanceAllAnswers();
  });
  lifecycleObserver.observe(messageInput, { attributes: true, attributeFilter: ["disabled"] });

  enhanceAllAnswers();
})();
