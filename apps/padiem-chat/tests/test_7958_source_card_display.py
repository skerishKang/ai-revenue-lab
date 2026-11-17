"""#7958 — answer source display: readable date and theme-safe title colour."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def _run_node(script: str) -> str:
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True,
        encoding="utf-8", check=True,
    )
    return result.stdout.strip()


_SHIM = r'''
const fs = require("node:fs");
class El {
  constructor(tag){ this.tagName=String(tag).toUpperCase(); this.children=[]; this.className=""; this._text=""; this._attrs={}; }
  get textContent(){ return this.children.length ? this.children.map(c=>c.textContent).join("") : this._text; }
  set textContent(v){ this._text=String(v??""); this.children=[]; }
  appendChild(c){ this.children.push(c); return c; }
  append(...ns){ ns.forEach(n=>this.appendChild(n)); }
  remove(){}
  setAttribute(k,v){ this._attrs[k]=String(v); }
  matches(sel){
    const s = String(sel).trim();
    if (s.startsWith(".")) return String(this.className||"").split(/\s+/).includes(s.slice(1));
    return this.tagName === s.toUpperCase();
  }
  _walk(out){ for(const c of this.children){ out.push(c); if(c.children&&c.children.length)c._walk(out); } return out; }
  querySelector(sel){ return this._walk([]).find(n=>n.matches&&n.matches(sel))||null; }
  querySelectorAll(sel){ return this._walk([]).filter(n=>n.matches&&n.matches(sel)); }
}
global.Element=El;
'''


def _rendered_meta(lang: str) -> str:
    path = (STATIC / "claw-answer-sources.js").as_posix()
    script = _SHIM + f'''
global.document = {{
  createElement: (t) => new El(t),
  createTextNode: (v) => {{ const n = new El("#TEXT"); n._text = String(v); return n; }},
  documentElement: {{ lang: "{lang}" }},
  querySelector: () => null,
}};
global.window = {{ PadiemLocaleText: () => "출처" }};
const src = fs.readFileSync("{path}", "utf-8");
eval(src);
const article = new El("article");
const content = new El("div"); content.className = "assistant-content";
const p = new El("p"); p.textContent = "근거 [1]"; content.appendChild(p);
article.appendChild(content);
const evidence = [{{ url: "https://example.com/a", title: "제목", retrieved_at: "2026-11-18T09:00:00Z" }}];
global.window.PadiemClawAnswerSources.render(article, evidence);
const section = content.querySelector(".answer-sources");
const small = section && section.querySelector("small");
console.log(small ? small.textContent : "");
'''
    return _run_node(script)


def test_source_date_is_human_readable_in_both_locales():
    korean = _rendered_meta("ko")
    english = _rendered_meta("en")
    assert "2026-11-18T" not in korean and "2026-11-18T" not in english
    assert "11월 18일" in korean
    assert "Nov" in english and "18" in english


def test_source_title_uses_a_theme_common_token():
    rich = (STATIC / "padiem-rich.css").read_text(encoding="utf-8")
    search = (STATIC / "search-sources.css").read_text(encoding="utf-8")
    assert "color: var(--text);" in rich
    assert "color: var(--text);" in search
    assert "rgba(255, 255, 255, .52)" not in rich
    assert "rgba(31, 41, 55, 0.72)" not in search


def test_text_token_is_defined_in_every_theme():
    tokens = (STATIC / "padiem-tokens.css").read_text(encoding="utf-8")
    for theme in ("light", "dark", "padiem-glass", "cinematic", "padiem-home"):
        block = tokens.split(f'html[data-theme="{theme}"] {{', 1)[1].split("\n}", 1)[0]
        assert "--text:" in block, theme
