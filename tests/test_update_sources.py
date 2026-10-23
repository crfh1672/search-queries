import contextlib
import io
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
sys.path.insert(0, os.path.abspath(TOOLS))
try:
    import library  # noqa
except ModuleNotFoundError:
    fake = types.ModuleType("library")
    fake.norm = lambda s: " ".join(s.split())
    fake.fetch = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network disabled"))
    fake.get_pinned = lambda *a, **k: (None, "network disabled")
    sys.modules["library"] = fake
import update_sources
import source_refs


class MappingTests(unittest.TestCase):
    def test_inserted_line_moves_quote(self):
        old = ["header", "important text", "end"]
        new = ["header", "new line", "important text", "end"]
        mapping = update_sources.line_map(old, new)
        self.assertEqual(
            update_sources.locate_quote(old, new, "important text", (2, 2), mapping),
            (3, 3),
        )

    def test_unique_quote_after_edit(self):
        old = ["header", "before unique phrase after"]
        new = ["header", "added: before unique phrase after"]
        mapping = update_sources.line_map(old, new)
        self.assertEqual(
            update_sources.locate_quote(old, new, "unique phrase", (2, 2), mapping),
            (2, 2),
        )

    def test_changed_quote_requires_review(self):
        old = ["header", "old wording"]
        new = ["header", "new wording"]
        mapping = update_sources.line_map(old, new)
        with self.assertRaises(update_sources.UpdateProblem):
            update_sources.locate_quote(old, new, "old wording", (2, 2), mapping)

    def test_ambiguous_quote_requires_review(self):
        old = ["header", "the unique phrase", "other"]
        # The quote appears as a substring on two changed lines, while the
        # original line no longer maps exactly to either line.
        new = ["header", "x unique phrase", "another unique phrase"]
        mapping = update_sources.line_map(old, new)
        with self.assertRaises(update_sources.UpdateProblem):
            update_sources.locate_quote(
                old, new, "unique phrase", (2, 2), mapping
            )

    def test_overlapping_mapped_citations_require_review(self):
        row = {"correct_line": "12", "near_miss_line": "12"}
        with self.assertRaises(update_sources.UpdateProblem):
            update_sources.ensure_citations_do_not_overlap(row)

    def test_separate_mapped_citations_are_allowed(self):
        row = {"correct_line": "12", "near_miss_line": "13"}
        update_sources.ensure_citations_do_not_overlap(row)

    def test_heading_path_reference_is_derived_from_nested_toc(self):
        # A heading excluded from Otzaria's TOC must not become a citation section.
        lines = [
            "<h1>כתר ראש</h1>",
            "<h2>הלכות ציצית</h2>",
            "<h3>סימן א</h3>",
            "טקסט בתוך הסימן",
            "<h4>סעיף קטן א</h4>",
            "עוד טקסט",
            "<h3>סימן ב</h3>",
            "המשך",
        ]
        references = source_refs.line_references(lines)
        self.assertEqual(
            update_sources.reference_for_line(references, 4, "כתר ראש"),
            "הלכות ציצית > סימן א",
        )
        self.assertEqual(
            update_sources.reference_for_line(references, 6, "כתר ראש"),
            "הלכות ציצית > סימן א > סעיף קטן א",
        )
        self.assertEqual(
            update_sources.reference_for_line(references, 8, "כתר ראש"),
            "הלכות ציצית > סימן ב",
        )

    def test_citation_span_checks_intermediate_heading(self):
        lines = ["start quote", "middle", "end quote"]
        row = {
            "correct_line": "1-3",
            "correct_quote": "start quote middle end quote",
            "correct_ref": "",
        }
        refs = ["same", "intermediate", "same"]
        with self.assertRaisesRegex(update_sources.UpdateProblem, "heading boundary"):
            update_sources.map_citation(
                row, "correct", lines, lines,
                update_sources.line_map(lines, lines), "book", refs,
            )

    def test_citation_span_checks_repeated_heading_with_same_path(self):
        lines = ["start quote", "middle", "end quote"]
        row = {
            "correct_line": "1-3",
            "correct_quote": "start quote middle end quote",
            "correct_ref": "",
        }
        refs = ["same", "same", "same"]
        section_ids = [10, 10, 11]
        with self.assertRaisesRegex(update_sources.UpdateProblem, "heading boundary"):
            update_sources.map_citation(
                row, "correct", lines, lines,
                update_sources.line_map(lines, lines), "book", refs, section_ids,
            )

    def test_report_symlink_is_rejected_before_any_dataset_update(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "datasets"
            dataset = root / "ספר"
            dataset.mkdir(parents=True)
            (dataset / "ספר.מקור.json").write_text("{}", encoding="utf-8")
            outside_report = Path(temp) / "outside-report.md"
            outside_report.write_text("keep me", encoding="utf-8")
            report = root / "SOURCE_UPDATE_REPORT.md"
            try:
                report.symlink_to(outside_report)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"file symlink is unavailable: {exc}")

            with patch.object(
                sys, "argv",
                ["update_sources.py", "--datasets-dir", str(root), "--report", str(report)],
            ):
                with patch.object(update_sources, "update_dataset") as update:
                    with contextlib.redirect_stderr(io.StringIO()):
                        result = update_sources.main()
            self.assertEqual(result, 1)
            update.assert_not_called()
            self.assertEqual(outside_report.read_text(encoding="utf-8"), "keep me")

    def test_updater_rejects_symlinked_dataset_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "dataset"
            dataset.mkdir()
            outside = root / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            try:
                (dataset / "linked.txt").symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"file symlink is unavailable: {exc}")
            with self.assertRaisesRegex(update_sources.UpdateProblem, "symlink or junction"):
                update_sources.reject_symlink_tree(dataset)

    def test_read_rows_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "book.jsonl"
            path.write_text(
                '{"id":"book-001","id":"book-002"}\\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(update_sources.UpdateProblem, "duplicate JSON key"):
                update_sources.read_rows(path)

    def test_write_dataset_preserves_existing_file_modes(self):
        if os.name == "nt":
            self.skipTest("POSIX permission bits are not portable to Windows")
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            name = "ספר"
            for filename in (f"{name}.jsonl", f"{name}.csv", f"{name}.מקור.json"):
                path = directory / filename
                path.write_text("old", encoding="utf-8")
                path.chmod(0o640)

            row = {field: "" for field in update_sources.FIELDS}
            row.update({"id": "book-001", "query": "q", "type": "short"})
            update_sources.write_dataset(directory, name, [row], {"book_name": name})

            for filename in (f"{name}.jsonl", f"{name}.csv", f"{name}.מקור.json"):
                self.assertEqual(stat.S_IMODE((directory / filename).stat().st_mode), 0o640)

    def test_write_dataset_rolls_back_if_replacement_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            name = "ספר"
            originals = {
                f"{name}.jsonl": b"old jsonl\\n",
                f"{name}.csv": b"old csv\\n",
                f"{name}.מקור.json": b'{"old":true}\\n',
            }
            for filename, payload in originals.items():
                (directory / filename).write_bytes(payload)

            row = {field: "" for field in update_sources.FIELDS}
            row.update({"id": "book-001", "query": "q", "type": "short"})
            meta = {"book_name": name}
            real_replace = os.replace
            calls = {"count": 0}

            def fail_second_replace(src, dst):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("simulated replacement failure")
                return real_replace(src, dst)

            with patch.object(update_sources.os, "replace", side_effect=fail_second_replace):
                with self.assertRaisesRegex(update_sources.UpdateProblem, "original files restored"):
                    update_sources.write_dataset(directory, name, [row], meta)

            for filename, payload in originals.items():
                self.assertEqual((directory / filename).read_bytes(), payload)
            self.assertFalse(any(p.name.endswith(".tmp") for p in directory.iterdir()))



    def test_citation_under_malformed_new_heading_needs_manual_review(self):
        lines = ["<h1>B</h1>", "<h2>A</h2>", "x", "<h3><br></h3>", "quote"]
        refs, ids = source_refs.line_reference_data(lines)
        row = {"correct_line": "5", "correct_quote": "quote", "correct_ref": ""}
        plain = ["B", "A", "x", "", "quote"]
        with self.assertRaisesRegex(update_sources.UpdateProblem, "malformed heading"):
            update_sources.map_citation(
                row, "correct", plain, plain, update_sources.line_map(plain, plain), "book", refs, ids,
            )

    def test_section_flag_is_recomputed_from_section_ids_not_ref_strings(self):
        lines = ["<h1>B</h1>", "<h3>הלכה א</h3>", "first", "<h3>הלכה א</h3>", "second"]
        refs, ids = source_refs.line_reference_data(lines)
        self.assertEqual(refs[2], refs[4])
        self.assertNotEqual(ids[2], ids[4])


if __name__ == "__main__":
    unittest.main()
