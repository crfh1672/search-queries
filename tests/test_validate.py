import csv, json, os, shutil, sys, tempfile, unittest
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

    def test_malformed_empty_heading_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "malformed heading at source line 3"):
            source_refs.line_references([
                "<h1>ספר</h1>",
                "<h2>פרק</h2>",
                "<h3></h3>",
                "טקסט",
            ])

    def test_toc_excluded_heading_does_not_replace_reference(self):
        refs = source_refs.line_references([
            "<h1>כתר ראש</h1>",
            "<h2>הלכות ציצית</h2>",
            "טקסט",
            '<h2 data-toc="none">כותרת משנית</h2>',
            "המשך",
        ])
        self.assertEqual(refs[4], "הלכות ציצית")
        self.assertEqual(refs[5], "הלכות ציצית")



class JsonlChecks(Base):
    def test_broken_json(self):
        with open(os.path.join(self.d, NAME + ".jsonl"), "a", encoding="utf-8") as f:
            f.write("{not json}\n")
        self.assertTrue(self.has("JSON לא תקין"))

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



if __name__ == "__main__":
    unittest.main()
