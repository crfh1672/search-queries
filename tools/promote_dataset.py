#!/usr/bin/env python3
"""Promote a manually reviewed dataset from drafts/ into datasets/."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))
import validate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", help="path such as drafts/שות/שו״ת שער יוסף")
    parser.add_argument("--offline", action="store_true", help="use only the validated source cache")
    args = parser.parse_args()

    supplied_path = Path(args.draft)
    candidate = supplied_path if supplied_path.is_absolute() else Path.cwd() / supplied_path
    # Reject symlinks in the supplied path before resolving it, then check the
    # resolved location to prevent absolute paths and '..' from bypassing containment.
    if any(part.is_symlink() for part in (candidate, *candidate.parents)):
        parser.error("draft path must not traverse symlinks")
    try:
        source = candidate.resolve(strict=True)
    except OSError:
        parser.error("draft path must exist")
    try:
        relative = source.relative_to(REPO_ROOT.resolve())
    except ValueError:
        parser.error("draft path must be inside this repository")
    if len(relative.parts) != 3 or relative.parts[0] != "drafts":
        parser.error("expected drafts/<source-category>/<book-folder>")
    if any(entry.is_symlink() for entry in source.rglob("*")):
        parser.error("draft contents must not contain symlinks")

    errors = validate.validate_dataset(
        str(source), offline=args.offline, require_verified=True
    )
    if errors:
        print("הטיוטה לא הועברה; יש לתקן את השגיאות הבאות:")
        for error in errors:
            print(" -", error)
        return 1

    import json
    meta_path = source / f"{source.name}.מקור.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    destination = REPO_ROOT / "datasets" / meta["source_category"] / meta["book_name"]
    if destination.exists():
        print(f"לא ניתן להעביר: היעד כבר קיים: {destination}", file=sys.stderr)
        return 1

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    print(f"המערך אושר והועבר אל: {destination.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
