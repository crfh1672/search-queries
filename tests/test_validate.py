import csv, json, os, shutil, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import validate
import source_refs

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixture", "בדיקה")
NAME = "בדיקה"
with open(os.path.join(HERE, "fixture", "library.txt"), "rb") as _f:
    LIB = _f.read()


class Base(unittest.TestCase):
    lib = LIB

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, NAME)
        shutil.copytree(FIXTURE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def errs(self, loader=None):
        return validate.validate_dataset(self.d, loader=loader or (lambda d, m: (self.lib, None)))

    def has(self, text, **kw):
        return any(text in e for e in self.errs(**kw))

    def load(self):
        with open(os.path.join(self.d, NAME + ".jsonl"), encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    def save(self, rows):
        with open(os.path.join(self.d, NAME + ".jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


class Valid(Base):
    def test_fixture_is_valid(self):
        self.assertEqual(self.errs(), [])

    def test_niqqud_tags_and_divine_name_are_normalised(self):
        # השורה בספרייה כוללת ניקוד, תגיות ו"יהוה", והציטוט כתוב בלי ניקוד וב"ה'"
        self.assertEqual(self.errs(), [])

    def test_heading_paths_follow_hierarchy(self):
        refs = source_refs.line_references([
            "<h1>כתר ראש</h1>",
            "<h2>הלכות ציצית</h2>",
            "<h3>סימן א</h3>",
            "טקסט בתוך הסימן",
            "<h4>סעיף קטן א</h4>",
            "טקסט נוסף",
            "<h3>סימן ב</h3>",
            "המשך",
        ])
        self.assertEqual(refs[3], "הלכות ציצית > סימן א")
        self.assertEqual(refs[5], "הלכות ציצית > סימן א > סעיף קטן א")
        self.assertEqual(refs[7], "הלכות ציצית > סימן ב")

    def test_skipped_heading_level_stays_without_parent(self):
        # Otzaria's tree: a heading that skips a level has no parent.
        refs = source_refs.line_references([
            "<h1>ספר</h1>",
            "<h2>A</h2>",
            "<h4>B</h4>",
            "body",
            "<h5>C</h5>",
            "child",
            "<h3>D</h3>",
        ])
        self.assertEqual(refs[2], "B")
        self.assertEqual(refs[3], "B")
        self.assertEqual(refs[5], "B > C")
        self.assertEqual(refs[6], "A > D")

    def test_heading_reference_preserves_visible_title(self):
        refs = source_refs.line_references([
            "<h2>שֵׁם יהוה ״</h2>",
            "body",
        ])
        self.assertEqual(refs[0], "שֵׁם יהוה ״")

    def test_repeated_heading_titles_have_distinct_internal_sections(self):
        lines = [
            "<h2>אותו סימן</h2>",
            "טקסט ראשון",
            "<h2>אותו סימן</h2>",
            "טקסט שני",
        ]
        refs, section_ids = source_refs.line_reference_data(lines)
        self.assertEqual(refs[1], refs[3])
        self.assertNotEqual(section_ids[1], section_ids[3])
        with self.assertRaisesRegex(ValueError, "repeated-heading boundary"):
            source_refs.span_reference(refs, 2, 4, section_ids)

    def test_malformed_heading_does_not_fail_the_whole_book(self):
        index = source_refs.analyze([
            "<h1>ספר</h1>",       # 1
            "<h2>פרק א</h2>",     # 2
            "גוף א",              # 3
            "<h3><br></h3>",      # 4 malformed
            "גוף לא ודאי",        # 5 ambiguous
            "<h2>פרק ב</h2>",     # 6 recovers
            "גוף ב",              # 7
        ])
        self.assertEqual(index.references[2], "פרק א")
        self.assertEqual(index.references[3:5], [None, None])
        self.assertEqual(index.references[5:], ["פרק ב", "פרק ב"])
        self.assertEqual(list(index.problems), [4])
        with self.assertRaisesRegex(ValueError, "malformed heading"):
            source_refs.span_reference(index.references, 4, 5, index.section_ids)
        self.assertIn("source line 4", source_refs.explain_ambiguity(index.problems, 5))

    def test_deeper_heading_after_malformed_one_stays_ambiguous(self):
        refs = source_refs.line_references([
            "<h1>ספר</h1>", "<h2>פרק</h2>", "<h2", "<h3>סימן</h3>", "טקסט", "<h2>הבא</h2>",
        ])
        self.assertEqual(refs[2:5], [None, None, None])
        self.assertEqual(refs[5], "הבא")

    def test_unterminated_tag_is_malformed_not_fatal(self):
        index = source_refs.analyze(["<h1>ספר</h1>", "<h2 class=x", "טקסט"])
        self.assertEqual(index.references, ["פתיחת הספר", None, None])

    def test_markdown_hash_lines_are_ordinary_body_text(self):
        # Otzaria builds its TOC from <h1>-<h6> only; '#' lines never reset the path.
        index = source_refs.analyze([
            "<h1>ספר</h1>", "<h2>סימן א</h2>", "# הערה: טקסט", "#", "## ", "אחרי",
        ])
        self.assertEqual(index.references[2:], ["סימן א"] * 4)
        self.assertEqual(index.problems, {})

    def test_sibling_headings_with_same_title_are_different_sections(self):
        refs, ids = source_refs.line_reference_data([
            "<h1>ספר</h1>", "<h3>הלכה א</h3>", "a", "<h3>הלכה א</h3>", "b",
        ])
        self.assertEqual(refs[2], refs[4])
        self.assertNotEqual(ids[2], ids[4])

    def test_toc_excluded_heading_does_not_replace_reference(self):
        refs = source_refs.line_references([
            "<h1>כתר ראש</h1>",
            "<h2>הלכות ציצית</h2>",
            "טקסט",
            '<h2 data-toc="none">כותרת משנית</h2>',
            "המשך",
        ])
        self.assertEqual(refs[3], "הלכות ציצית")
        self.assertEqual(refs[4], "הלכות ציצית")



class JsonlChecks(Base):
    def test_broken_json(self):
        with open(os.path.join(self.d, NAME + ".jsonl"), "a", encoding="utf-8") as f:
            f.write("{not json}\n")
        self.assertTrue(self.has("JSON לא תקין"))

    def test_duplicate_keys_in_jsonl_are_rejected(self):
        with open(os.path.join(self.d, NAME + ".jsonl"), "w", encoding="utf-8") as f:
            f.write('{"id":"first","id":"second"}\n')
        self.assertTrue(self.has("duplicate JSON key"))

    def test_extra_field(self):
        rows = self.load(); rows[0]["extra"] = "x"; self.save(rows)
        self.assertTrue(self.has("שדות מיותרים ['extra']"))

    def test_missing_field(self):
        rows = self.load(); del rows[0]["split"]; self.save(rows)
        self.assertTrue(self.has("שדות חסרים ['split']"))

    def test_duplicate_id(self):
        rows = self.load(); rows[1]["id"] = rows[0]["id"]; self.save(rows)
        self.assertTrue(self.has("id כפול"))

    def test_line_in_wrong_heading(self):
        rows = self.load(); rows[0]["correct_line"] = "7"; self.save(rows)
        self.assertTrue(self.has("אינו תואם למסלול הכותרות"))

    def test_line_outside_file(self):
        rows = self.load(); rows[0]["correct_line"] = "999"; self.save(rows)
        self.assertTrue(self.has("מחוץ לקובץ"))

    def test_quote_not_in_line(self):
        rows = self.load(); rows[0]["correct_quote"] = "ציטוט שלא קיים בשום מקום"; self.save(rows)
        self.assertTrue(self.has("לא נמצא בשורה"))

    def test_quote_that_normalizes_to_empty_is_rejected(self):
        rows = self.load(); rows[0]["correct_quote"] = "<b>ְ</b>"; self.save(rows)
        self.assertTrue(self.has("ריק אחרי נירמול"))

    def test_line_range_with_trailing_newline_is_rejected(self):
        rows = self.load(); rows[0]["correct_line"] = rows[0]["correct_line"] + "\n"; self.save(rows)
        self.assertTrue(self.has("correct_line לא תקין"))

    def test_extremely_long_line_number_is_reported_not_crashed(self):
        rows = self.load(); rows[0]["correct_line"] = "9" * 5000; self.save(rows)
        errors = self.errs()
        self.assertTrue(any("correct_line" in error and ("לא תקין" in error or "מחוץ לקובץ" in error) for error in errors))

    def test_bad_type_and_split(self):
        rows = self.load(); rows[0]["type"] = "weird"; rows[0]["split"] = "dev"; self.save(rows)
        self.assertTrue(self.has("type לא חוקי")); self.assertTrue(self.has("split לא חוקי"))

    def test_empty_required_field(self):
        rows = self.load(); rows[0]["query"] = ""; self.save(rows)
        self.assertTrue(self.has("השדה query ריק"))

    def test_ref_for_wrong_heading(self):
        rows = self.load(); rows[0]["correct_ref"] = "כותרת שאינה קיימת"; self.save(rows)
        self.assertTrue(self.has("אינו תואם למסלול הכותרות"))

    def test_same_section_flag_inconsistent(self):
        rows = self.load(); rows[0]["near_miss_same_section"] = "כן"; self.save(rows)
        self.assertTrue(self.has("לא עקבי"))


    def test_correct_and_near_miss_share_a_line(self):
        rows = self.load(); rows[0]["near_miss_line"] = rows[0]["correct_line"]; self.save(rows)
        self.assertTrue(self.has("באותה שורה"))

    def test_overlapping_line_ranges(self):
        rows = self.load(); a, _, b = rows[0]["correct_line"].partition("-")
        rows[0]["near_miss_line"] = f"{a}-{int(b or a) + 1}"; self.save(rows)
        self.assertTrue(self.has("באותה שורה"))


class CsvChecks(Base):
    def _rewrite(self, fn):
        p = os.path.join(self.d, NAME + ".csv")
        with open(p, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        rows = fn(rows)
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)

    def test_extra_column(self):
        self._rewrite(lambda r: [row + ["x"] for row in r])
        self.assertTrue(self.has("מיותרות ['x']"))

    def test_missing_column(self):
        self._rewrite(lambda r: [row[:-1] for row in r])
        self.assertTrue(self.has("חסרות"))

    def test_row_with_wrong_cell_count(self):
        self._rewrite(lambda r: r[:2] + [r[2] + ["x"]] + r[3:])
        self.assertTrue(self.has("עמודות במקום"))

    def test_csv_differs_from_jsonl(self):
        def f(r):
            r[1][1] = r[1][1] + " שונה"; return r
        self._rewrite(f)
        self.assertTrue(self.has("שונה מה-JSONL"))

    def test_missing_row_in_csv(self):
        self._rewrite(lambda r: r[:-1])
        self.assertTrue(self.has("חסר (קיים ב-JSONL)"))


class SourceChecks(Base):
    def test_missing_source_json(self):
        os.remove(os.path.join(self.d, NAME + ".מקור.json"))
        self.assertTrue(self.has("חסר הקובץ בדיקה.מקור.json"))

    def test_source_json_extra_key(self):
        p = os.path.join(self.d, NAME + ".מקור.json")
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
        m["oops"] = 1
        with open(p, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False)
        self.assertTrue(self.has("בדיקה.מקור.json: מפתחות לא תקינים"))

    def test_broken_source_json(self):
        with open(os.path.join(self.d, NAME + ".מקור.json"), "w") as f:
            f.write("{")
        self.assertTrue(self.has("בדיקה.מקור.json: JSON לא תקין"))

    def test_non_object_source_json_is_reported_without_crashing(self):
        with open(os.path.join(self.d, NAME + ".מקור.json"), "w", encoding="utf-8") as f:
            f.write("null")
        self.assertTrue(self.has("המטא־נתונים חייבים להיות אובייקט JSON"))

    def test_duplicate_keys_in_source_json_are_rejected(self):
        with open(os.path.join(self.d, NAME + ".מקור.json"), "w", encoding="utf-8") as f:
            f.write('{"book_name":"בדיקה","book_name":"שונה"}')
        self.assertTrue(self.has("JSON לא תקין"))

    def test_commit_must_be_full_sha(self):
        p = os.path.join(self.d, NAME + ".מקור.json")
        with open(p, encoding="utf-8") as f:
            m = json.load(f)
        m["origin_commit"] = "main"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False)
        self.assertTrue(self.has("SHA מלא"))

    def test_folder_name_must_match_masechet(self):
        other = os.path.join(self.tmp, "אחרת")
        os.makedirs(other)
        for ext in (".jsonl", ".csv", ".מקור.json"):
            shutil.copy(os.path.join(self.d, NAME + ext), os.path.join(other, "אחרת" + ext))
        errs = validate.validate_dataset(other, loader=lambda d, m: (self.lib, None))
        self.assertTrue(any("חייב להיות זהה ל-book_name" in e for e in errs))

    def test_library_file_changed(self):
        self.assertTrue(self.has("שונה מ-origin_sha256", loader=lambda d, m: (self.lib + "\nעוד".encode("utf-8"), None)))

    def test_library_unavailable(self):
        self.assertTrue(self.has("קובץ המקור מאוצריא: לא ניתן למשוך", loader=lambda d, m: (None, "לא ניתן למשוך")))

    def test_only_otzaria_sources_are_accepted(self):
        p = os.path.join(self.d, NAME + ".מקור.json")
        with open(p, encoding="utf-8") as f:
            meta = json.load(f)
        meta["origin_repo"] = "https://github.com/example/library"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        self.assertTrue(self.has("origin_repo must be https://github.com/Otzaria/otzaria-library"))

    def test_uppercase_txt_source_extension_is_rejected(self):
        p = os.path.join(self.d, NAME + ".מקור.json")
        with open(p, encoding="utf-8") as f:
            meta = json.load(f)
        meta["origin_path"] = "MoreBooks/ספרים/אוצריא/בדיקה/בדיקה.TXT"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        self.assertTrue(self.has("origin_path must point to an Otzaria .txt book"))

    def test_source_category_must_match_library_path(self):
        p = os.path.join(self.d, NAME + ".מקור.json")
        with open(p, encoding="utf-8") as f:
            meta = json.load(f)
        meta["source_category"] = "תלמוד בבלי"
        with open(p, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        self.assertTrue(self.has("does not match the library path category"))

    def test_approved_dataset_requires_human_verification(self):
        errs = validate.validate_dataset(
            self.d, loader=lambda d, m: (self.lib, None), require_verified=True
        )
        self.assertTrue(any("מערך מאושר חייב לכלול verified_by_human" in e for e in errs))

    def test_dataset_discovery_includes_book_folder_without_metadata(self):
        root = os.path.join(self.tmp, "datasets")
        target = os.path.join(root, "הלכה", "ספר בלי מטא")
        os.makedirs(target)
        self.assertIn(target, {str(path) for path in validate.dataset_dirs(root)})

    def test_dataset_discovery_reports_misplaced_book_folder_with_jsonl(self):
        root = os.path.join(self.tmp, "datasets")
        target = os.path.join(root, "ספר שהונח ברמה שגויה")
        os.makedirs(target)
        with open(os.path.join(target, "ספר שהונח ברמה שגויה.jsonl"), "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        self.assertIn(target, {str(path) for path in validate.dataset_dirs(root)})

    def test_direct_validator_rejects_symlinked_dataset_root(self):
        target = os.path.join(self.tmp, "real")
        os.makedirs(target)
        link = os.path.join(self.tmp, "linked")
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlink is unavailable: {exc}")
        errors = validate.validate_dataset(link, loader=lambda d, m: (self.lib, None))
        self.assertTrue(any("קישור סמלי" in error for error in errors))

    def test_dataset_discovery_does_not_follow_symlinked_book(self):
        root = os.path.join(self.tmp, "datasets")
        category = os.path.join(root, "הלכה")
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(category)
        os.makedirs(outside)
        with open(os.path.join(outside, "ספר.jsonl"), "w", encoding="utf-8") as handle:
            handle.write("{}\n")
        link = os.path.join(category, "ספר")
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlink is unavailable: {exc}")
        self.assertNotIn(Path(link), validate.dataset_dirs(root))
        self.assertIn(Path(link), validate.symlink_entries(root))



class SourceCase(Base):
    """Helper: replace the fixture source and the first record in one call."""

    def use_source(self, text, correct, near, flag):
        import hashlib
        self.lib = text.encode("utf-8")
        meta_path = os.path.join(self.d, NAME + ".מקור.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["origin_sha256"] = hashlib.sha256(self.lib).hexdigest()
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        row = self.load()[0]
        row.update(
            correct_ref=correct[0], correct_line=correct[1], correct_quote=correct[2],
            near_miss_ref=near[0], near_miss_line=near[1], near_miss_quote=near[2],
            near_miss_same_section=flag,
        )
        self.save([row])
        with open(os.path.join(self.d, NAME + ".csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, lineterminator="\r\n")
            w.writerow(validate.FIELDS)
            w.writerow([row[k] for k in validate.FIELDS])


SIBLINGS = (
    "<h1>ספר</h1>\n<h3>הלכה א</h3>\nמשפט ראשון על נושא א.\n"
    "<h3>הלכה א</h3>\nמשפט שני על נושא ב.\nעוד משפט בהלכה השנייה.\n"
)
FIRST = ("הלכה א", "3", "משפט ראשון על נושא א")
SECOND = ("הלכה א", "5", "משפט שני על נושא ב")
SECOND_LATER = ("הלכה א", "6", "עוד משפט בהלכה השנייה")


class SectionFlag(SourceCase):
    """near_miss_same_section compares section identity, not ref strings."""

    def test_identical_refs_in_sibling_sections_must_be_marked_different(self):
        self.use_source(SIBLINGS, FIRST, SECOND, "כן")
        self.assertTrue(self.has("לא עקבי עם מקטעי המקור"))

    def test_identical_refs_in_sibling_sections_marked_no_is_accepted(self):
        self.use_source(SIBLINGS, FIRST, SECOND, "לא")
        self.assertEqual(self.errs(), [])

    def test_same_section_marked_yes_is_accepted(self):
        self.use_source(SIBLINGS, SECOND, SECOND_LATER, "כן")
        self.assertEqual(self.errs(), [])

    def test_same_section_marked_no_is_rejected(self):
        self.use_source(SIBLINGS, SECOND, SECOND_LATER, "לא")
        self.assertTrue(self.has("לא עקבי עם מקטעי המקור"))


class MalformedHeadingCitations(SourceCase):
    SRC = (
        "<h1>ספר</h1>\n<h2>פרק א</h2>\nמשפט ראשון על נושא א.\n"
        "<h3><br></h3>\nמשפט שני על נושא ב.\n"
    )

    def test_citation_under_malformed_heading_is_rejected_but_book_still_loads(self):
        self.use_source(
            self.SRC,
            ("פרק א", "3", "משפט ראשון על נושא א"),
            ("פרק א", "5", "משפט שני על נושא ב"),
            "כן",
        )
        errors = self.errs()
        self.assertTrue(
            any("near_miss_line" in e and "מבנה כותרות לא ודאי" in e and "source line 4" in e for e in errors),
            errors,
        )
        # the healthy citation (line 3) produces no error of its own
        self.assertFalse(any("correct_line" in e or "correct_ref" in e for e in errors), errors)


class Verifiers(Base):
    def approved(self, verifiers):
        rows = self.load()
        for r in rows:
            r["verified_by_human"] = "ד. כהן"
        self.save(rows)
        return validate.validate_dataset(
            self.d, loader=lambda d, m: (self.lib, None), require_verified=True, verifiers=verifiers
        )

    def test_listed_verifier_is_accepted(self):
        # CSV must mirror JSONL, so rewrite it too.
        rows = self.load()
        for r in rows:
            r["verified_by_human"] = "ד. כהן"
        self.save(rows)
        with open(os.path.join(self.d, NAME + ".csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, lineterminator="\r\n")
            w.writerow(validate.FIELDS)
            for r in rows:
                w.writerow([r[k] for k in validate.FIELDS])
        errs = validate.validate_dataset(
            self.d, loader=lambda d, m: (self.lib, None), require_verified=True, verifiers={"ד. כהן"}
        )
        self.assertEqual(errs, [])

    def test_unlisted_verifier_is_rejected(self):
        errs = self.approved({"מישהו אחר"})
        self.assertTrue(any("אינו מופיע ב-verifiers.txt" in e for e in errs))

    def test_empty_allowlist_rejects_everyone(self):
        errs = self.approved(set())
        self.assertTrue(any("אינו מופיע ב-verifiers.txt" in e for e in errs))

    def test_load_verifiers_ignores_comments_and_blanks(self):
        path = os.path.join(self.tmp, "verifiers.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# header\n\n  ד. כהן  \n#x\nש. לוי\n")
        self.assertEqual(validate.load_verifiers(path), {"ד. כהן", "ש. לוי"})
        self.assertEqual(validate.load_verifiers(os.path.join(self.tmp, "missing.txt")), set())


class SourceGate(Base):
    def set_path(self, origin_path):
        p = os.path.join(self.d, NAME + ".מקור.json")
        with open(p, encoding="utf-8") as f:
            meta = json.load(f)
        meta["origin_path"] = origin_path
        with open(p, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

    def test_unpackaged_extrabooks_root_is_rejected(self):
        self.set_path("extraBooks/SefariaToOtzaria/sefaria_export/ספרים/אוצריא/בדיקה/בדיקה.txt")
        self.assertTrue(self.has("origin_path must be <packaged source root>"))

    def test_dicta_unedited_root_is_rejected(self):
        self.set_path("DictaToOtzaria/לא ערוך/ספרים/אוצריא/בדיקה/בדיקה.txt")
        self.assertTrue(self.has("not part of the shipped library"))

    def test_unsorted_folder_under_a_packaged_root_is_rejected(self):
        self.set_path("OraytaToOtzaria/ספרים/לא ממויין/בדיקה/בדיקה.txt")
        self.assertTrue(self.has("not part of the shipped library"))

    def test_packaged_root_is_accepted(self):
        self.set_path("OraytaToOtzaria/ספרים/אוצריא/בדיקה/בדיקה.txt")
        self.assertEqual(self.errs(), [])

    def test_shadowed_source_is_rejected(self):
        self.set_path("OraytaToOtzaria/ספרים/אוצריא/בדיקה/בדיקה.txt")
        errs = validate.validate_dataset(
            self.d, loader=lambda d, m: (self.lib, None), shadow_check=lambda m: ["MoreBooks"]
        )
        self.assertTrue(any("נדרס" in e and "MoreBooks" in e for e in errs))

    def test_shadow_check_failure_is_reported_not_crashed(self):
        def boom(meta):
            raise OSError("network down")
        errs = validate.validate_dataset(
            self.d, loader=lambda d, m: (self.lib, None), shadow_check=boom
        )
        self.assertTrue(any("לא ניתן לבדוק אם הקובץ נדרס" in e for e in errs))


class CrossDataset(Base):
    def make_copy(self, name, prefix=None, ids=None):
        target = os.path.join(self.tmp, "set", name)
        os.makedirs(target)
        meta_src = os.path.join(self.d, NAME + ".מקור.json")
        with open(meta_src, encoding="utf-8") as f:
            meta = json.load(f)
        if prefix:
            meta["id_prefix"] = prefix
        with open(os.path.join(target, name + ".מקור.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        rows = self.load()
        for r, new_id in zip(rows, ids or [r["id"] for r in rows]):
            r["id"] = new_id
        with open(os.path.join(target, name + ".jsonl"), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return target

    def test_duplicate_ids_across_datasets_are_reported(self):
        a = self.make_copy("א")
        b = self.make_copy("ב", prefix="other", ids=["other-001", "other-002", "fx-001"])
        errors = validate.cross_dataset_errors([a, b])
        self.assertTrue(any("fx-001" in e for e in errors), errors)

    def test_duplicate_prefix_is_reported(self):
        a = self.make_copy("א")
        b = self.make_copy("ב", ids=["zz-001", "zz-002", "zz-003"])
        errors = validate.cross_dataset_errors([a, b])
        self.assertTrue(any("id_prefix" in e for e in errors), errors)

    def test_distinct_datasets_pass(self):
        a = self.make_copy("א")
        b = self.make_copy("ב", prefix="other", ids=["other-001", "other-002", "other-003"])
        self.assertEqual(validate.cross_dataset_errors([a, b]), [])


class UnknownShadowResult(Base):
    def run_check(self, require_verified):
        return validate.validate_dataset(
            self.d, loader=lambda d, m: (self.lib, None), shadow_check=lambda m: None,
            require_verified=require_verified, verifiers=set(),
        )

    def test_unknown_result_blocks_an_approved_dataset(self):
        self.assertTrue(any("offline" in e and "נדרס" in e for e in self.run_check(True)))

    def test_unknown_result_is_tolerated_for_a_draft(self):
        self.assertFalse(any("נדרס" in e for e in self.run_check(False)))


class CrossDatasetScope(CrossDataset):
    def test_all_dataset_dirs_finds_drafts_and_datasets(self):
        root = Path(self.tmp) / "repo"
        for kind in ("datasets", "drafts"):
            (root / kind / "הלכה" / "ספר").mkdir(parents=True)
        found = {p.relative_to(root).parts[0] for p in validate.all_dataset_dirs(root)}
        self.assertEqual(found, {"datasets", "drafts"})

    def test_symlinked_dataset_is_skipped_not_followed(self):
        real = self.make_copy("אמיתי")
        # Same folder name as the real dataset, so a followed link would find
        # real metadata/JSONL files and report duplicate ids.
        (Path(self.tmp) / "links").mkdir()
        link = Path(self.tmp) / "links" / "אמיתי"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlink is unavailable: {exc}")
        self.assertEqual(validate.cross_dataset_errors([Path(real), link]), [])

    def test_unreadable_jsonl_fails_closed(self):
        a = self.make_copy("א")
        b = self.make_copy("ב", prefix="other", ids=["other-001", "other-002", "other-003"])
        Path(b, "ב.jsonl").write_text("{broken\n", encoding="utf-8")
        errors = validate.cross_dataset_errors([a, b])
        self.assertTrue(any("JSONL" in e for e in errors), errors)

    def test_unreadable_metadata_fails_closed(self):
        a = self.make_copy("א")
        Path(a, "א.מקור.json").write_text("not json", encoding="utf-8")
        errors = validate.cross_dataset_errors([a])
        self.assertTrue(any("מטא-דאטה" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
