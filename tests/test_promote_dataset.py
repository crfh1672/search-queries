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
import promote_dataset


class PromotePathSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.original_root = promote_dataset.REPO_ROOT
        promote_dataset.REPO_ROOT = self.root
        self.draft_root = self.root / "drafts" / "הלכה"
        self.draft_root.mkdir(parents=True)

    def tearDown(self):
        promote_dataset.REPO_ROOT = self.original_root
        self.tmp.cleanup()

    def create_draft(self, name="ספר"):
        draft = self.draft_root / name
        draft.mkdir()
        (draft / f"{name}.jsonl").write_text('{"id":"book-001"}\n', encoding="utf-8")
        (draft / f"{name}.csv").write_text("id\nbook-001\n", encoding="utf-8")
        meta = {
            "book_name": name,
            "source_category": "הלכה",
            "id_prefix": "book",
            "origin_repo": "https://github.com/Otzaria/otzaria-library",
            "origin_path": f"MoreBooks/ספרים/אוצריא/הלכה/{name}.txt",
            "origin_commit": "a" * 40,
            "origin_sha256": "b" * 64,
            "note": "test fixture",
        }
        (draft / f"{name}.מקור.json").write_text(
            json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return draft

    def run_main(self, path):
        with patch.object(sys, "argv", ["promote_dataset.py", str(path)]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    promote_dataset.main()
        self.assertEqual(cm.exception.code, 2)

    def run_promotion(self, draft):
        with patch.object(sys, "argv", ["promote_dataset.py", str(draft)]):
            with patch.object(promote_dataset.validate, "validate_dataset", return_value=[]):
                with contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()) as out:
                    result = promote_dataset.main()
        return result, out.getvalue(), err.getvalue()

    def test_missing_draft_path_exits_with_usage_error(self):
        self.run_main(self.draft_root / "חסר")

    def test_symlinked_draft_directory_exits_with_usage_error(self):
        target = self.root / "outside"
        target.mkdir()
        link = self.draft_root / "קישור"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlink is unavailable: {exc}")
        self.run_main(link)

    def test_symlink_inside_draft_exits_with_usage_error(self):
        draft = self.create_draft()
        target = self.root / "outside.txt"
        target.write_text("outside", encoding="utf-8")
        link = draft / "linked.txt"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"file symlink is unavailable: {exc}")
        self.run_main(draft)

    def test_successful_promotion_moves_the_validated_snapshot(self):
        draft = self.create_draft()
        result, stdout, stderr = self.run_promotion(draft)
        target = self.root / "datasets" / "הלכה" / "ספר"
        self.assertEqual(result, 0)
        self.assertTrue((target / "ספר.jsonl").is_file())
        self.assertFalse(draft.exists())
        self.assertIn("המערך אומת והועבר", stdout)
        self.assertEqual(stderr, "")

    def test_existing_destination_is_refused_cleanly(self):
        draft = self.create_draft()
        destination = self.root / "datasets" / "הלכה" / "ספר"
        destination.mkdir(parents=True)
        result, stdout, stderr = self.run_promotion(draft)
        self.assertEqual(result, 1)
        self.assertTrue(draft.exists())
        self.assertIn("היעד כבר קיים", stderr)

    def test_mismatched_draft_category_is_refused_even_if_validator_is_stubbed(self):
        draft = self.create_draft()
        meta_path = draft / "ספר.מקור.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["source_category"] = "מדרש"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        result, _, stderr = self.run_promotion(draft)
        self.assertEqual(result, 1)
        self.assertTrue(draft.exists())
        self.assertIn("does not match", stderr)

    def test_path_based_rename_fallback_promotes_successfully(self):
        draft = self.create_draft()
        with patch.object(promote_dataset, "source_files_supported_by_dir_fd", return_value=False):
            result, _, stderr = self.run_promotion(draft)
        self.assertEqual(result, 0)
        self.assertEqual(stderr, "")
        self.assertTrue((self.root / "datasets" / "הלכה" / "ספר" / "ספר.jsonl").is_file())

    def test_symlinked_datasets_root_does_not_create_outside_category(self):
        outside = self.root / "outside"
        outside.mkdir()
        try:
            (self.root / "datasets").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlink is unavailable: {exc}")
        draft = self.create_draft()
        result, _, stderr = self.run_promotion(draft)
        self.assertEqual(result, 1)
        self.assertFalse((outside / "הלכה").exists())
        self.assertIn("בוטל", stderr)

    def test_changes_to_original_draft_do_not_change_promoted_snapshot(self):
        draft = self.create_draft()

        def edit_original_after_snapshot(staged, **kwargs):
            staged = Path(staged)
            self.assertIn("ספר.jsonl", {p.name for p in staged.iterdir()})
            (draft / "ספר.jsonl").write_text('{"id":"tampered"}\n', encoding="utf-8")
            return []

        with patch.object(sys, "argv", ["promote_dataset.py", str(draft)]):
            with patch.object(
                promote_dataset.validate,
                "validate_dataset",
                side_effect=edit_original_after_snapshot,
            ):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    result = promote_dataset.main()

        target = self.root / "datasets" / "הלכה" / "ספר" / "ספר.jsonl"
        self.assertEqual(result, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), '{"id":"book-001"}\n')
        self.assertTrue(draft.exists())
        self.assertIn("השתנתה בזמן הקידום", err.getvalue())


if __name__ == "__main__":
    unittest.main()
