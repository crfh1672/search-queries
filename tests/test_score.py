import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
sys.path.insert(0, os.path.abspath(TOOLS))
import score


class ScoreInputTests(unittest.TestCase):
    def test_loads_canonical_file_and_warns_about_misnamed_jsonl(self):
        with tempfile.TemporaryDirectory() as temp:
            book = Path(temp) / "הלכה" / "ספר"
            book.mkdir(parents=True)
            (book / "ספר.jsonl").write_text(
                json.dumps({"id": "book-001", "type": "short", "query": "query"}) + "\n",
                encoding="utf-8",
            )
            (book / "backup.jsonl").write_text(
                json.dumps({"id": "bad-001", "type": "short", "query": "backup"}) + "\n",
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rows = score.load_data(temp)
            self.assertEqual(set(rows), {"book-001"})
            self.assertIn("backup.jsonl", stderr.getvalue())
            self.assertIn("Warning", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
