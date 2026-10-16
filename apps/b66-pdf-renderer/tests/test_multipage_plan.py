"""Offline, asset-free acceptance matrix for #3839's page-plan contract."""
import importlib.util
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "multipage_plan.py"
spec = importlib.util.spec_from_file_location("b66_multipage_plan_test_target", SOURCE)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)

CertifiedGeometry = module.CertifiedGeometry
PagePlanError = module.PagePlanError
plan_pages = module.plan_pages


def geometry(**changes):
    base = dict(
        page_width_pt=595, page_height_pt=842,
        first_rows_top_pt=345, continuation_rows_top_pt=150,
        rows_bottom_pt=700, final_section_height_pt=120,
        name_column_width_pt=180, line_height_pt=12,
        row_vertical_padding_pt=3, minimum_row_height_pt=22,
    )
    base.update(changes)
    return CertifiedGeometry(**base)


def rows(count, name="품목"):
    return [{"name": f"{name} {i+1}", "qty": i+1, "unitPrice": 1000+i}
            for i in range(count)]


def measure(text):
    return len(text) * 4


class MultipagePlanning(unittest.TestCase):
    def plan(self, records, *, g=None, size=4096):
        return plan_pages(records, geometry=g or geometry(),
                          measure_name_pt=measure, content_bytes=size)

    def assert_exact(self, count, *, name="품목"):
        records = rows(count, name=name)
        before = [dict(item) for item in records]
        pages = self.plan(records)
        actual = [placed.source_index for page in pages for placed in page.rows]
        self.assertEqual(actual, list(range(count)))
        self.assertEqual([p.printed_number for page in pages for p in page.rows],
                         list(range(1, count+1)))
        self.assertEqual(records, before, "the planner must not mutate QuoteCore rows")
        self.assertEqual([page.number for page in pages], list(range(1, len(pages)+1)))
        self.assertTrue(all(page.total_pages == len(pages) for page in pages))
        self.assertEqual([page.show_totals_and_terms for page in pages],
                         [False]*(len(pages)-1)+[True])
        self.assertTrue(pages[0].first_page)
        self.assertTrue(all(not p.first_page for p in pages[1:]))
        for page in pages:
            top = 345 if page.first_page else 150
            limit = 580 if page.show_totals_and_terms and page.first_page else (
                580 if page.show_totals_and_terms else 700)
            for placed in page.rows:
                self.assertGreaterEqual(placed.top_pt, top)
                self.assertLessEqual(placed.top_pt + placed.height_pt, limit + 1e-6)
        return pages

    def test_all_requested_item_counts(self):
        for n in (1, 2, 3, 4, 10, 25, 100, 101, 125, 500):
            with self.subTest(n=n):
                page_set = self.assert_exact(n)
                if n >= 25:
                    self.assertGreater(len(page_set), 1)

    def test_wrapping_never_drops_a_character(self):
        long_name = "특수한공사항목" * 45
        pages = self.assert_exact(101, name=long_name)
        for page in pages:
            for placement in page.rows:
                self.assertEqual("".join(placement.wrapped_name),
                                 f"{long_name} {placement.source_index + 1}")
                self.assertTrue(all(measure(s) <= 180 for s in placement.wrapped_name))

    def test_hard_line_break_is_preserved(self):
        doc = [{"name": "복합 공사\n검수 내용\n추가 내역"}]
        pages = self.plan(doc)
        placed = pages[0].rows[0]
        self.assertEqual("".join(("\n" if hard else "") + line
                                 for line, hard in zip(placed.wrapped_name, placed.hard_break_before)),
                         doc[0]["name"])

    def test_exact_row_boundary_and_one_past(self):
        g = geometry(first_rows_top_pt=480, continuation_rows_top_pt=480,
                     rows_bottom_pt=680, final_section_height_pt=100)
        # Two 22pt rows fit in the 100pt final budget; 5 fit, 6 exceed.
        self.assertEqual(len(self.plan(rows(4), g=g)), 1)
        pages = self.plan(rows(5), g=g)
        self.assertEqual(len(pages), 2)
        self.assertEqual([len(p.rows) for p in pages], [4, 1])

    def test_large_single_row_is_not_clipped(self):
        with self.assertRaisesRegex(PagePlanError, "row_exceeds_page"):
            self.plan(rows(1, name="긴품목"*600))

    def test_resource_bounded_by_bytes_not_item_count(self):
        self.assert_exact(101)
        with self.assertRaisesRegex(PagePlanError, "request_too_large"):
            self.plan(rows(101), size=1024*1024+1)
        with self.assertRaisesRegex(PagePlanError, "request_too_large"):
            self.plan(rows(101), size=0)

    def test_unrenderable_glyph_fails_closed(self):
        with self.assertRaisesRegex(PagePlanError, "unrenderable_glyph"):
            plan_pages(rows(1), geometry=geometry(name_column_width_pt=1),
                       measure_name_pt=measure, content_bytes=100)

    def test_geometry_is_not_inferred_from_customer_request(self):
        with self.assertRaisesRegex(PagePlanError, "invalid_certified_geometry"):
            geometry(page_width_pt=700)
        with self.assertRaisesRegex(PagePlanError, "invalid_certified_geometry"):
            geometry(final_section_height_pt=400)

    def test_bad_measure_fails_closed(self):
        with self.assertRaisesRegex(PagePlanError, "invalid_text_measure"):
            plan_pages(rows(1), geometry=geometry(), measure_name_pt=lambda _: float("nan"),
                       content_bytes=50)

    def test_empty_and_nonstring_rejected(self):
        for payload in ([], [{"name": None}], [{"name": "bad\x01name"}]):
            with self.subTest(payload=payload):
                with self.assertRaises(PagePlanError):
                    self.plan(payload)


if __name__ == "__main__":
    unittest.main()
