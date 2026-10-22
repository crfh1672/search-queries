#!/usr/bin/env python3
"""Compare a pinned Otzaria book with another commit and list affected queries.

Examples:
    python tools/fetch_source.py "datasets/שות/שו״ת שער יוסף"
    python tools/fetch_source.py "שו״ת שער יוסף" --ref main
"""
import argparse, json, sys
from itertools import zip_longest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))
import library
import source_refs


def resolve_dataset(value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = (REPO_ROOT / candidate).resolve()
    if candidate.is_dir() and (candidate / f"{candidate.name}.מקור.json").is_file():
        return candidate

    matches = []
    for root_name in ("datasets", "drafts"):
        root = REPO_ROOT / root_name
        if root.exists():
            matches.extend(
                path.parent for path in root.rglob("*.מקור.json")
                if path.parent.name == value
            )
    matches = sorted(set(matches))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise SystemExit(f"שם ספר עמום; ספק נתיב מלא. נמצאו: {matches}")
    raise SystemExit(f"לא נמצא מערך בשם או בנתיב: {value}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="dataset path, or unique book folder name")
    parser.add_argument("--ref", default="main")
    args = parser.parse_args()

    directory = resolve_dataset(args.dataset)
    name = directory.name
    meta_path = directory / f"{name}.מקור.json"
    with meta_path.open(encoding="utf-8") as handle:
        meta = json.load(handle)
    try:
        library.validate_source_origin(meta)
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"מקור לא תקין: {exc}") from exc

    pinned, why = library.get_pinned(name, meta)
    if why:
        raise SystemExit(f"קובץ המקור הנעוץ: {why}")
    print("מושך:", library.raw_url(meta, args.ref))
    other = library.fetch(meta, args.ref)
    old_raw_lines = pinned.decode("utf-8").split("\n")
    new_raw_lines = other.decode("utf-8").split("\n")
    old_lines = [library.norm(line) for line in old_raw_lines]
    new_lines = [library.norm(line) for line in new_raw_lines]
    old_refs = source_refs.line_references(old_raw_lines)
    new_refs = source_refs.line_references(new_raw_lines)
    print(f"שורות בקומיט הנעוץ: {len(old_lines)}, ב-{args.ref}: {len(new_lines)}")
    if len(old_lines) != len(new_lines):
        print(f"הבדל במספר השורות: {len(new_lines) - len(old_lines):+d}. מספרי השורות בהמשך עלולים לזוז")
    missing = object()
    diff = [
        i + 1
        for i, (old, new, old_ref, new_ref) in enumerate(
            zip_longest(old_lines, new_lines, old_refs, new_refs, fillvalue=missing)
        )
        if old != new or old_ref != new_ref
    ]
    print(f"שורות שונות (כולל שינויי כותרות): {len(diff)}", diff[:20])

    touched = set()
    jsonl_path = directory / f"{name}.jsonl"
    with jsonl_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            for key in ("correct_line", "near_miss_line"):
                lo, _, hi = row[key].partition("-")
                if any(int(lo) <= line_no <= int(hi or lo) for line_no in diff):
                    touched.add(row["id"])
    if touched:
        print("שאילתות שהשורות שלהן השתנו:", sorted(touched))
    else:
        print("אף שאילתה אינה נוגעת בשורות שהשתנו.")
    raise SystemExit(1 if touched or len(old_lines) != len(new_lines) else 0)


if __name__ == "__main__":
    main()
