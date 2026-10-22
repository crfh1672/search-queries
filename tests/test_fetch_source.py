import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
sys.path.insert(0, os.path.abspath(TOOLS))
import fetch_source


class DatasetPathSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.original_root = fetch_source.REPO_ROOT
        fetch_source.REPO_ROOT = self.root

    def tearDown(self):
        fetch_source.REPO_ROOT = self.original_root
        self.temp.cleanup()

    def test_resolve_dataset_rejects_symlinked_book_directory(self):
        category = self.root / "datasets" / "הלכה"
        category.mkdir(parents=True)
        outside = self.root.parent / (self.root.name + "-outside")
        outside.mkdir()
        link = category / "ספר"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlink is unavailable: {exc}")
        with self.assertRaisesRegex(SystemExit, "symlink או junction"):
            fetch_source.resolve_dataset("datasets/הלכה/ספר")

    def test_resolve_dataset_rejects_symlinked_metadata_file(self):
        book = self.root / "datasets" / "הלכה" / "ספר"
        book.mkdir(parents=True)
        outside = self.root.parent / (self.root.name + "-metadata.json")
        outside.write_text('{"book_name":"ספר"}', encoding="utf-8")
        try:
            (book / "ספר.מקור.json").symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"file symlink is unavailable: {exc}")
        with self.assertRaisesRegex(SystemExit, "symlink או junction"):
            fetch_source.resolve_dataset("datasets/הלכה/ספר")


class SourceDiffTests(unittest.TestCase):
    def test_heading_only_change_is_reported(self):
        old = b"<h1>Book</h1>\nbody text\n"
        new = b"<h2>Book</h2>\nbody text\n"
        old_lines, new_lines, diff = fetch_source.compare_source_lines(old, new)
        self.assertEqual(old_lines, new_lines)
        self.assertIn(1, diff)
        self.assertIn(2, diff)

    def test_removed_tail_line_is_reported(self):
        old_lines, new_lines, diff = fetch_source.compare_source_lines(
            b"first line\nremoved tail\n", b"first line\n"
        )
        self.assertEqual(len(old_lines), 3)
        self.assertEqual(len(new_lines), 2)
        self.assertIn(3, diff)

    def test_text_only_change_is_reported(self):
        _, _, diff = fetch_source.compare_source_lines(
            b"<h2>Chapter</h2>\nold text\n",
            b"<h2>Chapter</h2>\nnew text\n",
        )
        self.assertIn(2, diff)

    def test_unrelated_later_section_keeps_stable_identity(self):
        _, _, diff = fetch_source.compare_source_lines(
            b"<h2>A</h2>\nfirst\nsecond\n<h2>B</h2>\nbody\n",
            b"<h2>A</h2>\nfirst\n<h3>Child</h3>\n<h2>B</h2>\nbody\n",
        )
        self.assertEqual(diff, [3])

    def test_malformed_heading_fails_with_value_error(self):
        with self.assertRaisesRegex(ValueError, "malformed heading"):
            fetch_source.compare_source_lines(
                b"<h2>Chapter</h2>\ntext\n",
                b"<h2>Chapter</h2>\n<h3></h3>\n",
            )

    def test_touched_query_loader_checks_ranges_and_returns_matching_ids(self):
        row = {field: "value" for field in fetch_source.validate.FIELDS}
        row["id"] = "book-001"
        row["correct_line"] = "2-3"
        row["near_miss_line"] = "8"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "book.jsonl"
            path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            self.assertEqual(fetch_source.touched_query_ids(path, [3]), {"book-001"})
            self.assertEqual(fetch_source.touched_query_ids(path, [6]), set())

    def test_touched_query_loader_rejects_invalid_ranges(self):
        row = {field: "value" for field in fetch_source.validate.FIELDS}
        row["id"] = "book-001"
        row["correct_line"] = "5-2"
        row["near_miss_line"] = "8"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "book.jsonl"
            path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "invalid line range"):
                fetch_source.touched_query_ids(path, [5])


if __name__ == "__main__":
    unittest.main()
