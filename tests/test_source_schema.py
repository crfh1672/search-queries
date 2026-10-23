import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import library


SCHEMA = Path(__file__).resolve().parents[1] / "schema" / "source.schema.json"


class SourceSchemaPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        cls.pattern = re.compile(cls.schema["properties"]["origin_path"]["pattern"])

    def test_accepts_repository_relative_otzaria_book_path(self):
        self.assertRegex(
            "MoreBooks/ספרים/אוצריא/הלכה/ספר.txt",
            self.pattern,
        )

    def test_rejects_backslashes(self):
        self.assertNotRegex(
            r"MoreBooks\ספרים\אוצריא\הלכה\ספר.txt",
            self.pattern,
        )

    def test_rejects_duplicate_otzaria_path_segments(self):
        self.assertNotRegex(
            "MoreBooks/ספרים/אוצריא/הלכה/ספרים/אוצריא/ספר.txt",
            self.pattern,
        )

    def test_rejects_dot_segments(self):
        self.assertNotRegex(
            "MoreBooks/./ספרים/אוצריא/הלכה/ספר.txt",
            self.pattern,
        )

    def test_rejects_missing_category_folder(self):
        self.assertNotRegex(
            "ספרים/אוצריא/ספר.txt",
            self.pattern,
        )

    def test_schema_pattern_matches_the_packaged_roots_in_code(self):
        self.assertEqual(self.schema["properties"]["origin_path"]["pattern"],
                         library.schema_origin_path_pattern())

    def test_every_packaged_root_is_accepted_by_schema_and_code(self):
        for root in library.PACKAGED_ROOTS:
            path = f"{root}/ספרים/אוצריא/הלכה/ספר.txt"
            self.assertRegex(path, self.pattern)
            self.assertEqual(library.source_category_from_path(path), "הלכה")

    def test_unpackaged_roots_are_rejected_by_schema_and_code(self):
        for path in (
            "extraBooks/SefariaToOtzaria/sefaria_export/ספרים/אוצריא/משנה/ספר.txt",
            "DictaToOtzaria/לא ערוך/ספרים/אוצריא/הלכה/ספר.txt",
            "docxToOtzaria/ספרים/אוצריא/הלכה/ספר.txt",
            "OraytaToOtzaria/ספרים/לא ממויין/תלמוד בבלי/ספר.txt",
            "ספרים/אוצריא/הלכה/ספר.txt",
        ):
            self.assertNotRegex(path, self.pattern)
            with self.assertRaises(ValueError):
                library.source_category_from_path(path)

    def test_a_root_name_is_not_accepted_as_a_nested_substring(self):
        path = "x/MoreBooks/ספרים/אוצריא/הלכה/ספר.txt"
        self.assertNotRegex(path, self.pattern)
        with self.assertRaises(ValueError):
            library.source_category_from_path(path)


if __name__ == "__main__":
    unittest.main()
