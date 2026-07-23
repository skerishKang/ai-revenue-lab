// Living Travel — Staging safe DOM helpers.
//
// All rendering goes through textContent / createElement / appendChild. These
// helpers never assign innerHTML, outerHTML, or insertAdjacentHTML, so
// API-sourced content cannot inject markup. The staging contract test asserts
// that no staging script uses those unsafe sinks.

export function clear(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

// Toggle the "hidden" utility class (defined in staging.css). No inline styles.
export function setHidden(node, hidden) {
  node.classList.toggle("hidden", Boolean(hidden));
}

export function setText(node, text) {
  node.textContent = text == null ? "" : String(text);
  return node;
}

// Create an element. `attrs` sets attributes/properties safely; `children`
// appends text or element children. A string child becomes a text node.
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null) continue;
    if (key === "class") {
      node.className = value;
    } else if (key === "dataset") {
      for (const [dk, dv] of Object.entries(value)) {
        node.dataset[dk] = dv;
      }
    } else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else {
      node.setAttribute(key, String(value));
    }
  }
  for (const child of children) {
    if (child == null) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

export function badge(text, className = "badge") {
  return el("span", { class: className }, [text]);
}

// Render a labeled key/value row into a grid-like parent using safe text nodes.
export function keyValue(label, value) {
  return el("div", { class: "preference-item" }, [
    el("label", {}, [label]),
    el("span", { class: "value" }, [value == null || value === "" ? "—" : String(value)]),
  ]);
}

// Join a list value for display.
export function listText(items) {
  if (Array.isArray(items) && items.length > 0) {
    return items.join(" · ");
  }
  return "—";
}

// Render an edition's structured_content defensively using only safe DOM APIs.
// Recognised shapes (opening + sections[]) are laid out; anything else falls
// back to a readable JSON dump rendered as text (never parsed as HTML).
export function renderStructured(sc, container) {
  clear(container);
  if (!sc || typeof sc !== "object" || Object.keys(sc).length === 0) {
    container.appendChild(el("p", { class: "small" }, ["구조화된 콘텐츠가 없습니다."]));
    return;
  }
  if (typeof sc.opening === "string") {
    container.appendChild(el("p", { class: "edition-opening" }, [sc.opening]));
  }
  if (Array.isArray(sc.sections)) {
    sc.sections.forEach((section, index) => {
      const wrap = el("div", { class: "edition-section" });
      wrap.appendChild(
        el("div", { class: "edition-section-number" }, [
          String(section.section_number ?? index + 1),
        ])
      );
      if (section.title) {
        wrap.appendChild(el("h2", {}, [String(section.title)]));
      }
      if (section.body) {
        wrap.appendChild(el("div", { class: "edition-section-body" }, [String(section.body)]));
      }
      container.appendChild(wrap);
    });
    return;
  }
  const pre = el("pre", { class: "staging-json" });
  pre.textContent = JSON.stringify(sc, null, 2);
  container.appendChild(pre);
}
