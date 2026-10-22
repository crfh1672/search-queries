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


def load_data(data_dir="datasets"):
    rows = {}
    # Only load the canonical file at datasets/<category>/<book>/<book>.jsonl.
    # Ignore nested examples, backups, and any alternate JSONL files.
    pattern = os.path.join(data_dir, "*", "*", "*.jsonl")
    for p in sorted(glob.glob(pattern)):
        if os.path.basename(p) != os.path.basename(os.path.dirname(p)) + ".jsonl":
            print(
                f"Warning: ignoring non-canonical JSONL file {p!r}; "
                "expected the file name to match its book directory",
                file=sys.stderr,
            )
            continue
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    rows[r["id"]] = r
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="?")
    ap.add_argument("--template")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--data", default="datasets")
    a = ap.parse_args()
    data = load_data(a.data)
    if a.template:
        with open(a.template, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "type", "query", "smart_rank", "lexical_rank"])
            for i in sorted(data):
                w.writerow([i, data[i]["type"], data[i]["query"], "", ""])
        print(f"נוצר {a.template} עם {len(data)} שורות")
        return
    if not a.results:
        ap.error("חסר קובץ תוצאות או --template")
    with open(a.results, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    modes = [c for c in rows[0] if c.endswith("_rank")]
    for mode in modes:
        measured = [r for r in rows if r.get("measured", "1") != "0"]
        n = len(measured)
        ranks = [int(r[mode]) if r[mode].strip() else None for r in measured]
        rec = sum(1 for x in ranks if x is not None and x <= a.k) / n
        mrr = sum(1 / x for x in ranks if x) / n
        print(f"{mode}: Recall@{a.k} = {rec:.1%}   MRR = {mrr:.3f}   (n={n})")
        by = collections.defaultdict(list)
        for r, x in zip(measured, ranks):
            by[r.get("type", "?")].append(x)
        for t, xs in by.items():
            print(f"    {t}: Recall@{a.k} = {sum(1 for x in xs if x and x <= a.k) / len(xs):.1%} (n={len(xs)})")
    print("הערה: שורה ריקה נחשבת כ'לא נמצא'. כדי למדוד רק חלק מהשאילתות, הוסיפו עמודה measured עם 0 לשורות שלא נבדקו.")


if __name__ == "__main__":
    main()
