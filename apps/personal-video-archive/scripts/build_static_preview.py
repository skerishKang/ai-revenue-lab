"""Build a static UI preview for Cloudflare Pages.

Renders the *existing* Jinja2 templates with synthetic fixture data into
``dist-preview/`` so the accepted Phase 1 UI can be reviewed in a hosted
browser without any backend service.

Safety contract:
    * synthetic fixtures only (no real personal data, no real YouTube ids);
    * no database, FastAPI server, provider, API key, or network call;
    * inline event-handler JavaScript is stripped from every page;
    * forms are made inert via a restrictive Content-Security-Policy
      (``form-action 'none'; script-src 'none'``) in ``_headers``;
    * every page carries ``noindex, nofollow`` and a visible preview banner;
    * ``robots.txt`` disallows all crawling.

Usage (from the ``apps/personal-video-archive`` workspace)::

    python -m scripts.build_static_preview
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader

from preview_fixtures.data import (
    THUMBNAIL_URL,
    filter_feed_by_state,
    make_query_rule,
    make_query_rule_proposal,
    make_record_completed,
    make_record_in_progress,
    make_record_saved,
    make_search_results,
    make_structure_proposal,
    make_timestamps,
    make_topic,
    make_topic1_feed,
    make_topic1_topic_videos,
    make_topic1_videos,
    make_topic2_feed,
    make_topic2_topic_videos,
    make_topics,
)

_BASE_DIR = Path(__file__).resolve().parent.parent
_TEMPLATE_DIR = _BASE_DIR / "templates"
_STATIC_DIR = _BASE_DIR / "static"
_OUTPUT_DIR = _BASE_DIR / "dist-preview"

_PREVIEW_BANNER_TEXT = "UI Preview \u00b7 Synthetic data \u00b7 No persistence"
_PREVIEW_BANNER = (
    '<div class="preview-banner">' + _PREVIEW_BANNER_TEXT + "</div>"
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

# Restrictive Cloudflare Pages headers: no scripts, no form submission, no
# external connections, no framing, no indexing.
_HEADERS_CONTENT = """\
/*
  X-Robots-Tag: noindex, nofollow
  Referrer-Policy: no-referrer
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Content-Security-Policy: default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; script-src 'none'; connect-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'self'
"""

_ROBOTS_CONTENT = "User-agent: *\nDisallow: /\n"

# Local placeholder thumbnail (no external image host, no production CDN URL).
_PLACEHOLDER_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180" role="img" aria-label="Synthetic preview thumbnail">
  <rect width="320" height="180" fill="#1f2937"/>
  <rect x="1" y="1" width="318" height="178" fill="none" stroke="#4b5563" stroke-width="2"/>
  <circle cx="160" cy="82" r="30" fill="#374151"/>
  <polygon points="150,68 150,96 176,82" fill="#fbbf24"/>
  <text x="160" y="140" fill="#9ca3af" font-family="sans-serif" font-size="14" text-anchor="middle">Synthetic preview</text>
</svg>
"""

# Synthetic health page (the live /health endpoint returns JSON; this is a
# clearly-labelled static stand-in so the navigation link resolves).
_HEALTH_TEMPLATE = """{% extends "base.html" %}
{% block title %}Health \u2014 Personal Video Archive{% endblock %}
{% block content %}
<div class="page-header">
    <h1>Health</h1>
</div>
<div class="info-box">
    <p><strong>Status:</strong> ok (synthetic)</p>
    <p><strong>Discovery provider:</strong> FakeVideoDiscoveryProvider</p>
    <p><strong>LLM provider:</strong> FakeLanguageModelProvider</p>
    <p class="small">
        Synthetic health snapshot for the static UI preview. No live service,
        database, or provider is contacted.
    </p>
</div>
{% endblock %}
"""

# Matches an inline HTML event-handler attribute, e.g. onerror="..." or
# onchange='...'. These are stripped so no inline JavaScript survives into the
# generated preview.
_INLINE_HANDLER_RE = re.compile(r"""\s+on[a-z]+\s*=\s*("[^"]*"|'[^']*')""", re.IGNORECASE)


class _MockRequest:
    """Minimal stand-in for a Starlette Request during static rendering."""

    def __init__(self, path: str) -> None:
        self.url = SimpleNamespace(path=path)


def _build_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    def _tojson(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _fromjson(value: object) -> object:
        return json.loads(value) if isinstance(value, str) else value

    def _format_thousands(value: object) -> str:
        try:
            return f"{int(value):,}"
        except (ValueError, TypeError):
            return str(value)

    env.filters["tojson"] = _tojson
    env.filters["fromjson"] = _fromjson
    env.filters["format_thousands"] = _format_thousands
    return env


def _render(env: Environment, template_name: str, context: dict, request_path: str) -> str:
    ctx = dict(context)
    ctx["request"] = _MockRequest(request_path)
    ctx["is_preview"] = True
    template = env.get_template(template_name)
    return template.render(ctx)


def _strip_inline_handlers(html: str) -> str:
    return _INLINE_HANDLER_RE.sub("", html)


def _post_process(html: str) -> str:
    # noindex / nofollow
    html = html.replace(
        '<meta name="viewport"',
        '<meta name="robots" content="noindex,nofollow">\n<meta name="viewport"',
        1,
    )
    # preview styling (banner + visually-disabled submit controls)
    html = html.replace("</head>", f"<style>{_PREVIEW_CSS}</style>\n</head>", 1)
    # visible preview banner immediately after <body ...>
    html = re.sub(
        r"(<body[^>]*>)",
        lambda m: m.group(1) + "\n" + _PREVIEW_BANNER,
        html,
        count=1,
    )
    # remove every inline event handler so no inline JS remains
    html = _strip_inline_handlers(html)
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


def _write_raw_page(html: str, output_rel_path: str) -> None:
    out_file = _OUTPUT_DIR / output_rel_path
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html, encoding="utf-8")


def _copy_static() -> None:
    dest = _OUTPUT_DIR / "static"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(_STATIC_DIR, dest)
    # synthetic placeholder thumbnail referenced by the fixtures
    placeholder_name = THUMBNAIL_URL.rsplit("/", 1)[-1]
    (dest / placeholder_name).write_text(_PLACEHOLDER_SVG, encoding="utf-8")


def _write_headers() -> None:
    (_OUTPUT_DIR / "_headers").write_text(_HEADERS_CONTENT, encoding="utf-8")


def _write_robots_txt() -> None:
    (_OUTPUT_DIR / "robots.txt").write_text(_ROBOTS_CONTENT, encoding="utf-8")


def main() -> None:
    if _OUTPUT_DIR.exists():
        shutil.rmtree(_OUTPUT_DIR)
    _OUTPUT_DIR.mkdir(parents=True)

    env = _build_jinja_env()

    topics = make_topics()
    topic1 = make_topic("pv-topic-0001")
    topic2 = make_topic("pv-topic-0002")
    topic3 = make_topic("pv-topic-0003")

    rules = make_query_rule()
    rule_proposal = make_query_rule_proposal()

    topic1_feed = make_topic1_feed()
    topic2_feed = make_topic2_feed()
    feed_states = [
        "all", "unseen", "opened", "saved", "in_progress",
        "completed", "revisit", "irrelevant",
    ]

    videos = make_topic1_videos()
    topic1_tvs = make_topic1_topic_videos()

    rec_completed = make_record_completed()
    rec_in_progress = make_record_in_progress()
    rec_saved = make_record_saved()
    timestamps = make_timestamps()
    structure_proposal = make_structure_proposal()

    # --- Preview landing / index -----------------------------------------
    _write_page(env, "preview_index.html", {}, "/", "index.html")

    # --- Product home / topic list ---------------------------------------
    _write_page(
        env, "index.html", {"topics": topics}, "/home", "home/index.html"
    )
    _write_page(
        env, "topics/list.html", {"topics": topics}, "/topics", "topics/index.html"
    )

    # --- New topic --------------------------------------------------------
    _write_page(env, "topics/new.html", {}, "/topics/new", "topics/new/index.html")

    # --- LLM query-rule review -------------------------------------------
    _write_page(
        env,
        "topics/review_rule.html",
        {"topic": topic1, "proposal": rule_proposal},
        "/topics/pv-topic-0001/review-rule",
        "topics/pv-topic-0001/review-rule/index.html",
    )

    # --- Populated newest-first feed (topic 1) ---------------------------
    _write_page(
        env,
        "topics/feed.html",
        {
            "topic": topic1,
            "rules": rules,
            "feed": topic1_feed,
            "current_state_filter": "all",
            "feed_states": feed_states,
            "sync_failed": False,
        },
        "/topics/pv-topic-0001",
        "topics/pv-topic-0001/index.html",
    )

    # --- Feed filtered to unseen -----------------------------------------
    _write_page(
        env,
        "topics/feed.html",
        {
            "topic": topic1,
            "rules": rules,
            "feed": filter_feed_by_state(topic1_feed, "unseen"),
            "current_state_filter": "unseen",
            "feed_states": feed_states,
            "sync_failed": False,
        },
        "/topics/pv-topic-0001?state=unseen",
        "topics/pv-topic-0001/unseen/index.html",
    )

    # --- Feed filtered to completed --------------------------------------
    _write_page(
        env,
        "topics/feed.html",
        {
            "topic": topic1,
            "rules": rules,
            "feed": filter_feed_by_state(topic1_feed, "completed"),
            "current_state_filter": "completed",
            "feed_states": feed_states,
            "sync_failed": False,
        },
        "/topics/pv-topic-0001?state=completed",
        "topics/pv-topic-0001/completed/index.html",
    )

    # --- Empty / no-results feed -----------------------------------------
    _write_page(
        env,
        "topics/feed.html",
        {
            "topic": topic3,
            "rules": None,
            "feed": [],
            "current_state_filter": "all",
            "feed_states": feed_states,
            "sync_failed": False,
        },
        "/topics/pv-topic-0001/empty",
        "topics/pv-topic-0001/empty/index.html",
    )

    # --- Provider refresh failure, existing feed preserved ---------------
    _write_page(
        env,
        "topics/feed.html",
        {
            "topic": topic1,
            "rules": rules,
            "feed": topic1_feed,
            "current_state_filter": "all",
            "feed_states": feed_states,
            "sync_failed": True,
        },
        "/topics/pv-topic-0001/refresh-failed",
        "topics/pv-topic-0001/refresh-failed/index.html",
    )

    # --- Secondary topic feed (keeps topic-card links resolvable) --------
    _write_page(
        env,
        "topics/feed.html",
        {
            "topic": topic2,
            "rules": None,
            "feed": topic2_feed,
            "current_state_filter": "all",
            "feed_states": feed_states,
            "sync_failed": False,
        },
        "/topics/pv-topic-0002",
        "topics/pv-topic-0002/index.html",
    )

    # --- Archived topic feed (empty) -------------------------------------
    _write_page(
        env,
        "topics/feed.html",
        {
            "topic": topic3,
            "rules": None,
            "feed": [],
            "current_state_filter": "all",
            "feed_states": feed_states,
            "sync_failed": False,
        },
        "/topics/pv-topic-0003",
        "topics/pv-topic-0003/index.html",
    )

    # --- Video detail -----------------------------------------------------
    _write_page(
        env,
        "videos/detail.html",
        {
            "video": videos[0],
            "topic_videos": [topic1_tvs[0]],
            "records": [(topic1_tvs[0], rec_completed)],
        },
        "/videos/pv-video-0001",
        "videos/pv-video-0001/index.html",
    )

    # --- Private record detail / edit (free-form, minimal) ---------------
    _write_page(
        env,
        "records/detail.html",
        {
            "record": rec_saved,
            "topic_video": topic1_tvs[2],
            "video": videos[2],
            "timestamps": [],
            "pending_proposals": [],
        },
        "/records/pv-rec-0003",
        "records/pv-rec-0003/index.html",
    )

    # --- Record with a pending LLM structure proposal --------------------
    _write_page(
        env,
        "records/detail.html",
        {
            "record": rec_in_progress,
            "topic_video": topic1_tvs[1],
            "video": videos[1],
            "timestamps": [],
            "pending_proposals": [structure_proposal],
        },
        "/records/pv-rec-0002",
        "records/pv-rec-0002/index.html",
    )

    # --- Accepted / structured private record ----------------------------
    _write_page(
        env,
        "records/detail.html",
        {
            "record": rec_completed,
            "topic_video": topic1_tvs[0],
            "video": videos[0],
            "timestamps": timestamps,
            "pending_proposals": [],
        },
        "/records/pv-rec-0001",
        "records/pv-rec-0001/index.html",
    )

    # --- Record search results -------------------------------------------
    _write_page(
        env,
        "records/search.html",
        {
            "results": make_search_results(),
            "filters": {"topic_id": None, "state": None, "tags": None, "q": "pytorch"},
        },
        "/records",
        "records/index.html",
    )

    # --- Validation error example ----------------------------------------
    _write_page(
        env,
        "error.html",
        {
            "code": 400,
            "message": (
                "Invalid tag: '123preview'. Tags must start with a letter "
                "and contain only letters, digits, spaces, hyphens, and "
                "underscores (1-40 chars)."
            ),
        },
        "/error",
        "error/index.html",
    )

    # --- Synthetic health page (resolves the nav link) -------------------
    health_html = _post_process(
        env.from_string(_HEALTH_TEMPLATE).render(request=_MockRequest("/health"))
    )
    _write_raw_page(health_html, "health/index.html")

    _copy_static()
    _write_headers()
    _write_robots_txt()

    print(f"Static preview built at {_OUTPUT_DIR}")


if __name__ == "__main__":
    main()
