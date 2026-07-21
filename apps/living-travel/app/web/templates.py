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


def _resolve_path(obj, path_str: str, max_depth: int = 5):
    """Resolve dotted path against an object with security restrictions."""
    parts = path_str.split(".")
    if len(parts) > max_depth:
        return None
    for part in parts:
        if obj is None:
            return None
        if part.startswith("_"):
            return None
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            return None
    return obj


def _resolve_context_path(context: dict, path_str: str):
    parts = path_str.split(".", 1)
    value = context.get(parts[0])
    if value is None:
        return None
    if len(parts) == 1:
        return value
    return _resolve_path(value, parts[1])


def _render_loop(template_body: str, context: dict) -> str:
    result = template_body
    while "{% for " in result and "{% endfor %}" in result:
        pattern = r"\{%\s*for\s+(\w+)\s+in\s+([\w.]+)\s*%\}"
        match = re.search(pattern, result)
        if not match:
            break

        var_name = match.group(1)
        collection_path = match.group(2)
        collection = _resolve_context_path(context, collection_path)
        if collection is None:
            collection = []

        start = match.start()
        body_start = match.end()
        depth = 1
        pos = body_start
        while depth > 0 and pos < len(result):
            next_for = re.search(
                r"\{%\s*for\s+\w+\s+in\s+[\w.]+\s*%\}",
                result[pos:],
            )
            next_endfor = re.search(r"\{%\s*endfor\s*%\}", result[pos:])
            if next_endfor is None:
                break
            if next_for and next_for.start() < next_endfor.start():
                depth += 1
                pos += next_for.end()
            else:
                depth -= 1
                if depth == 0:
                    body_end = pos + next_endfor.start()
                    end = pos + next_endfor.end()
                    body = result[body_start:body_end]
                    rendered_items = []
                    for item in collection:
                        inner_context = {**context, var_name: item}
                        rendered_items.append(_render_fragment(body, inner_context))
                    result = result[:start] + "".join(rendered_items) + result[end:]
                    break
                pos += next_endfor.end()
    return result


def _render_conditionals(template_body: str, context: dict) -> str:
    result = template_body
    while "{% if " in result and "{% endif %}" in result:
        pattern = r"\{%\s*if\s+([\w.]+)\s*%\}"
        match = re.search(pattern, result)
        if not match:
            break

        condition_path = match.group(1)
        start = match.start()
        body_start = match.end()
        depth = 1
        pos = body_start
        else_pos = None

        while depth > 0 and pos < len(result):
            next_if = re.search(r"\{%\s*if\s+[\w.]+\s*%\}", result[pos:])
            next_else = re.search(r"\{%\s*else\s*%\}", result[pos:])
            next_endif = re.search(r"\{%\s*endif\s*%\}", result[pos:])
            if next_endif is None:
                break

            if (
                next_if
                and next_if.start() < next_endif.start()
                and (next_else is None or next_if.start() < next_else.start())
            ):
                depth += 1
                pos += next_if.end()
            elif (
                next_else
                and next_else.start() < next_endif.start()
                and depth == 1
                and else_pos is None
            ):
                else_pos = pos + next_else.start()
                pos += next_else.end()
            else:
                depth -= 1
                if depth == 0:
                    body_end = pos + next_endif.start()
                    end = pos + next_endif.end()
                    if else_pos is not None:
                        true_body = result[body_start:else_pos]
                        false_body = result[else_pos + len("{% else %}"):body_end]
                    else:
                        true_body = result[body_start:body_end]
                        false_body = ""

                    selected_body = (
                        true_body
                        if _resolve_context_path(context, condition_path)
                        else false_body
                    )
                    result = (
                        result[:start]
                        + _render_fragment(selected_body, context)
                        + result[end:]
                    )
                    break
                pos += next_endif.end()
    return result


def _render_vars(template_body: str, context: dict) -> str:
    def replace_var(match):
        value = _resolve_context_path(context, match.group(1).strip())
        if value is None:
            return ""
        if isinstance(value, (list, dict)):
            import json

            return _escape(json.dumps(value, ensure_ascii=False))
        return _escape(value)

    return re.sub(r"\{\{(.*?)\}\}", replace_var, template_body)


def _render_fragment(template_body: str, context: dict) -> str:
    rendered = _render_loop(template_body, context)
    rendered = _render_conditionals(rendered, context)
    return _render_vars(rendered, context)


def render_template(name: str, context: dict) -> str:
    return _render_fragment(_load_template(name), context)
