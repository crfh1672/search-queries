#!/usr/bin/env python3
"""Compare a pinned Otzaria book with another commit and list affected queries.

Examples:
    python tools/fetch_source.py "datasets/שות/שו״ת שער יוסף"
    python tools/fetch_source.py "שו״ת שער יוסף" --ref main
"""
import argparse, json, os, re, sys
from itertools import zip_longest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))
import library
import pathsafe
import source_refs
import validate


def path_has_link_component(path: Path) -> Path | None:
    """Reject links inside the checkout, but ignore OS-level ancestors above it."""
    return pathsafe.link_component(path, REPO_ROOT)


def reject_link_tree(root: Path) -> None:
    if path_has_link_component(root) is not None:
        raise SystemExit(f"נתיב המערך מכיל symlink או junction: {root}")
    for link in pathsafe.links_in_tree(root):
        raise SystemExit(f"המערך מכיל symlink או junction: {link}")


def resolve_dataset(value: str) -> Path:
    supplied = Path(value)
    candidate = supplied if supplied.is_absolute() else REPO_ROOT / supplied
    candidate = Path(os.path.abspath(candidate))
    if path_has_link_component(candidate) is not None:
        raise SystemExit(f"נתיב המערך מכיל symlink או junction: {candidate}")
    try:
        resolved_candidate = candidate.resolve(strict=True)
    except (OSError, ValueError):
        # Missing paths (including explicit in-repository paths) should fall
        # through to the normal "not found" lookup message.
        resolved_candidate = None
    if resolved_candidate is not None:
        try:
            resolved_candidate.relative_to(REPO_ROOT.resolve(strict=True))
        except ValueError:
            if candidate.exists():
                raise SystemExit("נתיב המערך חייב להיות בתוך המאגר")
        else:
            candidate = resolved_candidate

    if candidate.is_dir() and (candidate / f"{candidate.name}.מקור.json").is_file():
        reject_link_tree(candidate)
        meta_path = candidate / f"{candidate.name}.מקור.json"
        if pathsafe.is_link(meta_path) or not meta_path.is_file():
            raise SystemExit(f"קובץ המקור חסר או אינו קובץ רגיל: {meta_path}")
        return candidate.resolve(strict=True)

    matches = []
    for root_name in ("datasets", "drafts"):
        root = REPO_ROOT / root_name
        if pathsafe.is_link(root):
            raise SystemExit(f"תיקיית {root_name} אינה יכולה להיות symlink או junction")
        if root.exists():
            for current, dirs, files in os.walk(root, followlinks=False):
                base = Path(current)
                dirs[:] = [name for name in dirs if not pathsafe.is_link(base / name)]
                for name in files:
                    if not name.endswith(".מקור.json") or pathsafe.is_link(base / name):
                        continue
                    if base.name == value:
                        matches.append(base)
    matches = sorted(set(matches))
    if len(matches) == 1:
        reject_link_tree(matches[0])
        return matches[0].resolve(strict=True)
    if len(matches) > 1:
        raise SystemExit(f"שם ספר עמום; ספק נתיב מלא. נמצאו: {matches}")
    raise SystemExit(f"לא נמצא מערך בשם או בנתיב: {value}")


def compare_source_lines(pinned: bytes, other: bytes):
    """Return normalized lines and changed 1-based line numbers, including heading-only edits."""
    old_raw_lines = pinned.decode("utf-8").split("\n")
    new_raw_lines = other.decode("utf-8").split("\n")
    old_lines = [library.norm(line) for line in old_raw_lines]
    new_lines = [library.norm(line) for line in new_raw_lines]
    old_refs, old_sections = source_refs.line_reference_data(old_raw_lines)
    new_refs, new_sections = source_refs.line_reference_data(new_raw_lines)
    missing = object()
    diff = [
        i + 1
        for i, (old, new, old_ref, new_ref, old_section, new_section) in enumerate(
            zip_longest(
                old_lines, new_lines, old_refs, new_refs, old_sections, new_sections,
                fillvalue=missing,
            )
        )
        if old != new or old_ref != new_ref or old_section != new_section
    ]
    return old_lines, new_lines, diff


def touched_query_ids(jsonl_path: Path, diff: list[int]) -> set[str]:
    """Load a canonical dataset JSONL and return IDs whose citations overlap changed lines."""
    touched: set[str] = set()
    try:
        with jsonl_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                row = json.loads(line, object_pairs_hook=validate.unique_json_object)
                if not isinstance(row, dict) or list(row.keys()) != validate.FIELDS:
                    raise ValueError(f"JSONL row {line_number} does not match the 12-field schema")
                if any(not isinstance(row[field], str) for field in validate.FIELDS):
                    raise ValueError(f"JSONL row {line_number} contains a non-string field")
                if not row["id"]:
                    raise ValueError(f"JSONL row {line_number} has an empty ID")

                for key in ("correct_line", "near_miss_line"):
                    value = row[key]
                    if not validate.LINE_RE.fullmatch(value):
                        raise ValueError(f"invalid line range {value!r} at row {line_number}")
                    start_text, _, end_text = value.partition("-")
                    start = int(start_text)
                    end = int(end_text or start_text)
                    if start < 1 or end < start:
                        raise ValueError(f"invalid line range {value!r} at row {line_number}")
                    if any(start <= line_no <= end for line_no in diff):
                        touched.add(row["id"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"קובץ השאילתות אינו תקין: {exc}") from exc
    return touched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="dataset path, or unique book folder name")
    parser.add_argument("--ref", default="main")
    args = parser.parse_args()

    directory = resolve_dataset(args.dataset)
    name = directory.name
    meta_path = directory / f"{name}.מקור.json"
    try:
        with meta_path.open(encoding="utf-8") as handle:
            meta = json.load(handle, object_pairs_hook=validate.unique_json_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"קובץ המטא־נתונים אינו תקין: {exc}") from exc
    if not isinstance(meta, dict):
        raise SystemExit("קובץ המטא־נתונים חייב להכיל אובייקט JSON")
    try:
        library.validate_source_origin(meta)
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"מקור לא תקין: {exc}") from exc

    pinned, why = library.get_pinned(name, meta)
    if why:
        raise SystemExit(f"קובץ המקור הנעוץ: {why}")
    print("מושך:", library.raw_url(meta, args.ref))
    try:
        other = library.fetch(meta, args.ref)
        old_lines, new_lines, diff = compare_source_lines(pinned, other)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SystemExit(f"לא ניתן להשוות את מבנה המקור: {exc}") from exc
    except Exception as exc:
        raise SystemExit(f"לא ניתן למשוך את המקור ב-ref {args.ref!r}: {exc}") from exc
    print(f"שורות בקומיט הנעוץ: {len(old_lines)}, ב-{args.ref}: {len(new_lines)}")
    if len(old_lines) != len(new_lines):
        print(f"הבדל במספר השורות: {len(new_lines) - len(old_lines):+d}. מספרי השורות בהמשך עלולים לזוז")
    print(f"שורות שונות (כולל שינויי כותרות): {len(diff)}", diff[:20])

    jsonl_path = directory / f"{name}.jsonl"
    touched = touched_query_ids(jsonl_path, diff)
    if touched:
        print("שאילתות שהשורות שלהן השתנו:", sorted(touched))
    else:
        print("אף שאילתה אינה נוגעת בשורות שהשתנו.")
    raise SystemExit(1 if touched or len(old_lines) != len(new_lines) else 0)


if __name__ == "__main__":
    main()
