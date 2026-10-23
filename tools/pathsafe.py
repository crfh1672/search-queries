"""Small helpers for refusing symlinks and Windows junctions.

The datasets live in a git checkout that people edit locally, so the tools
simply refuse to read or write through a link. One implementation is shared by
every tool; keeping several copies in sync is how earlier review rounds kept
finding new inconsistencies.
"""
from __future__ import annotations

import os
from pathlib import Path


_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT


def _absolute(path) -> Path:
    """Absolute path that keeps '..' parts, so a link before '..' is still seen."""
    path = Path(path)
    return path if path.is_absolute() else Path.cwd() / path


def is_link(path) -> bool:
    """True for a symlink or, on Windows, a directory junction."""
    path = Path(path)
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None:
        return bool(is_junction())
    # Python < 3.12: on Windows a junction is a reparse point.
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & _REPARSE_POINT)


def link_component(path, root=None) -> Path | None:
    """Return the first link at or above *path*, or None.

    With *root*, the root itself and everything below it are inspected, but not
    its ancestors, so a symlinked home directory or temp dir above the checkout
    is not an error.
    """
    path = _absolute(path)
    if root is not None:
        root = _absolute(root)
        try:
            relative = path.relative_to(root)
        except ValueError:
            return path if is_link(path) else None
        current = root
        if is_link(current):
            return current
        for part in relative.parts:
            current = current / part
            if is_link(current):
                return current
        return None
    for component in (*reversed(path.parents), path):
        if is_link(component):
            return component
    return None


def links_in_tree(root) -> list[Path]:
    """List links inside *root* (and *root* itself) without following them."""
    root = Path(root)
    if is_link(root):
        return [root]
    if not root.is_dir():
        return []
    found: list[Path] = []

    def unreadable(error):  # an unreadable subtree could hide a link: fail closed
        raise error

    for current, dirs, files in os.walk(root, followlinks=False, onerror=unreadable):
        base = Path(current)
        for name in list(dirs):
            if is_link(base / name):
                found.append(base / name)
                dirs.remove(name)
        found.extend(base / name for name in files if is_link(base / name))
    return sorted(found)
