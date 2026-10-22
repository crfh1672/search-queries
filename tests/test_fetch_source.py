import os
import sys
import unittest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
sys.path.insert(0, os.path.abspath(TOOLS))
import fetch_source


class SourceDiffTests(unittest.TestCase):
    def test_heading_only_change_is_reported(self):
        old = b"<h1>Book</h1>\nbody text\n"
        new = b"<h2>Book</h2>\nbody text\n"
        old_lines, new_lines, diff = fetch_source.compare_source_lines(old, new)
        self.assertEqual(old_lines, new_lines)
        self.assertIn(1, diff)
        self.assertIn(2, diff)

    def test_removed_tail_line_is_reported(self):
        old_lines, new_lines, diff = fetch_source.compare_source_lines(
            b"first line\nremoved tail\n", b"first line\n"
        )
        self.assertEqual(len(old_lines), 3)
        self.assertEqual(len(new_lines), 2)
        self.assertIn(3, diff)

    def test_text_only_change_is_reported(self):
        _, _, diff = fetch_source.compare_source_lines(
            b"<h2>Chapter</h2>\nold text\n",
            b"<h2>Chapter</h2>\nnew text\n",
        )
        self.assertIn(2, diff)

    def test_malformed_heading_fails_with_value_error(self):
        with self.assertRaisesRegex(ValueError, "malformed heading"):
            fetch_source.compare_source_lines(
                b"<h2>Chapter</h2>\ntext\n",
                b"<h2>Chapter</h2>\n<h3></h3>\n",
            )


if __name__ == "__main__":
    unittest.main()
