import hashlib
import os
import tempfile
import unittest
import urllib.parse
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


class ShadowingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.old_root, self.old_cache = library.ROOT, library.CACHE_DIR
        library.ROOT = str(self.root)
        library.CACHE_DIR = str(self.root / ".cache" / "library")
        self.meta = {
            "book_name": "Book", "source_category": "הלכה", "id_prefix": "book",
            "origin_repo": library.CANONICAL_REPO_URL,
            "origin_path": "OraytaToOtzaria/ספרים/אוצריא/הלכה/Book.txt",
            "origin_commit": "a" * 40, "origin_sha256": "b" * 64, "note": "",
        }

    def tearDown(self):
        library.ROOT, library.CACHE_DIR = self.old_root, self.old_cache
        self.temp.cleanup()

    def opener_for(self, present_roots, calls):
        import urllib.error

        def opener(request, timeout=0):
            url = urllib.parse.unquote(request.full_url)
            calls.append(url)
            if any(f"/{root}/ספרים/אוצריא/" in url for root in present_roots):
                class Ok:
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return Ok()
            raise urllib.error.HTTPError(request.full_url, 404, "nf", {}, None)
        return opener

    def test_only_later_roots_are_checked_and_hits_are_reported(self):
        calls = []
        result = library.shadowing_roots(self.meta, opener=self.opener_for({"MoreBooks"}, calls))
        self.assertEqual(result, ["MoreBooks"])
        checked = [c for c in calls]
        self.assertTrue(all("/OraytaToOtzaria/" not in c for c in checked))
        self.assertEqual(len(checked), len(library.PACKAGED_ROOTS) - library.PACKAGED_ROOTS.index("OraytaToOtzaria") - 1)

    def test_not_shadowed_returns_empty_list(self):
        self.assertEqual(library.shadowing_roots(self.meta, opener=self.opener_for(set(), [])), [])

    def test_last_root_can_never_be_shadowed_and_needs_no_requests(self):
        meta = dict(self.meta, origin_path="BeitAharonVeYisraelToOtzaria/ספרים/אוצריא/הלכה/Book.txt")
        calls = []
        self.assertEqual(library.shadowing_roots(meta, opener=self.opener_for(set(), calls)), [])
        self.assertEqual(calls, [])

    def test_answer_is_cached_and_reused_offline(self):
        library.shadowing_roots(self.meta, opener=self.opener_for({"KSK"}, []))
        self.assertEqual(library.shadowing_roots(self.meta, offline=True), ["KSK"])

    def test_offline_without_cache_is_unknown(self):
        self.assertIsNone(library.shadowing_roots(self.meta, offline=True))

    def test_server_error_propagates_instead_of_passing_silently(self):
        import urllib.error

        def broken(request, timeout=0):
            raise urllib.error.HTTPError(request.full_url, 500, "boom", {}, None)
        with patch.object(library, "_sleep", lambda s: None):
            with self.assertRaises(urllib.error.HTTPError):
                library.shadowing_roots(self.meta, opener=broken)

    def test_transient_errors_are_retried_a_bounded_number_of_times(self):
        import urllib.error
        attempts = []

        def flaky(request, timeout=0):
            attempts.append(1)
            if len(attempts) < 3:
                raise urllib.error.HTTPError(request.full_url, 429, "slow down", {}, None)
            raise urllib.error.HTTPError(request.full_url, 404, "nf", {}, None)
        with patch.object(library, "_sleep", lambda s: None):
            self.assertFalse(library._exists_at("https://example.invalid/x", flaky))
        self.assertEqual(len(attempts), 3)

        attempts.clear()

        def always_down(request, timeout=0):
            attempts.append(1)
            raise urllib.error.HTTPError(request.full_url, 503, "down", {}, None)
        with patch.object(library, "_sleep", lambda s: None):
            with self.assertRaises(urllib.error.HTTPError):
                library._exists_at("https://example.invalid/x", always_down)
        self.assertEqual(len(attempts), library._ATTEMPTS)

    def test_a_symlinked_cache_entry_is_not_read(self):
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text('["KSK"]', encoding="utf-8")
        cache = Path(library.CACHE_DIR)
        cache.mkdir(parents=True)
        name = f"shadow-{library._cache_identity(self.meta)}-{self.meta['origin_commit'][:10]}.json"
        try:
            (cache / name).symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink is unavailable: {exc}")
        self.assertIsNone(library.shadowing_roots(self.meta, offline=True))
        self.assertEqual(outside.read_text(encoding="utf-8"), '["KSK"]')


if __name__ == "__main__":
    unittest.main()
