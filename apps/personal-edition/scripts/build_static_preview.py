"""Build static UI preview for Cloudflare Pages.

Renders existing Jinja2 templates with synthetic fixture data into
dist-preview/ for visual review without backend services.

Usage:
    python -m scripts.build_static_preview
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader

from preview_fixtures.data import (
    make_edition,
    make_edition_content,
    make_feedback_directions,
    make_feedback_map,
    make_feedbacks,
    make_feedbacks_with_editions,
    make_generation_runs,
    make_inputs,
    make_participant,
    make_queue_items,
    make_status_info,
    make_summary_counts,
)

_BASE_DIR = Path(__file__).resolve().parent.parent
_TEMPLATE_DIR = _BASE_DIR / "templates"
_STATIC_DIR = _BASE_DIR / "static"
_OUTPUT_DIR = _BASE_DIR / "dist-preview"

_PREVIEW_BANNER = (
    '<div class="preview-banner">'
    "UI Preview \u00b7 Synthetic data \u00b7 No persistence"
    "</div>"
)

_PREVIEW_CSS = """
.preview-banner {
  background: #fbbf24;
  color: #92400e;
  text-align: center;
  padding: 0.5rem 1rem;
  font-size: 0.8rem;
  font-weight: 600;
}
form button[type="submit"],
form input[type="submit"] {
  opacity: 0.5;
  cursor: not-allowed;
}
"""

_HEADERS_CONTENT = """\
/*
  X-Robots-Tag: noindex, nofollow
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; script-src 'none'; connect-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'self'
"""


class _MockRequest:
    def __init__(self, path: str) -> None:
        self.url = SimpleNamespace(path=path)


def _build_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["feedback_directions"] = make_feedback_directions()
    return env


def _render(
    env: Environment,
    template_name: str,
    context: dict,
    request_path: str,
) -> str:
    context["request"] = _MockRequest(request_path)
    context["csrf_token"] = "preview-csrf-token"
    template = env.get_template(template_name)
    return template.render(context)


def _post_process(html: str) -> str:
    html = html.replace(
        '<meta name="viewport"',
        '<meta name="robots" content="noindex,nofollow">\n<meta name="viewport"',
        1,
    )
    html = html.replace(
        "</head>",
        f"<style>{_PREVIEW_CSS}</style>\n</head>",
        1,
    )
    html = re.sub(
        r"(<body[^>]*>)",
        lambda m: m.group(1) + "\n" + _PREVIEW_BANNER,
        html,
        count=1,
    )
    return html


def _write_page(
    env: Environment,
    template_name: str,
    context: dict,
    request_path: str,
    output_rel_path: str,
) -> None:
    html = _render(env, template_name, context, request_path)
    html = _post_process(html)
    out_file = _OUTPUT_DIR / output_rel_path
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html, encoding="utf-8")


def _copy_static() -> None:
    dest = _OUTPUT_DIR / "static"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(_STATIC_DIR, dest)


def _write_headers() -> None:
    (_OUTPUT_DIR / "_headers").write_text(_HEADERS_CONTENT, encoding="utf-8")


def _write_robots_txt() -> None:
    (_OUTPUT_DIR / "robots.txt").write_text(
        "User-agent: *\nDisallow: /\n", encoding="utf-8"
    )


def main() -> None:
    if _OUTPUT_DIR.exists():
        shutil.rmtree(_OUTPUT_DIR)
    _OUTPUT_DIR.mkdir(parents=True)

    env = _build_jinja_env()

    participant = make_participant()
    edition_published = make_edition(
        publication_state="published", generation_status="published"
    )
    edition_pending = make_edition(
        publication_state="pending", generation_status="pending_review"
    )
    content = make_edition_content()
    inputs = make_inputs()
    runs = make_generation_runs()
    feedbacks = make_feedbacks()
    feedback_map = make_feedback_map()
    published_editions = [edition_published]
    latest_input = inputs[-1] if inputs else None

    _write_page(
        env, "preview_index.html", {}, "/", "index.html"
    )

    _write_page(
        env, "admin_access.html",
        {"error": None},
        "/admin/access", "admin/access/index.html",
    )

    _write_page(
        env, "admin_dashboard.html",
        {
            "summary_counts": make_summary_counts(),
            "queue_items": make_queue_items(participant, edition_published, latest_input),
            "provider_name": "mock",
            "model_name": "mock-personal-edition-v1",
            "actual_provider": "mock",
            "actual_model": "mock-personal-edition-v1",
            "recent_generation_runs": runs,
        },
        "/admin/", "admin/index.html",
    )

    _write_page(
        env, "admin_participant_detail.html",
        {
            "participant": participant,
            "status_info": make_status_info(),
            "generation_error": None,
            "latest_input": latest_input,
            "inputs": inputs,
            "editions": [edition_published],
            "feedbacks_with_editions": make_feedbacks_with_editions(
                participant, edition_published, feedbacks[0]
            ),
            "feedback_map": feedback_map,
        },
        "/admin/participants/modal-preview-user",
        "admin/participants/modal-preview-user/index.html",
    )

    _write_page(
        env, "admin_review.html",
        {
            "edition": edition_pending,
            "content": content,
            "participant": participant,
            "error": None,
            "feedbacks": feedbacks,
            "generation_runs": runs,
            "feedback_map": feedback_map,
        },
        "/admin/review/modal-preview-edition",
        "admin/review/modal-preview-edition/index.html",
    )

    _write_page(
        env, "token_entry.html",
        {"error": None},
        "/p/access", "p/access/index.html",
    )

    _write_page(
        env, "participant_dashboard.html",
        {
            "participant": participant,
            "published_editions": published_editions,
            "input_count": len(inputs),
        },
        "/p/modal-preview-user",
        "p/modal-preview-user/index.html",
    )

    _write_page(
        env, "input_form.html",
        {
            "participant": participant,
            "error": None,
            "success": None,
            "raw_text": "",
        },
        "/p/modal-preview-user/input",
        "p/modal-preview-user/input/index.html",
    )

    _write_page(
        env, "edition_read.html",
        {
            "participant": participant,
            "edition": edition_published,
            "content": content,
            "prior_feedback_summary": None,
            "has_given_feedback": False,
            "next_edition_number": None,
        },
        "/p/modal-preview-user/editions/modal-preview-edition",
        "p/modal-preview-user/editions/modal-preview-edition/index.html",
    )

    _write_page(
        env, "feedback_form.html",
        {
            "participant": participant,
            "edition": edition_published,
            "content": content,
            "error": None,
        },
        "/p/modal-preview-user/editions/modal-preview-edition/feedback",
        "p/modal-preview-user/editions/modal-preview-edition/feedback/index.html",
    )

    _write_page(
        env, "feedback_thanks.html",
        {
            "participant": participant,
            "edition_number": "modal-preview-edition",
        },
        "/p/modal-preview-user/editions/modal-preview-edition/feedback/thanks",
        "p/modal-preview-user/editions/modal-preview-edition/feedback/thanks/index.html",
    )

    _write_page(
        env, "participant_history.html",
        {
            "participant": participant,
            "editions": published_editions,
        },
        "/p/modal-preview-user/history",
        "p/modal-preview-user/history/index.html",
    )

    _write_page(
        env, "not_found.html",
        {
            "participant": participant,
            "message": "요청하신 페이지를 찾을 수 없습니다.",
        },
        "/p/modal-preview-user/not-found",
        "p/modal-preview-user/not-found/index.html",
    )

    _copy_static()
    _write_headers()
    _write_robots_txt()

    print(f"Static preview built at {_OUTPUT_DIR}")


if __name__ == "__main__":
    main()
