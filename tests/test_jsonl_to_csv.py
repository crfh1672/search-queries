import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skill" / "search-queries-dataset-builder"
sys.path.insert(0, str(SCRIPT_DIR))
import jsonl_to_csv


def record(identifier="book-001"):
    return {
        "id": identifier,
        "query": "query",
        "type": "short",
        "correct_ref": "פתיחת הספר",
        "correct_quote": "correct quote",
        "correct_line": "1",
        "near_miss_ref": "פתיחת הספר",
        "near_miss_quote": "near miss",
        "near_miss_line": "3",
        "near_miss_same_section": "כן",
        "split": "train",
        "verified_by_human": "",
    }


class JsonlToCsvTests(unittest.TestCase):
    def test_valid_record_converts_to_schema_ordered_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "book.jsonl"
            destination = root / "book.csv"
            source.write_text(json.dumps(record(), ensure_ascii=False) + "\n", encoding="utf-8")

            result = jsonl_to_csv.main(["jsonl_to_csv.py", str(source), str(destination)])

            self.assertEqual(result, 0)
            with destination.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(list(rows[0]), jsonl_to_csv.FIELDS)
            self.assertEqual(rows[0]["id"], "book-001")

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "book.jsonl"
            source.write_text('{"id":"one","id":"two"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                jsonl_to_csv.load_records(source)

    def test_overlapping_correct_and_near_miss_ranges_are_rejected(self):
        row = record()
        row["near_miss_line"] = "1-4"
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "book.jsonl"
            source.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ranges overlap"):
                jsonl_to_csv.load_records(source)

    def test_symlinked_output_is_not_written_through(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "book.jsonl"
            source.write_text(json.dumps(record(), ensure_ascii=False) + "\n", encoding="utf-8")
            outside = root / "outside.csv"
            outside.write_text("do not modify", encoding="utf-8")
            link = root / "book.csv"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"file symlink is unavailable: {exc}")

            result = jsonl_to_csv.main(["jsonl_to_csv.py", str(source), str(link)])

            self.assertEqual(result, 1)
            self.assertEqual(outside.read_text(encoding="utf-8"), "do not modify")

    def test_same_input_and_output_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "book.jsonl"
            path.write_text(json.dumps(record(), ensure_ascii=False) + "\n", encoding="utf-8")
            original = path.read_bytes()
            result = jsonl_to_csv.main(["jsonl_to_csv.py", str(path), str(path)])
            self.assertEqual(result, 2)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
