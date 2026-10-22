"""Build the same human-readable heading paths used by Otzaria's TOC.

Otzaria treats a physical line beginning with <h1>...<h6> as a heading.
Its TOC title is the whole line with markup removed, not only the text between
opening and closing heading tags. Keep this behavior so stored references match
what users see in Otzaria.
"""
from __future__ import annotations

import re

HTML_HEADING_START_RE = re.compile(r"^\s*<h([1-6])\b([^>]*)", re.IGNORECASE)
TOC_EXCLUDE_RE = re.compile(r'\bdata-toc\s*=\s*["\']none["\']', re.IGNORECASE)
MARKDOWN_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$")


def heading(line: str) -> tuple[int, str] | None:
    """Return (level, visible title); excluded headings do not change the TOC path."""
    match = HTML_HEADING_START_RE.match(line)
    if match:
        if ">" not in line[:match.end() + 1]:
            raise ValueError("unterminated HTML heading tag")
        attrs = match.group(2)
        if TOC_EXCLUDE_RE.search(attrs):
            return None
        level = int(match.group(1))
        # Otzaria's parser extracts the complete line's text after stripping markup.
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", line)).strip()
        if not title:
            raise ValueError("empty heading")
        return level, title

    # Markdown headings are recognized by Otzaria, though markup is visible there.
    marker = re.match(r"^\s*(#{1,6})(?:\s|$)", line)
    if marker:
        match = MARKDOWN_HEADING_RE.match(line)
        if not match:
            raise ValueError("empty or malformed Markdown heading")
        level = len(match.group(1))
        title_text = " ".join(match.group(2).split())
        if not title_text:
            raise ValueError("empty Markdown heading")
        return level, ("#" * level) + " " + title_text
    return None


def line_reference_data(lines: list[str]) -> tuple[list[str], list[tuple]]:
    """Return visible heading paths and stable section IDs for every source line.

    Section IDs disambiguate repeated headings with the same visible path. They
    are internal validation aids; the stored reference remains human-readable.
    """
    stack: dict[int, tuple[str, ...]] = {}
    section_stack: dict[int, tuple] = {}
    references: list[str] = []
    section_ids: list[tuple] = []
    root_section_id: tuple = ("opening",)
    occurrence_counts: dict[tuple, int] = {}

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
                section_stack.clear()
                base_key = ("h1", title)
                occurrence_counts[base_key] = occurrence_counts.get(base_key, 0) + 1
                root_section_id = base_key + (occurrence_counts[base_key],)
                references.append("פתיחת הספר")
                section_ids.append(root_section_id)
                continue

            for old_level in [key for key in stack if key >= level]:
                del stack[old_level]
                section_stack.pop(old_level, None)

            # Preserve the nearest open ancestor even if the source skips a
            # heading level (for example h2 followed by h4).
            parent_level = max((key for key in stack if key < level), default=None)
            parent_path = stack[parent_level] if parent_level is not None else None
            parent_section = section_stack[parent_level] if parent_level is not None else root_section_id
            path = (parent_path + (title,)) if parent_path else (title,)
            base_key = (parent_section, level, title)
            occurrence_counts[base_key] = occurrence_counts.get(base_key, 0) + 1
            section_key = base_key + (occurrence_counts[base_key],)
            stack[level] = path
            section_stack[level] = section_key
            references.append(" > ".join(path))
            section_ids.append(section_key)
            continue

        if stack:
            active_level = max(stack)
            references.append(" > ".join(stack[active_level]))
            section_ids.append(section_stack[active_level])
        else:
            references.append("פתיחת הספר")
            section_ids.append(root_section_id)

    return references, section_ids


def line_references(lines: list[str]) -> list[str]:
    """Return the active visible heading path for every physical source line."""
    return line_reference_data(lines)[0]


def line_section_ids(lines: list[str]) -> list[tuple]:
    """Return internal section-boundary IDs for every physical source line."""
    return line_reference_data(lines)[1]


def reference_at_line(lines: list[str], line_no: int) -> str:
    """Return the heading path for a 1-based source line."""
    if line_no < 1 or line_no > len(lines):
        raise ValueError(f"line number {line_no} is outside source (1-{len(lines)})")
    return line_references(lines)[line_no - 1]


def span_reference(
    references: list[str],
    start: int,
    end: int,
    section_ids: list[tuple] | None = None,
) -> str:
    """Require a citation span to remain within one path and, if supplied, one section."""
    if start < 1 or end < start or end > len(references):
        raise ValueError(f"invalid citation span {start}-{end}")
    if section_ids is not None and len(section_ids) != len(references):
        raise ValueError("reference and section-ID arrays have different lengths")
    first = references[start - 1]
    first_section = section_ids[start - 1] if section_ids is not None else None
    for offset in range(start, end):
        if references[offset] != first:
            raise ValueError("citation crosses a heading boundary")
        if section_ids is not None and section_ids[offset] != first_section:
            raise ValueError("citation crosses a repeated-heading boundary")
    return first
