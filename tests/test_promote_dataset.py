import contextlib
import io
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
        self.root = Path(self.tmp.name)
        self.original_root = promote_dataset.REPO_ROOT
        promote_dataset.REPO_ROOT = self.root
        (self.root / "drafts" / "הלכה").mkdir(parents=True)

    def tearDown(self):
        promote_dataset.REPO_ROOT = self.original_root
        self.tmp.cleanup()

    def run_main(self, path):
        with patch.object(sys, "argv", ["promote_dataset.py", str(path)]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    promote_dataset.main()
        self.assertEqual(cm.exception.code, 2)

    def test_missing_draft_path_exits_with_usage_error(self):
        missing = self.root / "drafts" / "הלכה" / "חסר"
        self.run_main(missing)

    def test_symlinked_draft_directory_exits_with_usage_error(self):
        target = self.root / "outside"
        target.mkdir()
        link = self.root / "drafts" / "הלכה" / "קישור"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlink is unavailable: {exc}")
        self.run_main(link)

    def test_symlink_inside_draft_exits_with_usage_error(self):
        draft = self.root / "drafts" / "הלכה" / "ספר"
        draft.mkdir()
        target = self.root / "outside.txt"
        target.write_text("outside", encoding="utf-8")
        link = draft / "ספר.txt"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"file symlink is unavailable: {exc}")
        self.run_main(draft)


if __name__ == "__main__":
    unittest.main()
