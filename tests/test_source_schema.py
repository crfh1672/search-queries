import json
import re
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
