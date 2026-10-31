"""#4379 4th slice: B66 template-source custody carries no PADIEM byte total.

A finite product-side maximum is neither a platform limit nor a provider limit, so
the former 1 GiB ceiling on an original form file is removed rather than enlarged.
The route still reads the body incrementally, now declaring no total, and the
controls that are real stay enforced: media type, container structure, filename
rules, empty-payload rejection, the metadata/SHA-256 agreement on download and the
no-orphan cleanup. Every guard below fails as soon as a byte total comes back on
this surface under any number.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
MIGRATIONS = ROOT / "migrations"

SOURCE = "b66_template_source.py"
ROUTES = "b66_template_source_routes.py"


def test_the_custody_module_and_route_compare_no_byte_total() -> None:
    for name in (SOURCE, ROUTES):
        text = (APP / name).read_text(encoding="utf-8")
        assert "1024 * 1024 * 1024" not in text, name
        assert not re.search(r">\s*MAX_B66_TEMPLATE_SOURCE_BYTES", text), name
        assert not re.search(r">\s*MAX_TEMPLATE_SOURCE_REQUEST_BYTES", text), name
    assert "MAX_B66_TEMPLATE_SOURCE_BYTES" not in (APP / SOURCE).read_text(encoding="utf-8")
    routes = (APP / ROUTES).read_text(encoding="utf-8")
    assert "MAX_TEMPLATE_SOURCE_REQUEST_BYTES" not in routes
    assert "template_source_request_too_large" not in routes
    # The byte total had its own client-facing refusal; removing the total removes
    # that surface too, while every other rejection message stays.
    assert "원본 양식 파일 크기가 허용 범위를 초과했습니다" not in routes
    assert "_error(413" not in routes


def test_the_route_declares_no_total_to_the_incremental_reader() -> None:
    routes = (APP / ROUTES).read_text(encoding="utf-8")
    assert routes.count("read_bounded_request_body(request, max_bytes=None)") == 1
    assert "RequestBodyTooLarge" not in routes


def test_the_real_custody_controls_are_untouched() -> None:
    # Each marker is pinned with its delimiter so a rename of the guard itself
    # cannot keep satisfying a bare substring.
    source = (APP / SOURCE).read_text(encoding="utf-8")
    routes = (APP / ROUTES).read_text(encoding="utf-8")
    # #4379 removes byte totals, not the empty-payload rule that travelled on the
    # same source line as a total, so each rejection is pinned where it now stands.
    assert source.count("if not body:") == 1
    for marker, count in (
        ("or meta.byte_length < 1", 1),
        ("if reported is not None and reported != metadata.byte_length:", 1),
        ("len(payload) != metadata.byte_length", 1),
        ("hashlib.sha256(payload).hexdigest() != metadata.sha256", 1),
        ("if not _magic_matches(media_type, body):", 1),
        ("if not _structure_matches(media_type, body):", 1),
        ("raise B66TemplateSourceOrphanError(object_key)", 1),
        ("if len(text) > MAX_ORIGINAL_FILENAME_CHARS:", 1),
        ("if not infos:", 1),
    ):
        assert source.count(marker) == count, marker
    for marker in (
        "base64.b64decode(value, validate=True)",
        "if payload is None or not payload:",
    ):
        assert routes.count(marker) == 1, marker
    # #5734 stage 2: the member-count ceiling on the central-directory walk is
    # gone. A package with many parts is a big document; the path, encryption and
    # required-part judgements above are the ones that describe a threat.
    assert "MAX_OOXML_ENTRIES" not in source


def test_the_reader_helper_still_bounds_a_route_that_declares_a_total() -> None:
    helper = (APP / "bounded_request_body.py").read_text(encoding="utf-8")
    assert helper.count('raise ValueError("max_bytes must be a positive integer or None")') == 1
    assert "if max_bytes is not None and len(raw) + len(chunk_bytes) > max_bytes:" in helper
    assert 'async def open_bounded_spooled_request(request: Any, *, max_bytes: int' in helper


def test_the_ceiling_is_released_only_by_a_forward_migration_that_keeps_the_floor() -> None:
    # #4379: the D1 schema CHECK was the last PADIEM byte total on this surface.
    # The released migrations keep their own text; one forward rebuild carries
    # every row across and keeps the non-empty rule instead of dropping it with
    # the ceiling.
    released = (MIGRATIONS / "027_b66_template_source.sql").read_text(encoding="utf-8")
    assert "byte_length >= 1 AND byte_length <= 10485760" in released

    forward = (MIGRATIONS / "060_byte_length_capacity_ceiling_release.sql").read_text(encoding="utf-8")
    assert "10485760" not in forward
    assert forward.count("byte_length INTEGER NOT NULL CHECK (byte_length > 0)") == 1
    assert forward.count("byte_length INTEGER NOT NULL CHECK (byte_length >= 1)") == 1
    assert forward.count("size_bytes INTEGER NOT NULL CHECK (size_bytes > 0)") == 1
    for table in ("claw_document_metadata", "claw_conversation_artifact_index", "b66_template_source"):
        # Copy before drop: an absent or unreadable source aborts the rebuild
        # before any table is destroyed.
        assert forward.index(f"INSERT INTO {table}_next") < forward.index(f"DROP TABLE {table};")
        assert f"ALTER TABLE {table}_next RENAME TO {table};" in forward
    for index in (
        "idx_claw_document_metadata_tenant_active",
        "idx_claw_conversation_artifact_owner",
        "idx_b66_template_source_owner_workspace_status",
    ):
        assert f"CREATE INDEX IF NOT EXISTS {index}" in forward
    # The released migrations are not rewritten by the forward migration.
    for name in ("008_claw_document_metadata.sql", "026_claw_conversation_artifact_index.sql"):
        assert "10485760" in (MIGRATIONS / name).read_text(encoding="utf-8"), name


def test_the_quote_asset_ceiling_is_released_on_both_sides_at_once() -> None:
    # CENTRAL assigned the B66 quote asset ceiling to this lane. Releasing one
    # side alone would turn a clean 400 into a database failure, so the app
    # total and the D1 CHECK have to move together.
    quote_assets = (APP / "b66_quote_assets.py").read_text(encoding="utf-8")
    assert "MAX_B66_QUOTE_ASSET_BYTES" not in quote_assets
    assert not re.search(r"len\(body\)\s*>\s*MAX_B66_QUOTE_ASSET_BYTES", quote_assets)
    assert not re.search(r"byte_length\s*>\s*MAX_B66_QUOTE_ASSET_BYTES", quote_assets)
    # The real controls stay: the empty body, the media-type magic, the
    # non-empty metadata rule and the approved status.
    assert quote_assets.count("if not body:") == 1
    assert quote_assets.count("if not _magic_matches(media_type, body):") == 1
    assert quote_assets.count("or meta.byte_length < 1") == 1
    assert quote_assets.count('or meta.status != "approved"') == 1

    released = (MIGRATIONS / "022_b66_quote_asset.sql").read_text(encoding="utf-8")
    assert "byte_length >= 1 AND byte_length <= 262144" in released

    forward = (
        MIGRATIONS / "061_b66_quote_asset_byte_length_ceiling_release.sql"
    ).read_text(encoding="utf-8")
    assert "262144" not in forward
    assert forward.count("byte_length INTEGER NOT NULL CHECK (byte_length >= 1)") == 1
    # Copy before drop: an absent or unreadable source aborts the rebuild
    # before any table is destroyed.
    assert forward.index("INSERT INTO b66_quote_asset_next") < forward.index(
        "DROP TABLE b66_quote_asset;"
    )
    assert "ALTER TABLE b66_quote_asset_next RENAME TO b66_quote_asset;" in forward
    assert "CREATE INDEX IF NOT EXISTS idx_b66_quote_asset_owner_workspace_status" in forward
    # The released migration is not rewritten by the forward migration.
    assert "262144" in released
