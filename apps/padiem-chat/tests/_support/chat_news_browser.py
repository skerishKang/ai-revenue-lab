"""Isolated browser fixture serving the actual Chat news assets."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

STATIC = Path(__file__).resolve().parents[2] / "static"
THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
WIDTHS = (390, 768, 1440)
ORIGIN = "https://chat-news.invalid"

NEWS = [
    dict(number=9, kind="improved", title="PC connection improvements",
         detail="Connect to your PC and check its status more easily.",
         source="ai_tester", published_at="2026-11-16T09:00:00Z", version="2026.11.16"),
    dict(number=8, kind="fixed", title="Conversation list",
         detail="The selected conversation stays visible when switching views.",
         source="user", published_at="2026-11-16T09:00:00Z", version="2026.11.16"),
    dict(number=7, kind="fixed", title="Attachment preview",
         detail="Long filenames wrap within the preview panel.",
         source="ai_tester", published_at="2026-11-16T09:00:00Z", version="2026.11.16"),
    dict(number=6, kind="improved", title="Search",
         detail="Find earlier conversations from the sidebar.",
         source="none", published_at="2026-11-12T09:00:00Z", version="2026.11.12"),
    dict(number=5, kind="fixed", title="Settings",
         detail="Opening settings retains your current theme.",
         source="none", published_at="2026-11-15T09:00:00Z", version=""),
    dict(number=4, kind="improved", title="Accessibility",
         detail="Keyboard navigation is easier.",
         source="ai_tester", published_at="2026-11-15T09:00:00Z", version=""),
    dict(number=3, kind="fixed", title="Mobile layout",
         detail="Long text remains inside the card.",
         source="none", published_at="2026-11-13T09:00:00Z", version=""),
]


def open_news(browser, theme, width, overrides=None, language="en"):
    """Load the real HTML/CSS/news module; all network requests are intercepted."""
    overrides = overrides or {}
    html = overrides.get("index.html", (STATIC / "index.html").read_text(encoding="utf-8"))
    html = re.sub(r"<script\b[^>]*>[\s\S]*?</script\s*>", "", html, flags=re.I)
    script = """<script src="/locale-feedback-news.js"></script><script>
    window.PadiemAuthSession = {get: () => ({authenticated: true, ownerKey: "fixture"})};
    const language = """ + json.dumps(language) + """;
    window.__padiemLocale = {text: (key, values) => {
      let label = window.PadiemLocaleGroups["feedback-news"][language][key] || key;
      for (const [name, value] of Object.entries(values || {}))
        label = label.replace("{" + name + "}", value);
      return label;
    }};
    document.documentElement.lang = language;
    for (const el of document.querySelectorAll("#newsDialog [data-locale-key]"))
      el.textContent = window.__padiemLocale.text(el.dataset.localeKey);
    document.documentElement.dataset.theme = """ + json.dumps(theme) + """;
    document.body.dataset.theme = """ + json.dumps(theme) + """;
    </script><script src="/chat-news-module.js"></script>"""
    html = html.replace("</body>", script + "</body>")
    page = browser.new_page(viewport={"width": width, "height": 844},
                            timezone_id="Asia/Seoul")

    def route_request(route):
        url = urlsplit(route.request.url)
        if url.netloc != "chat-news.invalid":
            route.abort()
            return
        name = url.path.lstrip("/")
        if not name:
            route.fulfill(content_type="text/html; charset=utf-8", body=html)
        elif name == "api/chat/news":
            route.fulfill(json={"ok": True, "news": NEWS, "unread_count": 0})
        elif name == "api/chat/news/unread":
            route.fulfill(json={"ok": True, "unread_count": 0})
        elif name in overrides:
            mime = "text/css" if name.endswith(".css") else "application/javascript"
            route.fulfill(content_type=mime + "; charset=utf-8", body=overrides[name])
        elif (STATIC / name).is_file():
            route.fulfill(path=str(STATIC / name))
        else:
            route.abort()

    page.route("**/*", route_request)
    page.goto(ORIGIN)
    page.evaluate("() => window.PadiemNews.open()")
    page.locator("#newsList [data-news-number]").first.wait_for()
    return page


