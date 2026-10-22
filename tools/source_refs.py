"""Build exact, hierarchical references from Otzaria's book headings.

Otzaria TXT books use one physical line per content unit and headings such as
<h1>Book</h1> and <h2>/<h3>/... for the table of contents. References here are
the visible heading path at a source line, not a Talmud-specific folio parser.
"""
from __future__ import annotations

import html
import re

import library  # imported from tools/ via the repository's scripts

HTML_HEADING_RE = re.compile(
    r"^\s*<h([1-6])\b[^>]*>(.*?)</h\1>\s*$", re.IGNORECASE
)
MARKDOWN_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$")
TAG_RE = re.compile(r"<[^>]*>")


def heading(line: str) -> tuple[int, str] | None:
    """Return (level, visible title) for a whole-line HTML/Markdown heading."""
    match = HTML_HEADING_RE.match(line)
    if match:
        level = int(match.group(1))
        title = html.unescape(TAG_RE.sub("", match.group(2)))
        title = library.norm(title)
        if not title:
            raise ValueError("empty heading")
        return level, title

    # Otzaria can recognize Markdown headings, although HTML headings are preferred.
    match = MARKDOWN_HEADING_RE.match(line)
    if match:
        level = len(match.group(1))
        title_text = library.norm(match.group(2))
        if not title_text:
            raise ValueError("empty heading")
        # The hash marks are retained because Otzaria's TOC parser retains them too.
        return level, ("#" * level) + " " + title_text
    return None


def line_references(lines: list[str]) -> list[str]:
    """Return a stable human-readable heading path for every 1-based source line.

    The <h1> book title is represented by metadata and omitted from the section
    path. A gap in heading levels intentionally starts a new path, matching the
    hierarchy rules documented by Otzaria's TOC parser.
    """
    stack: dict[int, tuple[str, ...]] = {}
    references: list[str] = []

    for number, line in enumerate(lines, 1):
        try:
            parsed = heading(line)
        except ValueError as exc:
            raise ValueError(f"malformed heading at source line {number}: {line!r}") from exc

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
            references.append(stack[max(stack)])
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
