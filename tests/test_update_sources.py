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
        old = ["header", "quote", "other"]
        new = ["header", "quote", "new", "quote"]
        with self.assertRaises(update_sources.UpdateProblem):
            update_sources.locate_quote(old, new, "quote", (2, 2), {})


if __name__ == "__main__":
    unittest.main()
