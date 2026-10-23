import csv
import json
import os
import stat
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
            self.assertEqual(rows, [record()])

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "book.jsonl"
            source.write_text('{"id":"one","id":"two"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                jsonl_to_csv.load_records(source)

    def write_one(self, root, row):
        source = Path(root) / "book.jsonl"
        source.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        return source

    def test_no_flag_with_identical_refs_is_accepted_for_sibling_sections(self):
        row = record()
        row["near_miss_same_section"] = "לא"  # same title, different sibling sections
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(len(jsonl_to_csv.load_records(self.write_one(temp, row))), 1)

    def test_yes_flag_with_different_refs_is_rejected(self):
        row = record()
        row["near_miss_ref"] = "פרק אחר"
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "same_section|section"):
                jsonl_to_csv.load_records(self.write_one(temp, row))

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

    def test_oversized_line_range_has_record_context(self):
        with self.assertRaisesRegex(ValueError, r"book.jsonl:7: invalid correct_line range"):
            jsonl_to_csv.parse_line_range("9" * 5000, Path("book.jsonl"), 7, "correct_line")

    def test_new_csv_uses_normal_umask_permissions(self):
        if os.name == "nt":
            self.skipTest("POSIX permission bits are not portable to Windows")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "book.jsonl"
            destination = root / "book.csv"
            source.write_text(json.dumps(record(), ensure_ascii=False) + "\n", encoding="utf-8")
            previous_umask = os.umask(0o027)
            try:
                result = jsonl_to_csv.main(["jsonl_to_csv.py", str(source), str(destination)])
            finally:
                os.umask(previous_umask)
            self.assertEqual(result, 0)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o640)

    def test_existing_csv_mode_is_preserved(self):
        if os.name == "nt":
            self.skipTest("POSIX permission bits are not portable to Windows")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "book.jsonl"
            destination = root / "book.csv"
            source.write_text(json.dumps(record(), ensure_ascii=False) + "\n", encoding="utf-8")
            destination.write_text("old", encoding="utf-8")
            destination.chmod(0o640)
            result = jsonl_to_csv.main(["jsonl_to_csv.py", str(source), str(destination)])
            self.assertEqual(result, 0)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o640)

    def test_same_input_and_output_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "book.jsonl"
            path.write_text(json.dumps(record(), ensure_ascii=False) + "\n", encoding="utf-8")
            original = path.read_bytes()
            result = jsonl_to_csv.main(["jsonl_to_csv.py", str(path), str(path)])
            self.assertEqual(result, 2)
            self.assertEqual(path.read_bytes(), original)

    def test_input_and_output_alias_with_parent_segments_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "book.jsonl"
            path.write_text(json.dumps(record(), ensure_ascii=False) + "\n", encoding="utf-8")
            original = path.read_bytes()
            alias_dir = root / "sub"
            alias_dir.mkdir()
            alias = alias_dir / ".." / "book.jsonl"
            result = jsonl_to_csv.main(["jsonl_to_csv.py", str(path), str(alias)])
            self.assertEqual(result, 2)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
