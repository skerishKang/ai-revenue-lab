"""Simple template renderer for Living Travel Phase 2."""

from __future__ import annotations

import html
import re
from pathlib import Path

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _load_template(name: str) -> str:
    path = _TEMPLATE_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {name}")
    return path.read_text(encoding="utf-8")


def _escape(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _render_loop(template_body: str, context: dict) -> str:
    pattern = r"\{%\s*for\s+(\w+)\s+in\s+(\w+)\s*%\}(.*?)\{%\s*endfor\s*%\}"
    def replace_loop(m):
        var_name = m.group(1)
        collection_name = m.group(2)
        body = m.group(3)
        collection = context.get(collection_name, [])
        result = []
        for item in collection:
            inner_ctx = {**context, var_name: item}
            rendered = _render_vars(body, inner_ctx)
            result.append(rendered)
        return "".join(result)
    return re.sub(pattern, replace_loop, template_body, flags=re.DOTALL)


def _render_conditionals(template_body: str, context: dict) -> str:
    pattern = r"\{%\s*if\s+(\w+)\s*%\}(.*?)\{%\s*endif\s*%\}"
    def replace_cond(m):
        var_name = m.group(1)
        body = m.group(2)
        value = context.get(var_name)
        if value:
            return _render_vars(body, context)
        return ""
    return re.sub(pattern, replace_cond, template_body, flags=re.DOTALL)




def _resolve_path(obj, path_str: str, max_depth: int = 5):
    """Resolve dotted path against an object with security restrictions."""
    parts = path_str.split(".")
    if len(parts) > max_depth:
        return None
    for part in parts:
        if obj is None:
            return None
        # Reject private/dunder attributes
        if part.startswith("_"):
            return None
        if hasattr(obj, part):
            obj = getattr(obj, part)
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def _render_vars(template_body: str, context: dict) -> str:
    def replace_var(m):
        var_path = m.group(1).strip()
        parts = var_path.split(".", 1)
        obj = context.get(parts[0])
        if obj is None:
            return ""
        if len(parts) > 1:
            value = _resolve_path(obj, parts[1])
            if value is None:
                value = ""
        else:
            value = obj
        if isinstance(value, (list, dict)):
            import json
            return _escape(json.dumps(value, ensure_ascii=False))
        return _escape(value)
    return re.sub(r"\{\{(.*?)\}\}", replace_var, template_body)


def render_template(name: str, context: dict) -> str:
    template = _load_template(name)
    rendered = _render_loop(template, context)
    rendered = _render_conditionals(rendered, context)
    rendered = _render_vars(rendered, context)
    return rendered
