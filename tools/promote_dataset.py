#!/usr/bin/env python3
"""Promote a validated, human-reviewed snapshot from drafts/ into datasets/."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))
import validate


def is_path_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def directory_open_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def file_signature(info):
    return (
        info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode),
        info.st_size, info.st_mtime_ns, info.st_ctime_ns,
    )


def is_same_directory(left, right) -> bool:
    return (
        stat.S_ISDIR(left.st_mode)
        and stat.S_ISDIR(right.st_mode)
        and left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
    )


def source_files_supported_by_dir_fd() -> bool:
    supported = getattr(os, "supports_dir_fd", set())
    return (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and all(func in supported for func in (os.open, os.mkdir, os.stat, os.rename))
    )


def read_stable_regular_file(path: Path) -> bytes:
    before = path.lstat()
    if is_path_link(path) or stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError(f"only regular files are allowed in a draft: {path}")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or file_signature(opened) != file_signature(before):
            raise ValueError(f"draft file changed while opening: {path}")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        if file_signature(after) != file_signature(opened):
            raise ValueError(f"draft file changed while being copied: {path}")
        return b"".join(chunks)
    finally:
        os.close(fd)


def copy_tree_snapshot(source: Path, target: Path) -> tuple[os.stat_result, dict[str, str]]:
    """Copy an ordinary directory tree into private staging, rejecting links/special files."""
    root_before = source.lstat()
    if is_path_link(source) or stat.S_ISLNK(root_before.st_mode) or not stat.S_ISDIR(root_before.st_mode):
        raise ValueError("draft must be a real directory, not a symlink")

    manifest: dict[str, str] = {}

    def copy_contents(src_dir: Path, dst_dir: Path, prefix: str = "") -> None:
        before = src_dir.lstat()
        if is_path_link(src_dir) or stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            raise ValueError(f"draft directory changed or is not a directory: {src_dir}")
        before_names = sorted(p.name for p in src_dir.iterdir())

        for name in before_names:
            src = src_dir / name
            dst = dst_dir / name
            info = src.lstat()
            if is_path_link(src) or stat.S_ISLNK(info.st_mode):
                raise ValueError(f"draft contents must not contain symlinks: {src}")
            relative = f"{prefix}/{name}" if prefix else name
            if stat.S_ISDIR(info.st_mode):
                dst.mkdir(mode=0o700)
                copy_contents(src, dst, relative)
            elif stat.S_ISREG(info.st_mode):
                data = read_stable_regular_file(src)
                with dst.open("xb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                manifest[relative] = hashlib.sha256(data).hexdigest()
            else:
                raise ValueError(f"draft contains a non-regular file: {src}")

        after_names = sorted(p.name for p in src_dir.iterdir())
        after = src_dir.lstat()
        if before_names != after_names or file_signature(before) != file_signature(after):
            raise ValueError(f"draft directory changed while being copied: {src_dir}")

    target.mkdir(mode=0o700)
    copy_contents(source, target)
    root_after = source.lstat()
    if file_signature(root_before) != file_signature(root_after):
        raise ValueError("draft directory changed while being copied")
    return root_before, manifest


def tree_fingerprint(root: Path) -> dict[str, str]:
    """Hash every regular file without traversing symlinks; fail if the tree is changing."""
    result: dict[str, str] = {}

    def walk(directory: Path, prefix: str = "") -> None:
        before = directory.lstat()
        if is_path_link(directory) or stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
            raise ValueError(f"not a real directory: {directory}")
        names = sorted(p.name for p in directory.iterdir())
        for name in names:
            path = directory / name
            info = path.lstat()
            relative = f"{prefix}/{name}" if prefix else name
            if is_path_link(path) or stat.S_ISLNK(info.st_mode):
                raise ValueError(f"symlink encountered: {path}")
            if stat.S_ISDIR(info.st_mode):
                walk(path, relative)
            elif stat.S_ISREG(info.st_mode):
                result[relative] = hashlib.sha256(read_stable_regular_file(path)).hexdigest()
            else:
                raise ValueError(f"non-regular file encountered: {path}")
        if names != sorted(p.name for p in directory.iterdir()):
            raise ValueError(f"directory changed while reading: {directory}")
        if file_signature(before) != file_signature(directory.lstat()):
            raise ValueError(f"directory changed while reading: {directory}")

    walk(root)
    return result


def open_or_create_directory_at(parent_fd: int, name: str) -> int:
    flags = directory_open_flags()
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, mode=0o755, dir_fd=parent_fd)
        except FileExistsError:
            # A concurrent creator is accepted only if the following open
            # proves that the entry is a real directory, not a symlink.
            pass
        return os.open(name, flags, dir_fd=parent_fd)


def ensure_safe_destination_parent(parent: Path) -> None:
    """Portable path-based fallback; check each component before creating it."""
    repo_root = REPO_ROOT.resolve(strict=True)
    try:
        relative = parent.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("destination directory resolves outside this repository") from exc

    current = repo_root
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise ValueError("invalid destination path component")
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            current.mkdir()
            info = current.lstat()
        if is_path_link(current) or stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"destination component must be a real directory: {current}")
        try:
            current.resolve(strict=True).relative_to(repo_root)
        except ValueError as exc:
            raise ValueError(f"destination component resolves outside repository: {current}") from exc


def atomic_promote(source: Path, destination: Path, verified_stat, expected_manifest: dict[str, str]) -> None:
    """Atomically install the validated staging snapshot, refusing symlinked parents."""
    repo_root = REPO_ROOT.resolve(strict=True)
    if destination.parent != repo_root / "datasets" / destination.parent.name:
        raise ValueError("unexpected dataset destination layout")

    if source_files_supported_by_dir_fd():
        root_fd = os.open(repo_root, directory_open_flags())
        opened_fds = [root_fd]
        try:
            datasets_fd = open_or_create_directory_at(root_fd, "datasets")
            opened_fds.append(datasets_fd)
            category_fd = open_or_create_directory_at(datasets_fd, destination.parent.name)
            opened_fds.append(category_fd)
            staging_fd = os.open(source.parent.name, directory_open_flags(), dir_fd=root_fd)
            opened_fds.append(staging_fd)

            current = os.stat(source.name, dir_fd=staging_fd, follow_symlinks=False)
            if not is_same_directory(current, verified_stat):
                raise RuntimeError("staging directory changed; promotion cancelled")
            try:
                os.stat(destination.name, dir_fd=category_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(f"destination already exists: {destination}")

            os.rename(
                source.name, destination.name,
                src_dir_fd=staging_fd, dst_dir_fd=category_fd,
            )
            moved = os.stat(destination.name, dir_fd=category_fd, follow_symlinks=False)
            if not is_same_directory(moved, verified_stat):
                try:
                    os.stat(source.name, dir_fd=staging_fd, follow_symlinks=False)
                except FileNotFoundError:
                    os.rename(
                        destination.name, source.name,
                        src_dir_fd=category_fd, dst_dir_fd=staging_fd,
                    )
                raise RuntimeError("moved directory identity changed; promotion rolled back")
        finally:
            for fd in reversed(opened_fds):
                os.close(fd)
    else:
        ensure_safe_destination_parent(destination.parent)
        if destination.exists() or is_path_link(destination):
            raise FileExistsError(f"destination already exists: {destination}")
        if is_path_link(source) or not is_same_directory(source.lstat(), verified_stat):
            raise RuntimeError("staging directory changed; promotion cancelled")
        os.rename(source, destination)
        moved = destination.lstat()
        if not is_same_directory(moved, verified_stat):
            if not source.exists() and not is_path_link(source):
                os.rename(destination, source)
            raise RuntimeError("moved directory identity changed; promotion rolled back")

    if tree_fingerprint(destination) != expected_manifest:
        # The staging directory is private, but verify the installed content too.
        # Restore it to staging if anything changed during the atomic rename.
        try:
            os.rename(destination, source)
        except OSError:
            pass
        raise RuntimeError("installed snapshot differs from validated content; promotion rolled back")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", help="path such as drafts/הלכה/שם הספר")
    parser.add_argument("--offline", action="store_true", help="use only the validated source cache")
    args = parser.parse_args()

    supplied = Path(args.draft)
    candidate = supplied if supplied.is_absolute() else Path.cwd() / supplied
    if any(is_path_link(part) for part in (candidate, *candidate.parents)):
        parser.error("draft path must not traverse symlinks")
    try:
        source = candidate.resolve(strict=True)
    except OSError:
        parser.error("draft path must exist")
    try:
        relative = source.relative_to(REPO_ROOT.resolve(strict=True))
    except ValueError:
        parser.error("draft path must be inside this repository")
    if len(relative.parts) != 3 or relative.parts[0] != "drafts":
        parser.error("expected drafts/<source-category>/<book-folder>")

    try:
        source_info = source.lstat()
        if is_path_link(source) or stat.S_ISLNK(source_info.st_mode) or not stat.S_ISDIR(source_info.st_mode):
            parser.error("draft must be a real directory, not a symlink")
        # Catch symlinks before snapshotting to provide a direct explanation.
        tree_fingerprint(source)
    except (OSError, ValueError) as exc:
        parser.error(f"draft tree is unsafe or unreadable: {exc}")

    staging_root = Path(tempfile.mkdtemp(prefix=".promotion-staging-", dir=REPO_ROOT.resolve()))
    try:
        staged = staging_root / source.name
        try:
            original_info, manifest = copy_tree_snapshot(source, staged)
        except (OSError, ValueError) as exc:
            parser.error(f"cannot snapshot draft safely: {exc}")

        try:
            validation_errors = validate.validate_dataset(
                str(staged), offline=args.offline, require_verified=True
            )
        except Exception as exc:
            print(f"הטיוטה לא קודמה: הבודק נכשל ({type(exc).__name__}: {exc})", file=sys.stderr)
            return 1
        if validation_errors:
            print("הטיוטה לא הועברה; יש לתקן את השגיאות הבאות:")
            for error in validation_errors:
                print(" -", error)
            return 1

        if tree_fingerprint(staged) != manifest:
            print("הטיוטה הזמנית השתנתה אחרי הבדיקה; הקידום בוטל.", file=sys.stderr)
            return 1

        meta_path = staged / f"{staged.name}.מקור.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            destination = REPO_ROOT / "datasets" / meta["source_category"] / meta["book_name"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f"לא ניתן לקבוע יעד תקין למערך: {exc}", file=sys.stderr)
            return 1

        try:
            staged_info = staged.lstat()
            atomic_promote(staged, destination, staged_info, manifest)
        except FileExistsError:
            print(f"לא ניתן להעביר: היעד כבר קיים: {destination}", file=sys.stderr)
            return 1
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"הקידום בוטל מטעמי בטיחות: {exc}", file=sys.stderr)
            return 1

        # Remove the original draft only if it still contains exactly the
        # bytes captured in the validated snapshot. Otherwise preserve it.
        try:
            if is_same_directory(source.lstat(), original_info) and tree_fingerprint(source) == manifest:
                shutil.rmtree(source)
            else:
                print(
                    f"אזהרה: הטיוטה השתנתה בזמן הקידום ולכן נשמרה לבדיקה: {source}",
                    file=sys.stderr,
                )
        except (OSError, ValueError):
            print(f"אזהרה: לא ניתן היה לוודא שהטיוטה המקורית לא השתנתה; היא נשמרה: {source}", file=sys.stderr)

        print(f"המערך אומת והועבר אל: {destination.relative_to(REPO_ROOT.resolve())}")
        return 0
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
