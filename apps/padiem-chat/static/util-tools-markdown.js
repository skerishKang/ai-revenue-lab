/*
 * #7173 PR2 follow-up · Util result formatting.
 *
 * The answer the tools receive carries light markdown. The screen shows it as
 * formatting (headings, lists, bold — nothing else), and the copy button hands
 * over plain text: heading markers gone, bullets as "• ", bold markers gone,
 * hashtags and line breaks intact.
 *
 * Safety boundary: every node is built with createElement/createTextNode and
 * textContent — this file never assembles HTML, so the repo's DOM-sink audit
 * keeps its zero. Rules mirror the shipped Chat renderer (rich-response.js):
 * "#{1,4} " headings, "-*•" bullets, "1. " ordered items, **bold**.
 */
(() => {
  "use strict";

  const HEADING = /^(#{1,4})\s+(.+)$/;
  const BULLET = /^\s*[-*•]\s+(.+)$/;
  const ORDERED = /^\s*\d+[.)]\s+(.+)$/;
  const BOLD = /\*\*([^*]+)\*\*/;

  function appendInline(host, value) {
    let rest = String(value == null ? "" : value);
    let match = BOLD.exec(rest);
    while (match) {
      if (match.index > 0) host.appendChild(document.createTextNode(rest.slice(0, match.index)));
      const strong = document.createElement("strong");
      strong.textContent = match[1];
      host.appendChild(strong);
      rest = rest.slice(match.index + match[0].length);
      match = BOLD.exec(rest);
    }
    if (rest) host.appendChild(document.createTextNode(rest));
  }

  function startsBlock(line) {
    return HEADING.test(line) || BULLET.test(line) || ORDERED.test(line);
  }

  function render(host, value) {
    if (!host || typeof host.replaceChildren !== "function") return host;
    host.replaceChildren();
    const lines = String(value == null ? "" : value).replace(/\r\n/g, "\n").split("\n");
    let index = 0;
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }
      const heading = HEADING.exec(line);
      if (heading) {
        const node = document.createElement(heading[1].length <= 2 ? "h5" : "h6");
        node.className = "util-md-heading";
        appendInline(node, heading[2].trim());
        host.appendChild(node);
        index += 1;
        continue;
      }
      if (BULLET.test(line)) {
        const list = document.createElement("ul");
        list.className = "util-md-list";
        while (index < lines.length && BULLET.test(lines[index])) {
          const item = document.createElement("li");
          appendInline(item, BULLET.exec(lines[index])[1].trim());
          list.appendChild(item);
          index += 1;
        }
        host.appendChild(list);
        continue;
      }
      if (ORDERED.test(line)) {
        const list = document.createElement("ol");
        list.className = "util-md-list";
        while (index < lines.length && ORDERED.test(lines[index])) {
          const item = document.createElement("li");
          appendInline(item, ORDERED.exec(lines[index])[1].trim());
          list.appendChild(item);
          index += 1;
        }
        host.appendChild(list);
        continue;
      }
      const paragraph = document.createElement("p");
      paragraph.className = "util-md-paragraph";
      const chunk = [];
      while (index < lines.length && lines[index].trim() && !startsBlock(lines[index])) {
        chunk.push(lines[index].trim());
        index += 1;
      }
      if (!chunk.length) {
        index += 1;
        continue;
      }
      appendInline(paragraph, chunk.join("\n"));
      host.appendChild(paragraph);
    }
    return host;
  }

  function stripInline(value) {
    return String(value == null ? "" : value)
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/`([^`]+)`/g, "$1");
  }

  function plain(value) {
    const lines = String(value == null ? "" : value).replace(/\r\n/g, "\n").split("\n");
    const out = [];
    lines.forEach((line) => {
      const heading = HEADING.exec(line);
      if (heading) {
        out.push(stripInline(heading[2]).trim());
        return;
      }
      const bullet = BULLET.exec(line);
      if (bullet) {
        out.push("• " + stripInline(bullet[1]).trim());
        return;
      }
      out.push(stripInline(line).replace(/[ \t]+$/, ""));
    });
    while (out.length && !out[out.length - 1].trim()) out.pop();
    return out.join("\n").replace(/\n{3,}/g, "\n\n");
  }

  window.PadiemUtilMarkdown = Object.freeze({ render: render, plain: plain });
})();
