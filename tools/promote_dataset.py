#!/usr/bin/env python3
"""Move a human-verified draft from drafts/<category>/<book> to datasets/<category>/<book>.

The draft must pass full validation as an *approved* dataset: every record
carries a verifier listed in verifiers.txt, the source matches its pinned
SHA-256, and every citation resolves. Nothing is ever overwritten. The move is
a plain rename, git records it, and CI validates the result again in the pull
request, so this tool does not need to defend against concurrent local edits.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))
import pathsafe  # noqa: E402
import validate  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", help="path such as drafts/הלכה/שם הספר")
    parser.add_argument("--offline", action="store_true", help="use only the validated source cache")
    args = parser.parse_args(argv)

    root = Path(os.path.abspath(REPO_ROOT))
    draft = Path(os.path.abspath(args.draft))
    if pathsafe.link_component(draft, root) is not None:
        parser.error("draft path must not contain symlinks or junctions")
    try:
        relative = draft.relative_to(root)
    except ValueError:
        parser.error("draft path must be inside this repository")
    if not draft.is_dir():
        parser.error("draft path must be an existing directory")
    if len(relative.parts) != 3 or relative.parts[0] != "drafts":
        parser.error("expected drafts/<source-category>/<book-folder>")
    if pathsafe.links_in_tree(draft):
        parser.error("draft must not contain symlinks or junctions")

    category, book = relative.parts[1], relative.parts[2]
    destination = root / "datasets" / category / book
    if destination.exists() or pathsafe.is_link(destination):
        print(f"לא ניתן להעביר: היעד כבר קיים: {destination}", file=sys.stderr)
        return 1

    try:
        errors = validate.validate_dataset(str(draft), offline=args.offline, require_verified=True)
    except Exception as exc:  # the validator must never crash a promotion silently
        print(f"הטיוטה לא קודמה: הבודק נכשל ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1
    if errors:
        print("הטיוטה לא הועברה; יש לתקן את השגיאות הבאות:")
        for error in errors:
            print(" -", error)
        return 1

    try:
        collisions = validate.cross_dataset_errors(
            {draft, *validate.all_dataset_dirs(root)}
        )
    except OSError as exc:
        print(f"הטיוטה לא הועברה: לא ניתן לבדוק התנגשויות ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1
    if collisions:
        print("הטיוטה לא הועברה: התנגשות מזהים מול מערכים אחרים:")
        for error in collisions:
            print(" -", error)
        return 1

    try:
        meta = json.loads((draft / f"{book}.מקור.json").read_text(encoding="utf-8"))
        for key, folder in (("source_category", category), ("book_name", book)):
            if meta.get(key) != folder:
                raise ValueError(f"folder {folder!r} does not match metadata {key} {meta.get(key)!r}")
    except (OSError, ValueError, AttributeError) as exc:
        print(f"לא ניתן לקבוע יעד תקין למערך: {exc}", file=sys.stderr)
        return 1

    parent = destination.parent
    if pathsafe.link_component(parent, root) is not None:
        print(f"הקידום בוטל: {parent} מכיל קישור סמלי", file=sys.stderr)
        return 1
    try:
        parent.mkdir(parents=True, exist_ok=True)
        if pathsafe.link_component(parent, root) is not None:
            print(f"הקידום בוטל: {parent} מכיל קישור סמלי", file=sys.stderr)
            return 1
        if destination.exists():
            print(f"לא ניתן להעביר: היעד כבר קיים: {destination}", file=sys.stderr)
            return 1
        os.rename(draft, destination)
    except OSError as exc:
        print(f"הקידום בוטל: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"המערך אומת והועבר אל: {destination.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
