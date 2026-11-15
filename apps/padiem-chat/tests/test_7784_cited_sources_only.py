"""#7784 (part 2): the source list shows only evidence the answer cited.

``search-sources.js`` (Chat) and ``claw-answer-sources.js`` (Claw) render the
validated evidence. Neither may list a retrieval the answer never used: the
visible list is the cited ``[n]`` set, with the original numbers preserved.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(script: str) -> dict:
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout.strip())


_SHIM = r'''
const fs = require("node:fs");
class El {
  constructor(tag){ this.tagName = String(tag).toUpperCase(); this.children = []; this.className = ""; this._text = ""; this.isConnected = true; this._attrs = {}; }
  get textContent(){ return this.children.length ? this.children.map((c) => c.textContent).join("") : this._text; }
  set textContent(v){ this._text = String(v ?? ""); this.children = []; }
  appendChild(c){ this.children.push(c); return c; }
  append(...ns){ ns.forEach((n) => this.appendChild(n)); }
  remove(){}
  setAttribute(k, v){ this._attrs[k] = String(v); }
  matches(sel){
    sel = String(sel).trim();
    if (sel.startsWith(".")) return String(this.className || "").split(/\s+/).includes(sel.slice(1));
    const dot = sel.indexOf(".");
    if (dot > 0){ const tag = sel.slice(0, dot).toUpperCase(); const cls = sel.slice(dot + 1); return this.tagName === tag && String(this.className || "").split(/\s+/).includes(cls); }
    return this.tagName === sel.toUpperCase();
  }
  _walk(out){ for (const c of this.children){ out.push(c); if (c.children && c.children.length) c._walk(out); } return out; }
  querySelector(sel){ return this._walk([]).find((n) => n.matches && n.matches(sel)) || null; }
  querySelectorAll(sel){ return this._walk([]).filter((n) => n.matches && n.matches(sel)); }
}
global.Element = El;
global.document = { createElement: (t) => new El(t), createTextNode: (v) => { const n = new El("#TEXT"); n._text = String(v); return n; } };
global.window = {};
'''


def _visible_numbers(file_name: str, answer: str) -> list[str]:
    path = (ROOT / "static" / file_name).as_posix()
    script = _SHIM + f'''
const src = fs.readFileSync("{path}", "utf-8");
eval(src);
const render = (global.window.PadiemSearchSources || global.window.PadiemClawAnswerSources).render;
function makeArticle(answer) {{
  const article = new El("article"); article.className = "assistant-message";
  const content = new El("div"); content.className = "assistant-content";
  const p = new El("p"); p.textContent = answer; content.appendChild(p);
  article.appendChild(content);
  return {{ article, content }};
}}
const evidence = [1,2,3,4].map((i) => ({{ url: "https://example.com/" + i, title: "제목" + i, retrieved_at: "2026-11-16" }}));
const {{ article, content }} = makeArticle({json.dumps(answer, ensure_ascii=False)});
render(article, evidence);
const section = content.querySelector(".answer-sources");
if (!section) console.log(JSON.stringify({{ numbers: [], count: 0 }}));
else {{
  const ol = section.querySelector("ol");
  const numbers = [];
  for (const li of ol.children) {{
    const all = []; li._walk(all);
    const span = all.find((n) => n.tagName === "SPAN" && String(n.className || "").includes("answer-source-number"));
    numbers.push(span ? span.textContent : "?");
  }}
  console.log(JSON.stringify({{ numbers, count: ol.children.length }}));
}}
'''
    return _run_node(script)["numbers"]


def test_search_sources_show_only_cited_evidence() -> None:
    assert _visible_numbers("search-sources.js", "가격은 [1]에 따라 달라요. 자세한 건 [3]을 보세요.") == ["[1]", "[3]"]
    assert _visible_numbers("search-sources.js", "근거 [2] 하나만 썼어요.") == ["[2]"]


def test_search_sources_hide_uncited_answer() -> None:
    assert _visible_numbers("search-sources.js", "공지 문구입니다. 출처 없이 작성했어요.") == []


def test_search_sources_keep_static_contract() -> None:
    js = (ROOT / "static" / "search-sources.js").read_text(encoding="utf-8")
    assert "function renderSources(article, evidence, research = null)" in js
    assert "citedSourceNumbers(answerText)" in js
    assert "cited.has(entry.index + 1)" in js
    assert 'number.textContent = `[${index + 1}]`' in js
    assert "innerHTML" not in js
    assert "insertAdjacentHTML" not in js
