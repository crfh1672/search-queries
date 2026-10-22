#!/usr/bin/env python3
"""Promote a manually reviewed dataset from drafts/ into datasets/."""
from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))
import validate


def directory_open_flags() -> int:
    """Open a real directory without following a final-component symlink where supported."""
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def same_directory(left, right) -> bool:
    return (
        stat.S_ISDIR(left.st_mode)
        and stat.S_ISDIR(right.st_mode)
        and left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
    )


def reject_symlink_entries(source: Path, parser: argparse.ArgumentParser) -> None:
    if any(entry.is_symlink() for entry in source.rglob("*")):
        parser.error("draft contents must not contain symlinks")


def atomic_promote(source: Path, destination: Path, verified_stat) -> None:
    """Rename the verified directory entry atomically without following its name as a symlink."""
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"destination already exists: {destination}")

    destination_parent = destination.parent.resolve()
    try:
        destination_parent.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("destination directory resolves outside this repository") from exc

    # dir_fd-based rename keeps both parent directories anchored and renames the
    # source entry itself; it never traverses a replacement symlink at the leaf.
    if os.rename in getattr(os, "supports_dir_fd", set()) and os.stat in getattr(os, "supports_dir_fd", set()):
        source_parent_fd = os.open(source.parent, directory_open_flags())
        destination_parent_fd = os.open(destination_parent, directory_open_flags())
        try:
            current = os.stat(source.name, dir_fd=source_parent_fd, follow_symlinks=False)
            if not same_directory(current, verified_stat):
                raise RuntimeError("draft directory changed during validation; promotion cancelled")
            os.rename(
                source.name,
                destination.name,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=destination_parent_fd,
            )
            moved = os.stat(destination.name, dir_fd=destination_parent_fd, follow_symlinks=False)
            if not same_directory(moved, verified_stat):
                # If a concurrent change replaced the source entry, restore the
                # unexpected entry rather than accepting it as the approved draft.
                try:
                    os.stat(source.name, dir_fd=source_parent_fd, follow_symlinks=False)
                    source_is_absent = False
                except FileNotFoundError:
                    source_is_absent = True
                if source_is_absent:
                    os.rename(
                        destination.name,
                        source.name,
                        src_dir_fd=destination_parent_fd,
                        dst_dir_fd=source_parent_fd,
                    )
                raise RuntimeError("draft entry changed during atomic promotion; entry was not approved")
        finally:
            os.close(source_parent_fd)
            os.close(destination_parent_fd)
        return

    # Portable fallback (including platforms without dir_fd rename support):
    current = source.lstat()
    if source.is_symlink() or not same_directory(current, verified_stat):
        raise RuntimeError("draft directory changed during validation; promotion cancelled")
    os.rename(source, destination)
    moved = destination.lstat()
    if not same_directory(moved, verified_stat):
        if not source.exists() and not source.is_symlink():
            os.rename(destination, source)
        raise RuntimeError("draft entry changed during atomic promotion; entry was not approved")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", help="path such as drafts/שות/שו״ת שער יוסף")
    parser.add_argument("--offline", action="store_true", help="use only the validated source cache")
    args = parser.parse_args()

    supplied_path = Path(args.draft)
    candidate = supplied_path if supplied_path.is_absolute() else Path.cwd() / supplied_path
    # Check the user-supplied path before resolving it, then require the resolved
    # path to stay in this repository.
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

    try:
        source_fd = os.open(source, directory_open_flags())
    except OSError as exc:
        parser.error(f"draft must be a real directory and must not be a symlink: {exc}")
    try:
        verified_stat = os.fstat(source_fd)
        if not stat.S_ISDIR(verified_stat.st_mode):
            parser.error("draft must be a directory")
        reject_symlink_entries(source, parser)

        errors = validate.validate_dataset(
            str(source), offline=args.offline, require_verified=True
        )
        if errors:
            print("הטיוטה לא הועברה; יש לתקן את השגיאות הבאות:")
            for error in errors:
                print(" -", error)
            return 1

        # Re-scan after validation to catch symlink entries added while checking.
        reject_symlink_entries(source, parser)
        current_stat = source.lstat()
        if not same_directory(current_stat, verified_stat):
            parser.error("draft directory changed during validation; promotion cancelled")

        import json
        meta_path = source / f"{source.name}.מקור.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        destination = REPO_ROOT / "datasets" / meta["source_category"] / meta["book_name"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_promote(source, destination, verified_stat)
        print(f"המערך אושר והועבר אל: {destination.relative_to(REPO_ROOT)}")
        return 0
    finally:
        os.close(source_fd)


if __name__ == "__main__":
    raise SystemExit(main())
