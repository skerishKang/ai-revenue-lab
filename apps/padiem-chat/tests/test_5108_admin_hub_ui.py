"""#5108 /admin hub contract: reuse the signed session, never add a second login."""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "static"
REPO = Path(__file__).resolve().parents[3]
B66 = REPO / "reference" / "business-66-padiem-quote-v1"
PRODUCTS = ("b14", "chat", "claw", "b66")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_hub_reuses_the_signed_session_without_a_login_surface():
    html = read(BASE / "admin.html")
    js = read(BASE / "admin.js")
    assert "/api/admin/session" in js
    assert "credentials: \"same-origin\"" in js
    for forbidden in (
        "/api/auth/password/login",
        "/api/auth/password/register",
        "/auth/google/start",
        'type="password"',
        "<form",
    ):
        assert forbidden not in html
        assert forbidden not in js
    for link in ("./admin-models", "./admin/chat", "./admin/claw", "./admin/b66"):
        assert link in js


def test_hub_menus_follow_server_capabilities_only():
    js = read(BASE / "admin.js")
    for capability in (
        "admin_hub",
        "role_management",
        "chat_admin",
        "claw_admin",
        "central_model_admin",
        "b66_platform_admin",
        "b66_customer_admin",
    ):
        assert capability in js
    assert 'data.authenticated !== true || !role' in js
    assert "caps.central_model_admin" in js
    assert "caps.chat_admin" in js
    assert "caps.claw_admin" in js
    assert "caps.b66_platform_admin" in js
    assert "caps.b66_customer_admin" in js
    assert "textContent" in js
    assert "innerHTML" not in js
    # The hub is a navigation surface; it never mutates roles or models.
    for write_path in ("/api/admin/roles", "/api/admin/models/", "/api/b66/admin/"):
        assert write_path not in js


def test_product_pages_reuse_existing_admin_surfaces_and_return_to_the_hub():
    shared = read(BASE / "admin-product.js")
    assert "/api/admin/session" in shared
    for write_path in (
        "/api/admin/models/preview",
        "/api/admin/models/change-apply",
        "/api/admin/models/route-apply",
    ):
        assert write_path not in shared
    for product in PRODUCTS:
        page = read(BASE / "admin" / f"{product}.html")
        assert f'data-product="{product}"' in page
        assert 'href="/admin"' in page
        assert 'href="/admin-models"' in page
        assert "/admin-product.js" in page
        assert 'type="password"' not in page
    # B14 management is the existing /admin-models page, reached by redirect.
    assert 'redirect: "/admin-models"' in shared
    assert "/admin-models#routeEditorHeading" in shared
    assert "B66_ADMIN_ORIGIN" in shared
    assert "b66_platform_admin" in shared
    assert "b66_customer_admin" in shared


def test_entry_and_return_links_are_wired_to_existing_screens():
    models_html = read(BASE / "admin-models.html")
    assert 'href="./admin"' in models_html

    shell = read(BASE / "index.html")
    assert 'id="adminHubLink"' in shell
    assert 'href="./admin"' in shell
    assert 'src="./admin-entry.js"' in shell
    entry = read(BASE / "admin-entry.js")
    assert '"/api/admin/session"' in entry
    assert "padiem:auth-state" in entry
    assert "data.authenticated === true" in entry
    assert "link.hidden = !authorized" in entry

    for page_name in (
        "admin.html",
        "admin-models.html",
        "admin-notices.html",
        "admin-inquiries.html",
        "admin-saved-skill-candidates.html",
        "admin-member.html",
    ):
        page = read(B66 / page_name)
        assert 'href="https://chat.padiem.net/admin"' in page, page_name


def test_admin_pretty_urls_map_to_workers_assets_files():
    assert (BASE / "admin.html").is_file()
    for product in PRODUCTS:
        assert (BASE / "admin" / f"{product}.html").is_file()
    wrangler = read(REPO / "apps" / "padiem-chat" / "wrangler.toml")
    assert "[assets]" in wrangler
    # Assets are uploaded from the generated bundle, which is a byte-verified copy
    # of these same files plus the staged app entries (wrangler.toml [assets]).
    assert 'directory = ".b66-worker-src/static"' in wrangler


def test_b66_navigation_origin_is_single_sourced_and_passes_the_origin_audit():
    config = read(BASE / "admin-config.js")
    assert "https://quick-quote-kr.pages.dev" in config
    for name in ("admin.html", "admin.js", "admin-product.js", "admin/b66.html"):
        assert "quick-quote-kr.pages.dev" not in read(BASE / name), name
    completed = subprocess.run(
        [sys.executable, str(REPO / ".github" / "scripts" / "b62_static_origin_audit.py")],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
