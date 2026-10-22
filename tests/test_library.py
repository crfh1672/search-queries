import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
import sys
sys.path.insert(0, os.path.abspath(TOOLS))
import library


class PinnedSourceCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.outside = Path(self.temp.name) / "outside"
        self.outside.mkdir()
        self.old_root = library.ROOT
        self.old_cache = library.CACHE_DIR
        library.ROOT = str(self.root)
        library.CACHE_DIR = str(self.root / ".cache" / "library")
        self.data = b"<h1>Book</h1>\nsource body\n"
        self.meta = {
            "book_name": "Book",
            "source_category": "הלכה",
            "id_prefix": "book",
            "origin_repo": library.CANONICAL_REPO_URL,
            "origin_path": "MoreBooks/ספרים/אוצריא/הלכה/Book.txt",
            "origin_commit": "a" * 40,
            "origin_sha256": hashlib.sha256(self.data).hexdigest(),
            "note": "test",
        }

    def tearDown(self):
        library.ROOT = self.old_root
        library.CACHE_DIR = self.old_cache
        self.temp.cleanup()

    def test_symlinked_cache_directory_is_never_written_through(self):
        cache_root = self.root / ".cache"
        cache_root.mkdir()
        outside_file = self.outside / "keep.txt"
        outside_file.write_bytes(b"outside must remain unchanged")
        (cache_root / "library").symlink_to(self.outside, target_is_directory=True)

        with patch.object(library, "fetch", return_value=self.data) as fetch:
            data, error = library.get_pinned("Book", self.meta)

        self.assertIsNone(error)
        self.assertEqual(data, self.data)
        self.assertEqual(outside_file.read_bytes(), b"outside must remain unchanged")
        self.assertFalse(Path(library.cache_path("Book", self.meta)).exists())
        fetch.assert_called_once_with(self.meta, self.meta["origin_commit"])

    def test_symlinked_cache_file_is_replaced_without_touching_target(self):
        cache_dir = Path(library.CACHE_DIR)
        cache_dir.mkdir(parents=True)
        outside_file = self.outside / "keep.txt"
        outside_file.write_bytes(b"outside must remain unchanged")
        cache_file = Path(library.cache_path("Book", self.meta))
        cache_file.symlink_to(outside_file)

        with patch.object(library, "fetch", return_value=self.data):
            data, error = library.get_pinned("Book", self.meta)

        self.assertIsNone(error)
        self.assertEqual(data, self.data)
        self.assertEqual(outside_file.read_bytes(), b"outside must remain unchanged")
        self.assertFalse(cache_file.is_symlink())
        self.assertEqual(cache_file.read_bytes(), self.data)

    def test_verified_regular_cache_works_offline(self):
        with patch.object(library, "fetch", return_value=self.data):
            data, error = library.get_pinned("Book", self.meta)
        self.assertIsNone(error)
        self.assertEqual(data, self.data)

        with patch.object(library, "fetch", side_effect=AssertionError("network should not be used")):
            offline_data, offline_error = library.get_pinned("Book", self.meta, offline=True)
        self.assertIsNone(offline_error)
        self.assertEqual(offline_data, self.data)

    def test_cache_write_never_bypasses_a_bad_source_hash(self):
        bad_meta = dict(self.meta)
        bad_meta["origin_sha256"] = "b" * 64
        with patch.object(library, "fetch", return_value=self.data):
            data, error = library.get_pinned("Book", bad_meta)
        self.assertIsNone(data)
        self.assertIn("origin_sha256", error)
        self.assertFalse(Path(library.CACHE_DIR).exists())


if __name__ == "__main__":
    unittest.main()
