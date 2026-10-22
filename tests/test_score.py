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


def query_record(identifier, query):
    return {
        "id": identifier,
        "query": query,
        "type": "short",
        "correct_ref": "פתיחת הספר",
        "correct_quote": "quote",
        "correct_line": "1",
        "near_miss_ref": "פתיחת הספר",
        "near_miss_quote": "near miss",
        "near_miss_line": "2",
        "near_miss_same_section": "כן",
        "split": "train",
        "verified_by_human": "test verifier",
    }


class ScoreInputTests(unittest.TestCase):
    def write_data(self, root):
        data_root = Path(root) / "datasets"
        book = data_root / "הלכה" / "ספר"
        book.mkdir(parents=True)
        (book / "ספר.jsonl").write_text(
            json.dumps(query_record("book-001", "q")) + "\n",
            encoding="utf-8",
        )
        return data_root

    def test_fixture_is_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as temp:
            data_root = self.write_data(temp)
            loaded = score.load_data(data_root)
            self.assertEqual(set(loaded), {"book-001"})

    def run_score(self, results, data_root):
        with patch.object(
            sys, "argv", ["score.py", str(results), "--data", str(data_root)]
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    score.main()
        self.assertEqual(cm.exception.code, 2)

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
            data_root = self.write_data(temp)
            results = Path(temp) / "results.csv"
            results.write_text(
                "id,type,query,smart_rank,lexical_rank\nbook-001,short,q,0,1\n",
                encoding="utf-8",
            )
            self.run_score(results, data_root)

    def test_score_rejects_unknown_result_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            data_root = self.write_data(temp)
            results = Path(temp) / "results.csv"
            results.write_text(
                "id,type,query,smart_rank\nother-001,short,q,1\n",
                encoding="utf-8",
            )
            self.run_score(results, data_root)

    def test_score_rejects_duplicate_result_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            data_root = self.write_data(temp)
            results = Path(temp) / "results.csv"
            results.write_text(
                "id,type,query,smart_rank\nbook-001,short,q,1\nbook-001,short,q,2\n",
                encoding="utf-8",
            )
            self.run_score(results, data_root)

    def test_score_rejects_edited_query_or_type(self):
        with tempfile.TemporaryDirectory() as temp:
            data_root = self.write_data(temp)
            results = Path(temp) / "results.csv"
            results.write_text(
                "id,type,query,smart_rank\nbook-001,conceptual,changed,1\n",
                encoding="utf-8",
            )
            self.run_score(results, data_root)

    def test_score_rejects_missing_canonical_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            data_root = self.write_data(temp)
            book2 = data_root / "מדרש" / "ספר נוסף"
            book2.mkdir(parents=True)
            (book2 / "ספר נוסף.jsonl").write_text(
                json.dumps(query_record("book-002", "q2")) + "\\n",
                encoding="utf-8",
            )
            results = Path(temp) / "results.csv"
            results.write_text(
                "id,type,query,smart_rank\nbook-001,short,q,1\n",
                encoding="utf-8",
            )
            self.run_score(results, data_root)

    def test_loader_fails_when_a_canonical_file_has_a_later_invalid_row(self):
        with tempfile.TemporaryDirectory() as temp:
            book = Path(temp) / "הלכה" / "ספר"
            book.mkdir(parents=True)
            (book / "ספר.jsonl").write_text(
                json.dumps(query_record("book-001", "valid")) + "\nnot-json\n",
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
                    json.dumps(query_record("duplicate-001", "q")) + "\n",
                    encoding="utf-8",
                )
            with self.assertRaisesRegex(ValueError, "duplicate query ID"):
                score.load_data(temp)

    def test_loader_allows_symlinked_ancestor_above_data_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            actual = root / "actual"
            book = actual / "datasets" / "הלכה" / "ספר"
            book.mkdir(parents=True)
            (book / "ספר.jsonl").write_text(
                json.dumps(query_record("book-001", "query")) + "\n",
                encoding="utf-8",
            )
            alias = root / "alias"
            try:
                alias.symlink_to(actual, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlink is unavailable: {exc}")
            loaded = score.load_data(alias / "datasets")
            self.assertEqual(set(loaded), {"book-001"})

    def test_loader_refuses_symlinked_data_root(self):
        with tempfile.TemporaryDirectory() as temp:
            actual = Path(temp) / "actual"
            actual.mkdir()
            category = actual / "הלכה" / "ספר"
            category.mkdir(parents=True)
            (category / "ספר.jsonl").write_text(
                json.dumps(query_record("book-001", "query")) + "\n",
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
                json.dumps(query_record("book-001", "query")) + "\n",
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
