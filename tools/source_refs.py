"""Build the same human-readable heading paths used by Otzaria's TOC.

Otzaria treats a physical line beginning with <h1>...<h6> as a heading.
Its TOC title is the whole line with markup removed, not only the text between
opening and closing heading tags. Keep this behavior so stored references match
what users see in Otzaria.
"""
from __future__ import annotations

import re

import library

HTML_HEADING_START_RE = re.compile(r"^\s*<h([1-6])\b([^>]*)", re.IGNORECASE)
TOC_EXCLUDE_RE = re.compile(r'\bdata-toc\s*=\s*["\']none["\']', re.IGNORECASE)
MARKDOWN_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$")


def heading(line: str) -> tuple[int, str] | None:
    """Return (level, visible title); excluded headings do not change the TOC path."""
    match = HTML_HEADING_START_RE.match(line)
    if match:
        attrs = match.group(2)
        if TOC_EXCLUDE_RE.search(attrs):
            return None
        level = int(match.group(1))
        # Otzaria's parser extracts the complete line's text after stripping markup.
        title = library.norm(line)
        if not title:
            raise ValueError("empty heading")
        return level, title

    # Markdown headings are recognized by Otzaria, though markup is visible there.
    match = MARKDOWN_HEADING_RE.match(line)
    if match:
        level = len(match.group(1))
        title_text = library.norm(match.group(2))
        if not title_text:
            raise ValueError("empty heading")
        return level, ("#" * level) + " " + title_text
    return None


def line_references(lines: list[str]) -> list[str]:
    """Return the active TOC heading path for every physical source line."""
    stack: dict[int, tuple[str, ...]] = {}
    references: list[str] = []

    for number, line in enumerate(lines, 1):
        try:
            parsed = heading(line)
        except ValueError as exc:
            raise ValueError(
                f"malformed heading at source line {number}: {line!r}"
            ) from exc

        if parsed is not None:
            level, title = parsed
            if level == 1:
                stack.clear()
                references.append("פתיחת הספר")
                continue

            for old_level in [key for key in stack if key >= level]:
                del stack[old_level]

            parent_path = stack.get(level - 1)
            path = (parent_path + (title,)) if parent_path else (title,)
            stack[level] = path
            references.append(" > ".join(path))
            continue

        if stack:
            references.append(" > ".join(stack[max(stack)]))
        else:
            references.append("פתיחת הספר")

    return references


def reference_at_line(lines: list[str], line_no: int) -> str:
    """Return the heading path for a 1-based source line."""
    if line_no < 1 or line_no > len(lines):
        raise ValueError(f"line number {line_no} is outside source (1-{len(lines)})")
    return line_references(lines)[line_no - 1]


def span_reference(references: list[str], start: int, end: int) -> str:
    """Require a citation span to remain within one heading path."""
    if start < 1 or end < start or end > len(references):
        raise ValueError(f"invalid citation span {start}-{end}")
    first = references[start - 1]
    if any(ref != first for ref in references[start:end]):
        raise ValueError("citation crosses a heading boundary")
    return first
