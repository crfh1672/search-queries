#!/usr/bin/env python3
"""בדיקה אם הקובץ בספריית אוצריא השתנה מאז הקומיט הנעוץ, ואילו שאילתות מושפעות.

    python tools/fetch_source.py taanit             # משווה ל-main
    python tools/fetch_source.py taanit --ref <sha>  # משווה לקומיט אחר

משווים שורה מול שורה אחרי ניקוי (בלי ניקוד, תגיות HTML ושם השם המפורש).
אם אין הבדל בשורות שהשאילתות נוגעות בהן, אפשר להמשיך לעבוד על הקומיט הנעוץ בלי לשנות כלום.
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import library


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--ref", default="main")
    a = ap.parse_args()
    d = os.path.join("datasets", a.dataset)
    with open(os.path.join(d, "source.json"), encoding="utf-8") as f:
        meta = json.load(f)
    pinned, why = library.get_pinned(a.dataset, meta)
    if why:
        sys.exit(f"קובץ הקומיט הנעוץ: {why}")
    print("מושך:", library.raw_url(meta, a.ref))
    other = library.fetch(meta, a.ref)
    P = [library.norm(l) for l in pinned.decode("utf-8").split("\n")]
    O = [library.norm(l) for l in other.decode("utf-8").split("\n")]
    print(f"שורות בקומיט הנעוץ: {len(P)}, ב-{a.ref}: {len(O)}")
    if len(P) != len(O):
        print(f"הבדל במספר השורות: {len(O) - len(P):+d}. מספרי השורות אחרי נקודת ההבדל עלולים לזוז")
    diff = [i + 1 for i, (x, y) in enumerate(zip(P, O)) if x != y]
    print(f"שורות שונות: {len(diff)}", diff[:20])
    touched = set()
    with open(os.path.join(d, "queries.jsonl"), encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            for k in ("correct_line", "near_miss_line"):
                lo, _, hi = r[k].partition("-")
                if any(int(lo) <= x <= int(hi or lo) for x in diff):
                    touched.add(r["id"])
    if touched:
        print("שאילתות שהשורות שלהן השתנו:", sorted(touched))
    else:
        print("אף שאילתה אינה נוגעת בשורות שהשתנו.")
    sys.exit(1 if touched or len(P) != len(O) else 0)


if __name__ == "__main__":
    main()
