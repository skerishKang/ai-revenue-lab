"""Tests for recursive unsafe markup rejection."""

import pytest

from app.pipeline.errors import UnsafeMarkupError
from app.pipeline.markup import check_payload, check_string


class TestCheckString:
    def test_plain_text_passes(self):
        check_string("This is safe text.", field_name="opening")

    def test_raw_html_tag_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="raw HTML tag"):
            check_string("Hello <script>alert('xss')</script>", field_name="opening")

    def test_self_closing_tag_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="raw HTML tag"):
            check_string("<br/>", field_name="deck")

    def test_event_handler_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="event handler"):
            check_string("Click here onmouseover=alert(1)", field_name="opening")

    def test_javascript_url_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="event handler"):
            check_string("javascript:alert(1)", field_name="deck")

    def test_vbscript_url_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="event handler"):
            check_string("vbscript:msgbox(1)", field_name="title")

    def test_data_text_html_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="unsafe markup"):
            check_string("data:text/html,<script>alert(1)</script>", field_name="deck")

    def test_mailto_url_passes(self):
        check_string("mailto:user@example.com", field_name="deck")

    def test_https_url_passes(self):
        check_string("https://example.com", field_name="continuity_note")

    def test_opening_tag_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="raw HTML tag"):
            check_string("Some <b>bold</b> text", field_name="opening")

    def test_closing_tag_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="raw HTML tag"):
            check_string("</div>", field_name="deck")

    def test_iframe_tag_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="raw HTML tag"):
            check_string("<iframe src='http://evil.com'>", field_name="opening")

    def test_onclick_attribute_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="event handler"):
            check_string("button onclick='doEvil()'", field_name="title")


class TestCheckPayload:
    def test_simple_string_payload_passes(self):
        check_payload("plain text")

    def test_simple_dict_passes(self):
        check_payload({"opening": "safe text", "title": "also safe"})

    def test_nested_dict_with_unsafe_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="raw HTML tag"):
            check_payload({"opening": "safe", "sections": [{"title": "<script>evil</script>"}]})

    def test_list_of_strings_with_unsafe_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="raw HTML tag"):
            check_payload(["safe", "<script>evil</script>"])

    def test_deeply_nested_unsafe_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="event handler"):
            check_payload(
                {
                    "level1": {
                        "level2": [
                            {"level3": "onclick=evil()"},
                        ]
                    }
                }
            )

    def test_numbers_bools_none_ignored(self):
        check_payload(
            {
                "count": 42,
                "active": True,
                "metadata": None,
                "rate": 3.14,
                "items": [1, 2, 3],
            }
        )

    def test_empty_payload_passes(self):
        check_payload({})
        check_payload([])
        check_payload("")

    def test_mixed_safe_and_unsafe_rejected(self):
        with pytest.raises(UnsafeMarkupError, match="raw HTML tag"):
            check_payload(
                {
                    "safe_field": "just text",
                    "unsafe_field": "<script>alert(1)</script>",
                }
            )
