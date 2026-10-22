#!/usr/bin/env python3
"""חישוב Recall@K ו-MRR מתוצאות מדידה ידנית.

שלב 1: יצירת גיליון ריק למילוי:
    python tools/score.py --template results.csv

שלב 2: מריצים כל שאילתה באוצריא ורושמים בעמודות את המקום שבו הופיעה התשובה
הנכונה (1 = התוצאה הראשונה). משאירים ריק אם לא הופיעה ב-30 הראשונות.
העמודות: smart_rank (חיפוש חכם), lexical_rank (חיפוש רגיל), אפשר להוסיף hybrid_rank.

שלב 3: חישוב:
    python tools/score.py results.csv
"""
import argparse, csv, glob, json, os, collections, sys
from pathlib import Path

import validate


def has_link_below_root(path, root):
    """Check the data root and its descendants, not unrelated OS ancestors."""
    path = Path(path)
    root = Path(root)
    try:
        relative = path.relative_to(root)
    except ValueError:
        return validate.is_path_link(path)
    current = root
    for component in relative.parts[:-1]:
        current = current / component
        if validate.is_path_link(current):
            return True
    return validate.is_path_link(path)


def load_data(data_dir="datasets"):
    rows = {}
    root = os.path.abspath(data_dir)
    if validate.is_path_link(root):
        print(f"Warning: refusing to read through a symlink or junction: {root!r}", file=sys.stderr)
        return rows
    # Only load the canonical file at datasets/<category>/<book>/<book>.jsonl.
    # Ignore nested examples, backups, and any alternate JSONL files.
    pattern = os.path.join(root, "*", "*", "*.jsonl")
    for p in sorted(glob.glob(pattern)):
        if has_link_below_root(p, Path(root)):
            print(f"Warning: ignoring JSONL path containing a symlink/junction: {p!r}", file=sys.stderr)
            continue
        if os.path.basename(p) != os.path.basename(os.path.dirname(p)) + ".jsonl":
            print(
                f"Warning: ignoring non-canonical JSONL file {p!r}; "
                "expected the file name to match its book directory",
                file=sys.stderr,
            )
            continue
        try:
            file_rows = []
            seen_in_file = set()
            with open(p, encoding="utf-8") as f:
                for line_number, line in enumerate(f, 1):
                    if line.strip():
                        r = json.loads(line, object_pairs_hook=validate.unique_json_object)
                        if not isinstance(r, dict) or list(r.keys()) != validate.FIELDS:
                            raise ValueError(
                                f"{p}:{line_number}: record does not match the 12-field query schema"
                            )
                        if any(not isinstance(r[key], str) for key in validate.FIELDS):
                            raise ValueError(f"{p}:{line_number}: all query fields must be strings")
                        if any(
                            not r[key].strip() and key not in validate.OPTIONAL_EMPTY
                            for key in validate.FIELDS
                        ):
                            raise ValueError(f"{p}:{line_number}: a required query field is empty")
                        if not validate.ID_RE.fullmatch(r["id"]):
                            raise ValueError(f"{p}:{line_number}: invalid query ID {r['id']!r}")
                        if r["type"] not in validate.TYPES:
                            raise ValueError(f"{p}:{line_number}: invalid query type {r['type']!r}")
                        if r["split"] not in validate.SPLITS:
                            raise ValueError(f"{p}:{line_number}: invalid split {r['split']!r}")
                        if r["near_miss_same_section"] not in validate.YESNO:
                            raise ValueError(f"{p}:{line_number}: invalid near-miss section flag")
                        if not r["verified_by_human"].strip():
                            raise ValueError(f"{p}:{line_number}: approved dataset lacks human verification")
                        if r["correct_quote"] == r["near_miss_quote"]:
                            raise ValueError(f"{p}:{line_number}: correct and near-miss quotes are identical")
                        try:
                            correct_start, correct_end = validate.span(r["correct_line"])
                            near_start, near_end = validate.span(r["near_miss_line"])
                        except ValueError as exc:
                            raise ValueError(f"{p}:{line_number}: invalid citation range: {exc}") from exc
                        if not (correct_end < near_start or near_end < correct_start):
                            raise ValueError(f"{p}:{line_number}: citation ranges overlap")
                        same_ref = r["correct_ref"] == r["near_miss_ref"]
                        if (r["near_miss_same_section"] == "כן") != same_ref:
                            raise ValueError(f"{p}:{line_number}: near-miss section flag disagrees with references")
                        if r["id"] in seen_in_file or r["id"] in rows:
                            raise ValueError(f"duplicate query ID {r['id']!r} across datasets or within file")
                        seen_in_file.add(r["id"])
                        file_rows.append(r)
            # Add a file only after every row in it passed basic checks.
            rows.update((r["id"], r) for r in file_rows)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"canonical dataset file {p!r} is invalid: {exc}") from exc
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="?")
    ap.add_argument("--template")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--data", default="datasets")
    a = ap.parse_args()
    if a.k < 1:
        ap.error("--k חייב להיות מספר חיובי")
    try:
        data = load_data(a.data)
    except (OSError, ValueError) as exc:
        ap.error(f"לא ניתן לטעון מערכי נתונים תקינים: {exc}")
    if a.template:
        try:
            with open(a.template, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["id", "type", "query", "smart_rank", "lexical_rank"])
                for i in sorted(data):
                    w.writerow([i, data[i].get("type", ""), data[i].get("query", ""), "", ""])
        except OSError as exc:
            ap.error(f"לא ניתן ליצור תבנית: {exc}")
        if not data:
            print("אזהרה: אין מערכי נתונים תקינים; התבנית לא תכיל שאילתות.", file=sys.stderr)
        print(f"נוצר {a.template} עם {len(data)} שורות")
        return
    if not a.results:
        ap.error("חסר קובץ תוצאות או --template")
    try:
        with open(a.results, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames or []
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        ap.error(f"לא ניתן לקרוא את קובץ התוצאות: {exc}")
    if not rows:
        ap.error("קובץ התוצאות ריק או מכיל כותרת בלבד; אין מה למדוד")
    if not data:
        ap.error("אין מערכי נתונים קנוניים להשוואת קובץ התוצאות")
    missing_columns = [field for field in ("id", "type", "query") if field not in fieldnames]
    if missing_columns:
        ap.error(f"קובץ התוצאות חסר עמודות נדרשות: {missing_columns}")
    modes = [c for c in fieldnames if c.endswith("_rank")]
    if not modes:
        ap.error("לא נמצאו עמודות דירוג בשמות המסתיימים ב-_rank")

    seen_ids = set()
    result_ids = []
    for row_number, row in enumerate(rows, 2):
        query_id = row.get("id")
        if not query_id:
            ap.error(f"ID חסר או ריק בשורת תוצאות {row_number}")
        if query_id in seen_ids:
            ap.error(f"ID כפול בקובץ התוצאות: {query_id!r}")
        seen_ids.add(query_id)
        result_ids.append(query_id)
        if query_id not in data:
            ap.error(f"ID לא מוכר בקובץ התוצאות: {query_id!r}")
            continue
        canonical = data[query_id]
        for field in ("type", "query"):
            if row.get(field) != canonical.get(field):
                ap.error(
                    f"השדה {field} של {query_id!r} אינו תואם למערך הקנוני"
                )
        measured_value = row.get("measured", "1")
        if measured_value not in {"0", "1"}:
            ap.error(f"measured חייב להיות 0 או 1 (שורה {row_number})")
    missing_ids = sorted(set(data) - seen_ids)
    if missing_ids:
        ap.error(f"קובץ התוצאות חסרים בו מזהי שאילתות: {missing_ids[:20]}")
    measured = [r for r in rows if r.get("measured", "1") != "0"]
    if not measured:
        ap.error("כל השורות הוחרגו מהמדידה; אין מה לחשב")
    for mode in modes:
        n = len(measured)
        try:
            ranks = []
            for row_no, row in enumerate(measured, 2):
                cell = row.get(mode, "")
                value = int(cell) if cell.strip() else None
                if value is not None and value < 1:
                    raise ValueError(f"rank must be positive (row {row_no}, column {mode})")
                ranks.append(value)
        except (ValueError, AttributeError) as exc:
            ap.error(f"דירוג לא תקין: {exc}")
        rec = sum(1 for x in ranks if x is not None and x <= a.k) / n
        mrr = sum(1 / x for x in ranks if x is not None) / n
        print(f"{mode}: Recall@{a.k} = {rec:.1%}   MRR = {mrr:.3f}   (n={n})")
        by = collections.defaultdict(list)
        for r, x in zip(measured, ranks):
            by[r.get("type", "?")].append(x)
        for t, xs in by.items():
            print(f"    {t}: Recall@{a.k} = {sum(1 for x in xs if x and x <= a.k) / len(xs):.1%} (n={len(xs)})")
    print("הערה: שורה ריקה נחשבת כ'לא נמצא'. כדי למדוד רק חלק מהשאילתות, הוסיפו עמודה measured עם 0 לשורות שלא נבדקו.")


if __name__ == "__main__":
    main()
