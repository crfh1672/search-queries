import os
import sys
import types
import unittest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
sys.path.insert(0, os.path.abspath(TOOLS))
try:
    import library  # noqa
except ModuleNotFoundError:
    fake = types.ModuleType("library")
    fake.norm = lambda s: " ".join(s.split())
    fake.fetch = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network disabled"))
    fake.get_pinned = lambda *a, **k: (None, "network disabled")
    sys.modules["library"] = fake
import update_sources


class MappingTests(unittest.TestCase):
    def test_inserted_line_moves_quote(self):
        old = ["header", "important text", "end"]
        new = ["header", "new line", "important text", "end"]
        mapping = update_sources.line_map(old, new)
        self.assertEqual(
            update_sources.locate_quote(old, new, "important text", (2, 2), mapping),
            (3, 3),
        )

    def test_unique_quote_after_edit(self):
        old = ["header", "before unique phrase after"]
        new = ["header", "added: before unique phrase after"]
        mapping = update_sources.line_map(old, new)
        self.assertEqual(
            update_sources.locate_quote(old, new, "unique phrase", (2, 2), mapping),
            (2, 2),
        )

    def test_changed_quote_requires_review(self):
        old = ["header", "old wording"]
        new = ["header", "new wording"]
        mapping = update_sources.line_map(old, new)
        with self.assertRaises(update_sources.UpdateProblem):
            update_sources.locate_quote(old, new, "old wording", (2, 2), mapping)

    def test_ambiguous_quote_requires_review(self):
        old = ["header", "the unique phrase", "other"]
        # The quote appears as a substring on two changed lines, while the
        # original line no longer maps exactly to either line.
        new = ["header", "x unique phrase", "another unique phrase"]
        mapping = update_sources.line_map(old, new)
        with self.assertRaises(update_sources.UpdateProblem):
            update_sources.locate_quote(
                old, new, "unique phrase", (2, 2), mapping
            )

    def test_overlapping_mapped_citations_require_review(self):
        row = {"correct_line": "12", "near_miss_line": "12"}
        with self.assertRaises(update_sources.UpdateProblem):
            update_sources.ensure_citations_do_not_overlap(row)

    def test_separate_mapped_citations_are_allowed(self):
        row = {"correct_line": "12", "near_miss_line": "13"}
        update_sources.ensure_citations_do_not_overlap(row)

    def test_hebrew_numeral_punctuation_is_normalized(self):
        lines = ["כותרת", "דף י״א.", "קטע", "דף י״א:", "עוד"]
        self.assertEqual(
            update_sources.reference_for_line(lines, 3, "בדיקה"),
            'בדיקה יא ע"א',
        )
        self.assertEqual(
            update_sources.reference_for_line(lines, 5, "בדיקה"),
            'בדיקה יא ע"ב',
        )


if __name__ == "__main__":
    unittest.main()
