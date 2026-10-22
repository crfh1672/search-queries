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


def is_path_link(path):
    path = os.path.abspath(path)
    current = path
    while True:
        candidate = Path(current)
        if candidate.is_symlink():
            return True
        is_junction = getattr(candidate, "is_junction", None)
        if is_junction and is_junction():
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def load_data(data_dir="datasets"):
    rows = {}
    root = os.path.abspath(data_dir)
    if is_path_link(root):
        print(f"Warning: refusing to read through a symlink or junction: {root!r}", file=sys.stderr)
        return rows
    # Only load the canonical file at datasets/<category>/<book>/<book>.jsonl.
    # Ignore nested examples, backups, and any alternate JSONL files.
    pattern = os.path.join(root, "*", "*", "*.jsonl")
    for p in sorted(glob.glob(pattern)):
        if is_path_link(p):
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
            with open(p, encoding="utf-8") as f:
                for line_number, line in enumerate(f, 1):
                    if line.strip():
                        r = json.loads(line)
                        if not isinstance(r, dict) or not isinstance(r.get("id"), str):
                            raise ValueError(f"{p}:{line_number}: each record must be an object with a string id")
                        if r["id"] in rows:
                            raise ValueError(f"duplicate query ID {r['id']!r} across datasets")
                        rows[r["id"]] = r
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            print(f"Warning: failed to load {p!r}: {exc}", file=sys.stderr)
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
    data = load_data(a.data)
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
    modes = [c for c in fieldnames if c.endswith("_rank")]
    if not modes:
        ap.error("לא נמצאו עמודות דירוג בשמות המסתיימים ב-_rank")
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
