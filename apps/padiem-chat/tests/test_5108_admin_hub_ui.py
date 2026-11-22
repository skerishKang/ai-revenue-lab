"""#5108 /admin hub contract: reuse the signed session, never add a second login."""
import subprocess
import sys
from pathlib import Path

# #8060: 원문 읽기는 _support(admin_hub_source)가 담당하고 시험은 토큰·계산 값으로
# 단언한다.
from _support.admin_hub_source import has, lacks, source, tokens  # noqa: E402

BASE = Path(__file__).resolve().parents[1] / "static"
REPO = Path(__file__).resolve().parents[3]
B66 = REPO / "reference" / "business-66-padiem-quote-v1"
PRODUCTS = ("b14", "chat", "claw", "b66")


def test_hub_reuses_the_signed_session_without_a_login_surface():
    html_path = BASE / "admin.html"
    js_path = BASE / "admin.js"
    js_tokens = tokens(js_path)
    assert "/api/admin/session" in js_tokens
    assert has(js_path, 'credentials: "same-origin"')
    # Operations forms are allowed behind the signed-session gate. The
    # login-specific URLs and password fields must still be absent.
    for forbidden in (
        "/api/auth/password/login",
        "/api/auth/password/register",
        "/auth/google/start",
        'type="password"',
    ):
        assert lacks(html_path, forbidden)
        assert lacks(js_path, forbidden)
    for link in ("./admin-models", "./admin/chat", "./admin/claw", "./admin/b66"):
        assert link in js_tokens


def test_hub_menus_follow_server_capabilities_only():
    js_path = BASE / "admin.js"
    js_tokens = tokens(js_path)
    for capability in (
        "admin_hub",
        "role_management",
        "chat_admin",
        "claw_admin",
        "central_model_admin",
        "b66_platform_admin",
        "b66_customer_admin",
    ):
        assert capability in js_tokens
    assert has(js_path, 'data.authenticated !== true || !role')
    for fragment in (
        "caps.central_model_admin", "caps.chat_admin", "caps.claw_admin",
        "caps.b66_platform_admin", "caps.b66_customer_admin",
    ):
        assert has(js_path, fragment)
    assert "textContent" in js_tokens
    assert "innerHTML" not in js_tokens
    # The hub is a navigation surface; it never mutates roles or models.
    for write_path in ("/api/admin/roles", "/api/admin/models/", "/api/b66/admin/"):
        assert write_path not in js_tokens


def test_product_pages_reuse_existing_admin_surfaces_and_return_to_the_hub():
    shared_path = BASE / "admin-product.js"
    shared_tokens = tokens(shared_path)
    assert "/api/admin/session" in shared_tokens
    for write_path in (
        "/api/admin/models/preview",
        "/api/admin/models/change-apply",
        "/api/admin/models/route-apply",
    ):
        assert write_path not in shared_tokens
    for product in PRODUCTS:
        page_path = BASE / "admin" / f"{product}.html"
        assert has(page_path, f'data-product="{product}"')
        assert has(page_path, 'href="/admin"')
        assert has(page_path, 'href="/admin-models"')
        assert "/admin-product.js" in tokens(page_path)
        assert lacks(page_path, 'type="password"')
    # B14 management is the existing /admin-models page, reached by redirect.
    assert has(shared_path, 'redirect: "/admin-models"')
    assert "/admin-models#routeEditorHeading" in shared_tokens
    assert "B66_ADMIN_ORIGIN" in shared_tokens
    assert "b66_platform_admin" in shared_tokens
    assert "b66_customer_admin" in shared_tokens


def test_entry_and_return_links_are_wired_to_existing_screens():
    assert has(BASE / "admin-models.html", 'href="./admin"')

    shell_path = BASE / "index.html"
    assert has(shell_path, 'id="adminHubLink"')
    assert has(shell_path, 'href="./admin"')
    assert has(shell_path, 'src="./admin-entry.js"')
    entry_path = BASE / "admin-entry.js"
    entry_tokens = tokens(entry_path)
    assert "/api/admin/session" in entry_tokens
    assert "padiem:auth-state" in entry_tokens
    assert has(entry_path, "data.authenticated === true")
    assert has(entry_path, "link.hidden = !authorized")

    for page_name in (
        "admin.html",
        "admin-models.html",
        "admin-notices.html",
        "admin-inquiries.html",
        "admin-saved-skill-candidates.html",
        "admin-member.html",
    ):
        assert has(B66 / page_name, 'href="https://chat.padiem.net/admin"'), page_name


def test_admin_pretty_urls_map_to_workers_assets_files():
    assert (BASE / "admin.html").is_file()
    for product in PRODUCTS:
        assert (BASE / "admin" / f"{product}.html").is_file()
    wrangler_path = REPO / "apps" / "padiem-chat" / "wrangler.toml"
    assert has(wrangler_path, "[assets]")
    # Assets are uploaded from the generated bundle, which is a byte-verified copy
    # of these same files plus the staged app entries (wrangler.toml [assets]).
    assert has(wrangler_path, 'directory = ".b66-worker-src/static"')


def test_b66_navigation_origin_is_single_sourced_and_passes_the_origin_audit():
    assert "https://quick-quote-kr.pages.dev" in tokens(BASE / "admin-config.js")
    for name in ("admin.html", "admin.js", "admin-product.js", "admin/b66.html"):
        assert "quick-quote-kr.pages.dev" not in tokens(BASE / name), name
    completed = subprocess.run(
        [sys.executable, str(REPO / ".github" / "scripts" / "b62_static_origin_audit.py")],
        cwd=REPO,
        capture_output=True,
        text=True, encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_license_navigation_is_exact_url_and_file_scoped():
    import importlib.util

    path = REPO / ".github" / "scripts" / "b62_static_origin_audit.py"
    spec = importlib.util.spec_from_file_location("static_origin_audit", path)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    notice = "apps/padiem-chat/static/third-party-licenses.html"
    allowed = {
        "https://github.com/NousResearch/hermes-agent/blob/9a76ac8e4f612c081e12008923893077f10f2ec7/tools/tool_output_truncate.py",
        "https://github.com/pymupdf/PyMuPDF",
        "https://github.com/skerishKang/ai-revenue-lab/tree/main/apps/b66-pdf-renderer",
        "https://www.gnu.org/licenses/agpl-3.0.html",
        "https://github.com/anomalyco/opencode",
        "https://github.com/microsoft/playwright-mcp",
        "https://github.com/microsoft/playwright",
        "https://www.apache.org/licenses/LICENSE-2.0",
    }
    assert audit.LICENSE_NOTICE_URLS == allowed
    for url in allowed:
        assert audit.license_notice_url_allowed(notice, url)
        assert not audit.license_notice_url_allowed(
            "apps/padiem-chat/static/index.html", url)
    for url in ("https://github.com/unreviewed/repo",
                "https://github.com/NousResearch/hermes-agent?tracking=1",
                "https://github.com/NousResearch/hermes-agent",
                "https://github.com/pymupdf/PyMuPDF?tracking=1",
                "https://www.gnu.org/other",
                "https://github.com/anomalyco/opencode?tracking=1"):
        assert not audit.license_notice_url_allowed(notice, url)
    assert "github.com" not in audit.ALLOWED_LITERAL_HTTP_HOSTS
    assert "www.gnu.org" not in audit.ALLOWED_LITERAL_HTTP_HOSTS


def test_tutorial_media_origins_are_exact_scene_scoped_urls():
    import importlib.util

    path = REPO / ".github" / "scripts" / "b62_static_origin_audit.py"
    spec = importlib.util.spec_from_file_location("static_origin_audit_media", path)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)

    expected = {
        "apps/padiem-chat/static/help-tutorials/01-first-visit.html": {
            "https://tutorial-media.padiem.net/tutorials/01-first-visit/video.v20261103.webm",
            "https://tutorial-media.padiem.net/tutorials/01-first-visit/captions.v20261103.vtt",
        },
        "apps/padiem-chat/static/help-tutorials/02-pc-connection.html": {
            "https://tutorial-media.padiem.net/tutorials/02-pc-connection/video.v20261103.webm",
            "https://tutorial-media.padiem.net/tutorials/02-pc-connection/captions.v20261103.vtt",
        },
        # #6786: the 03/05/07 scenes recorded in the same versioned R2 path.
        "apps/padiem-chat/static/help-tutorials/03-document-work.html": {
            "https://tutorial-media.padiem.net/tutorials/03-document-work/video.v20261103.webm",
            "https://tutorial-media.padiem.net/tutorials/03-document-work/captions.v20261103.vtt",
        },
        "apps/padiem-chat/static/help-tutorials/04-bookai.html": {
            "https://tutorial-media.padiem.net/tutorials/04-bookai/video.v20261103.webm",
            "https://tutorial-media.padiem.net/tutorials/04-bookai/captions.v20261103.vtt",
        },
        "apps/padiem-chat/static/help-tutorials/05-account-deletion.html": {
            "https://tutorial-media.padiem.net/tutorials/05-account-deletion/video.v20261103.webm",
            "https://tutorial-media.padiem.net/tutorials/05-account-deletion/captions.v20261103.vtt",
        },
        "apps/padiem-chat/static/help-tutorials/07-external-ai-connect.html": {
            "https://tutorial-media.padiem.net/tutorials/07-external-ai-connect/video.v20261103.webm",
            "https://tutorial-media.padiem.net/tutorials/07-external-ai-connect/captions.v20261103.vtt",
        },
    }
    assert audit.TUTORIAL_MEDIA_URLS == {
        relative: frozenset(urls) for relative, urls in expected.items()
    }
    assert "tutorial-media.padiem.net" not in audit.ALLOWED_LITERAL_HTTP_HOSTS
    assert "media.padiem.net" not in audit.ALLOWED_LITERAL_HTTP_HOSTS

    for relative, urls in expected.items():
        for url in urls:
            assert audit.tutorial_media_url_allowed(relative, url)
            assert not audit.tutorial_media_url_allowed(
                "apps/padiem-chat/static/index.html", url
            )

    first_visit = "apps/padiem-chat/static/help-tutorials/01-first-visit.html"
    for url in (
        "https://tutorial-media.padiem.net/tutorials/01-first-visit/video.webm",
        "https://tutorial-media.padiem.net/tutorials/01-first-visit/video.v20261104.webm",
        "https://tutorial-media.padiem.net/tutorials/02-pc-connection/video.v20261103.webm",
        "https://tutorial-media.padiem.net/tutorials/01-first-visit/video.v20261103.webm?download=1",
        "https://tutorial-media.padiem.net.evil.invalid/tutorials/01-first-visit/video.v20261103.webm",
        "https://media.padiem.net/tutorials/01-first-visit/video.v20261103.webm",
    ):
        assert not audit.tutorial_media_url_allowed(first_visit, url)
