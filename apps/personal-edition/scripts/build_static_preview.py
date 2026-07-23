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
    make_pending_edition,
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
    context.setdefault("_link_prefix", "/preview/participant")
    context["request"] = _MockRequest(request_path)
    context["csrf_token"] = "preview-csrf-token"
    context["is_preview"] = True
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


_REDIRECT_HTML = (
    '<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
    '<meta name="robots" content="noindex,nofollow">'
    '<meta http-equiv="refresh" content="0;url=/"></head>'
    '<body><div class="preview-banner">UI Preview \u00b7 Synthetic data \u00b7 No persistence</div>'
    '<p><a href="/">미리보기 목록으로 돌아가기</a></p></body></html>'
)


def _write_redirects() -> None:
    participant_dir = _OUTPUT_DIR / "preview" / "participant"
    participant_dir.mkdir(parents=True, exist_ok=True)
    (participant_dir / "index.html").write_text(_REDIRECT_HTML, encoding="utf-8")
    editions_dir = _OUTPUT_DIR / "preview" / "participant" / "editions"
    editions_dir.mkdir(parents=True, exist_ok=True)
    (editions_dir / "index.html").write_text(_REDIRECT_HTML, encoding="utf-8")


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
        "/p/access", "preview/participant/access/index.html",
    )

    _write_page(
        env, "participant_dashboard.html",
        {
            "participant": participant,
            "published_editions": [],
            "pending_editions": [],
            "input_count": 0,
            "has_feedback_on_latest": False,
            "workflow_stage": "record",
        },
        "/preview/participant/empty",
        "preview/participant/empty/index.html",
    )

    _write_page(
        env, "participant_dashboard.html",
        {
            "participant": participant,
            "published_editions": [],
            "pending_editions": [],
            "input_count": len(inputs),
            "has_feedback_on_latest": False,
            "workflow_stage": "input_received",
        },
        "/preview/participant/input-received",
        "preview/participant/input-received/index.html",
    )

    _write_page(
        env, "participant_dashboard.html",
        {
            "participant": participant,
            "published_editions": [],
            "pending_editions": [make_pending_edition()],
            "input_count": len(inputs),
            "has_feedback_on_latest": False,
            "workflow_stage": "reviewing",
        },
        "/preview/participant/editing",
        "preview/participant/editing/index.html",
    )

    _write_page(
        env, "participant_dashboard.html",
        {
            "participant": participant,
            "published_editions": published_editions,
            "pending_editions": [],
            "input_count": len(inputs),
            "has_feedback_on_latest": False,
            "workflow_stage": "published",
        },
        "/preview/participant/published",
        "preview/participant/published/index.html",
    )

    _write_page(
        env, "participant_dashboard.html",
        {
            "participant": participant,
            "published_editions": published_editions,
            "pending_editions": [],
            "input_count": len(inputs),
            "has_feedback_on_latest": True,
            "workflow_stage": "feedback",
        },
        "/preview/participant/feedback",
        "preview/participant/feedback/index.html",
    )

    _write_page(
        env, "input_form.html",
        {
            "participant": participant,
            "error": None,
            "success": None,
            "raw_text": "",
        },
        "/preview/participant/input",
        "preview/participant/input/index.html",
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
        f"/preview/participant/editions/{edition_published.edition_number}",
        f"preview/participant/editions/{edition_published.edition_number}/index.html",
    )

    _write_page(
        env, "feedback_form.html",
        {
            "participant": participant,
            "edition": edition_published,
            "content": content,
            "error": None,
        },
        f"/preview/participant/editions/{edition_published.edition_number}/feedback",
        f"preview/participant/editions/{edition_published.edition_number}/feedback/index.html",
    )

    _write_page(
        env, "feedback_thanks.html",
        {
            "participant": participant,
            "edition_number": edition_published.edition_number,
        },
        f"/preview/participant/editions/{edition_published.edition_number}/feedback/thanks",
        f"preview/participant/editions/{edition_published.edition_number}/feedback/thanks/index.html",
    )

    _write_page(
        env, "participant_history.html",
        {
            "participant": participant,
            "editions": published_editions,
        },
        "/preview/participant/history",
        "preview/participant/history/index.html",
    )

    _write_page(
        env, "not_found.html",
        {
            "participant": participant,
            "message": "요청하신 페이지를 찾을 수 없습니다.",
        },
        "/preview/participant/not-found",
        "preview/participant/not-found/index.html",
    )

    _write_page(
        env, "intro.html",
        {},
        "/preview/intro",
        "preview/intro/index.html",
    )

    _write_page(
        env, "transformation.html",
        {
            "participant": participant,
            "edition": edition_published,
            "content": content,
        },
        "/preview/participant/transformation",
        "preview/participant/transformation/index.html",
    )

    _write_page(
        env, "feedback_adaptation.html",
        {
            "participant": participant,
            "edition": edition_published,
            "content": content,
        },
        f"/preview/participant/editions/{edition_published.edition_number}/adaptation",
        f"preview/participant/editions/{edition_published.edition_number}/adaptation/index.html",
    )

    _write_page(
        env, "admin_evidence.html",
        {
            "edition": edition_pending,
            "content": content,
            "participant": participant,
            "runs": runs,
            "provider_name": "mock",
            "model_name": "mock-personal-edition-v1",
        },
        "/admin/review/modal-preview-edition/evidence",
        "admin/review/modal-preview-edition/evidence/index.html",
    )

    _write_page(
        env, "admin_content_review.html",
        {
            "edition": edition_pending,
            "content": content,
            "participant": participant,
            "input_count": len(inputs),
            "feedbacks": feedbacks,
        },
        "/admin/review/modal-preview-edition/content",
        "admin/review/modal-preview-edition/content/index.html",
    )

    _copy_static()
    _write_headers()
    _write_robots_txt()
    _write_redirects()

    print(f"Static preview built at {_OUTPUT_DIR}")


if __name__ == "__main__":
    main()
