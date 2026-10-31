"""Build the sandboxed document that runs one generated UI.

The document assembly follows the pinned MIT upstream
``CopilotKit/OpenIntelligentUI`` release: the generated CSS goes into its own
style block, the generated function declarations go into one classic script at
the top level so they become window globals (the upstream reason is that inline
``onclick="fn()"`` handlers have to resolve them), and the generated
expressions are joined into one async IIFE. The closing-tag guards are the
upstream's.

Two things are PADIEM's own and are marked as such:

* the theme variables the generated CSS refers to;
* the **bridge** that reports the user's current control values to the app, so
  the next AI turn can see what the user changed.
"""

from __future__ import annotations

import re

from .contracts import GeneratedUi

#: The upstream's Websandbox stub. Upstream makes it a no-op so an exported
#: document degrades gracefully; here it forwards to the app, because the
#: upstream prompt tells the model to call it.
_WEBSANDBOX_BRIDGE = """window.Websandbox = { connection: { remote: {
  sendPrompt: async (payload) => {
    var text = payload && typeof payload === "object" ? (payload.text || "") : String(payload || "");
    window.parent.postMessage({ type: "prompt", text: String(text) }, "*");
  },
  openLink: async (payload) => {
    var url = payload && payload.url ? String(payload.url) : "";
    if (/^https:/.test(url)) window.open(url, "_blank", "noopener,noreferrer");
  }
} } };"""

#: The PADIEM bridge: it captures the generated UI's control values and
#: reports them to the app on every change, and it tells the app when the
#: document is ready.
_BRIDGE = """(function () {
  function collect() {
    var values = {};
    var nodes = document.querySelectorAll("input, select, textarea");
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var key = node.id || node.name || (node.getAttribute("aria-label") || "");
      if (!key) continue;
      values[key] = node.type === "checkbox" ? String(node.checked) : String(node.value == null ? "" : node.value);
    }
    return values;
  }
  function report() {
    try {
      window.parent.postMessage({ type: "ui_state", values: collect() }, "*");
    } catch (error) {
      /* the host frame is gone; nothing to report */
    }
  }
  window.sendPrompt = function (text) {
    window.parent.postMessage({ type: "prompt", text: String(text == null ? "" : text) }, "*");
  };
  document.addEventListener("input", report, true);
  document.addEventListener("change", report, true);
  document.addEventListener("click", report, true);
  window.addEventListener("load", function () {
    report();
    window.parent.postMessage({ type: "ui_ready" }, "*");
  });
  report();
})();"""

#: The theme variables the upstream prompt tells the model to use. Only the
#: tokens the upstream prompt names are defined here.
_THEME_CSS = """:root {
  --color-text-primary: #111827;
  --color-text-secondary: #4b5563;
  --color-background-primary: #ffffff;
  --color-background-secondary: #f3f4f6;
  --color-border-primary: #d1d5db;
  --color-accent-primary: #2563eb;
  --color-danger-primary: #dc2626;
  --color-success-primary: #059669;
  --radius-sm: 4px;
  --radius-md: 8px;
  --space-sm: 6px;
  --space-md: 12px;
  --space-lg: 20px;
  --font-sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
}
body {
  margin: 0;
  padding: 16px;
  font-family: var(--font-sans);
  color: var(--color-text-primary);
  background: var(--color-background-primary);
}
label { display: block; margin-bottom: 4px; font-size: 13px; color: var(--color-text-secondary); }
input, select, textarea {
  font: inherit;
  padding: 6px 8px;
  border: 1px solid var(--color-border-primary);
  border-radius: var(--radius-sm);
  background: var(--color-background-primary);
  color: var(--color-text-primary);
}
button {
  font: inherit;
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border-primary);
  background: var(--color-background-secondary);
  color: var(--color-text-primary);
  cursor: pointer;
}
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid var(--color-border-primary); padding: 6px 8px; text-align: left; }
h1, h2, h3 { margin: 0 0 8px; }
h1 { font-size: 20px; } h2 { font-size: 17px; } h3 { font-size: 15px; }
p { font-size: 14px; margin: 0 0 10px; }
.c-card { background: var(--color-background-secondary); border-radius: var(--radius-md); padding: 12px; }
.c-muted { color: var(--color-text-secondary); font-size: 13px; }"""

_SCRIPT_CLOSE = re.compile(r"</script", re.IGNORECASE)
_STYLE_CLOSE = re.compile(r"</style", re.IGNORECASE)
_HTML_ESCAPES = (
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ('"', "&quot;"),
)


def escape_html(text: str) -> str:
    """Escape one text value for an HTML attribute."""

    for needle, replacement in _HTML_ESCAPES:
        text = text.replace(needle, replacement)
    return text


def escape_script_close(js: str) -> str:
    """The upstream's guard against a generated script closing its own tag."""

    return _SCRIPT_CLOSE.sub("<\\/script", js)


def escape_style_close(css: str) -> str:
    """The upstream's guard against a generated style closing its own tag."""

    return _STYLE_CLOSE.sub("<\\/style", css)


def build_sandbox_document(ui: GeneratedUi) -> str:
    """Assemble the sandboxed document for one generated UI.

    The structure mirrors the upstream's
    ``assembleStandaloneHtmlFromActivity``: the generated CSS in its own style
    block, the generated function declarations in one classic script at the top
    level, and the generated expressions joined into one async IIFE.
    """

    expressions = "\n".join(escape_script_close(item) for item in ui.js_expressions)
    script_parts: list[str] = []
    if ui.js_functions:
        script_parts.append(escape_script_close(ui.js_functions))
    if expressions.strip():
        script_parts.append(f"(async () => {{\n{expressions}\n}})();")

    generated_script = ""
    if script_parts:
        generated_script = "<script>\n" + "\n".join(script_parts) + "\n</script>"

    generated_css = ""
    if ui.css:
        generated_css = f"\n  <style>{escape_style_close(ui.css)}</style>"

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape_html(ui.title or "PADIEM Designer")}</title>
  <style>
    {_THEME_CSS}
  </style>{generated_css}
  <script>{_WEBSANDBOX_BRIDGE}</script>
</head>
<body>
  {ui.html}
  {generated_script}
  <script>{_BRIDGE}</script>
</body>
</html>"""
