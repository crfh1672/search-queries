import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
sys.path.insert(0, os.path.abspath(TOOLS))
import score


class ScoreInputTests(unittest.TestCase):
    def test_score_rejects_results_without_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            results = Path(temp) / "results.csv"
            results.write_text("id,type,query,smart_rank,lexical_rank\n", encoding="utf-8")
            with patch.object(sys, "argv", ["score.py", str(results)]):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as cm:
                        score.main()
            self.assertEqual(cm.exception.code, 2)

    def test_score_rejects_zero_rank_instead_of_dividing_by_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            results = Path(temp) / "results.csv"
            results.write_text(
                "id,type,query,smart_rank,lexical_rank\nbook-001,short,q,0,1\n",
                encoding="utf-8",
            )
            with patch.object(sys, "argv", ["score.py", str(results)]):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as cm:
                        score.main()
            self.assertEqual(cm.exception.code, 2)

    def test_loader_fails_when_a_canonical_file_has_a_later_invalid_row(self):
        with tempfile.TemporaryDirectory() as temp:
            book = Path(temp) / "הלכה" / "ספר"
            book.mkdir(parents=True)
            (book / "ספר.jsonl").write_text(
                '{"id":"book-001","type":"short","query":"valid"}\nnot-json\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "canonical dataset file"):
                score.load_data(temp)

    def test_loader_fails_on_duplicate_ids_across_canonical_files(self):
        with tempfile.TemporaryDirectory() as temp:
            for category, book in (("הלכה", "ספר א"), ("מדרש", "ספר ב")):
                directory = Path(temp) / category / book
                directory.mkdir(parents=True)
                (directory / f"{book}.jsonl").write_text(
                    '{"id":"duplicate-001","type":"short","query":"q"}\n',
                    encoding="utf-8",
                )
            with self.assertRaisesRegex(ValueError, "duplicate query ID"):
                score.load_data(temp)

    def test_loader_refuses_symlinked_data_root(self):
        with tempfile.TemporaryDirectory() as temp:
            actual = Path(temp) / "actual"
            actual.mkdir()
            category = actual / "הלכה" / "ספר"
            category.mkdir(parents=True)
            (category / "ספר.jsonl").write_text(
                '{"id":"book-001","type":"short","query":"query"}\n',
                encoding="utf-8",
            )
            link = Path(temp) / "linked"
            try:
                link.symlink_to(actual, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlink is unavailable: {exc}")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rows = score.load_data(str(link))
            self.assertEqual(rows, {})
            self.assertIn("refusing to read", stderr.getvalue())

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
