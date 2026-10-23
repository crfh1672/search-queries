import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pathsafe


class PathSafeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        (self.root / "datasets" / "הלכה").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def link(self, target, name):
        try:
            name.symlink_to(target, target_is_directory=Path(target).is_dir())
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink is unavailable: {exc}")

    def test_plain_paths_have_no_link(self):
        self.assertFalse(pathsafe.is_link(self.root))
        self.assertIsNone(pathsafe.link_component(self.root / "datasets" / "הלכה"))
        self.assertEqual(pathsafe.links_in_tree(self.root), [])

    def test_link_below_root_is_found(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        link = self.root / "datasets" / "קישור"
        self.link(outside, link)
        self.assertEqual(pathsafe.link_component(link / "x", self.root), link)
        self.assertEqual(pathsafe.links_in_tree(self.root), [link])

    def test_link_above_root_is_ignored_when_a_root_is_given(self):
        alias = Path(self.tmp.name) / "alias"
        self.link(Path(self.tmp.name), alias)  # alias/repo is the same checkout
        root = alias / "repo"
        self.assertIsNone(pathsafe.link_component(root / "datasets", root))
        self.assertEqual(pathsafe.link_component(root / "datasets"), alias)

    def test_root_that_is_itself_a_link_is_refused(self):
        alias = Path(self.tmp.name) / "alias"
        self.link(self.root, alias)
        self.assertEqual(pathsafe.link_component(alias / "datasets", alias), alias)

    def test_tree_walk_does_not_follow_links(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "inner.txt").write_text("x")
        self.link(outside, self.root / "datasets" / "קישור")
        found = pathsafe.links_in_tree(self.root)
        self.assertEqual([p.name for p in found], ["קישור"])

    def test_link_before_dot_dot_is_still_detected(self):
        outside = Path(self.tmp.name) / "outside"
        (outside / "inner").mkdir(parents=True)
        link = self.root / "datasets" / "קישור"
        self.link(outside, link)
        # The OS resolves link/.. to the link target's parent, not to datasets/.
        self.assertEqual(pathsafe.link_component(link / ".." / "x"), link)

    def test_unreadable_subtree_fails_closed(self):
        from unittest.mock import patch

        def failing_walk(top, topdown=True, onerror=None, followlinks=False):
            onerror(PermissionError("denied"))
            return iter(())

        with patch.object(pathsafe.os, "walk", failing_walk):
            with self.assertRaises(PermissionError):
                pathsafe.links_in_tree(self.root)


if __name__ == "__main__":
    unittest.main()
