"""Build the same human-readable heading paths used by Otzaria's TOC.

Otzaria builds a book's table of contents only from physical lines that start
with ``<h1>`` ... ``<h6>`` (see ``otzaria-book-format`` in Otzaria/otzaria-library).
Its TOC title is the whole line with markup removed. Markdown ``#`` lines are
ordinary body text there, so they are ordinary body text here too.

Rules:

* ``<h1>`` is the book title; every line under it without a deeper heading is
  cited as ``פתיחת הספר``.
* ``<hN>`` closes every open heading of level >= N. Its parent is the open
  heading of level N-1.
* ``data-toc="none"`` headings are not part of the TOC and change nothing.

Where Otzaria's own sources disagree, the line is *ambiguous* rather than
guessed (checked against Otzaria/otzaria ``generator.dart`` and ``toc_parser.dart``):

* A heading that skips a level (h2 followed by h4): the format document gives
  it no parent, while the application code attaches it to the nearest shallower
  heading. When only the book title (h1) is above, both readings give the same
  path; when an h2 or deeper heading is above, the heading and everything
  beneath it is ambiguous.
* A heading preceded by whitespace: the library builder only recognises
  ``<h`` at the physical line start, the navigator trims first. Ambiguous.

A malformed heading (empty title, unterminated tag) does not make the whole
book unusable. Lines whose path cannot be known for certain are *ambiguous*:
they get ``None`` for both the reference and the section ID, and any citation
touching them is rejected with the reason from :func:`explain_ambiguity`.
"""
from __future__ import annotations

import re
from typing import NamedTuple

HTML_HEADING_START_RE = re.compile(r"^\s*<h([1-6])\b([^>]*)", re.IGNORECASE)
TOC_EXCLUDE_RE = re.compile(r'\bdata-toc\s*=\s*["\']none["\']', re.IGNORECASE)
OPENING = "פתיחת הספר"


class HeadingIndex(NamedTuple):
    """Per-line results; index ``i`` describes source line ``i + 1``."""

    references: list[str | None]
    section_ids: list[tuple | None]
    problems: dict[int, str]  # 1-based line of a malformed heading -> reason


def heading(line: str) -> tuple[int, str] | None:
    """Return (level, visible title), or None when the line is not a TOC heading.

    Raises ValueError for a line that starts a heading but is malformed, or
    that Otzaria's parsers read differently (indented heading).
    """
    match = HTML_HEADING_START_RE.match(line)
    if not match:
        return None
    if line[0].isspace():
        raise ValueError("indented heading: Otzaria's parsers disagree")
    if ">" not in line[: match.end() + 1]:
        raise ValueError("unterminated HTML heading tag")
    if TOC_EXCLUDE_RE.search(match.group(2)):
        return None
    title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", line)).strip()
    if not title:
        raise ValueError("empty heading")
    return int(match.group(1)), title


def analyze(lines: list[str]) -> HeadingIndex:
    # A None path/section marks a heading whose position is ambiguous.
    stack: dict[int, tuple[str, ...] | None] = {}
    section_stack: dict[int, tuple | None] = {}
    references: list[str | None] = []
    section_ids: list[tuple | None] = []
    problems: dict[int, str] = {}
    root_section: tuple = ("opening",)
    counts: dict[tuple, int] = {}
    # After a malformed heading we do not know which level it was, so the open
    # path is uncertain until an h1/h2 re-establishes it.
    uncertain = False

    for number, line in enumerate(lines, 1):
        try:
            parsed = heading(line)
        except ValueError as exc:
            problems[number] = f"{exc}: {line!r}"
            uncertain = True
            references.append(None)
            section_ids.append(None)
            continue

        if parsed is None:
            if uncertain:
                references.append(None)
                section_ids.append(None)
            elif stack:
                top = max(stack)
                references.append(" > ".join(stack[top]) if stack[top] is not None else None)
                section_ids.append(section_stack[top])
            else:
                references.append(OPENING)
                section_ids.append(root_section)
            continue

        level, title = parsed
        if level == 1:
            uncertain = False
            stack.clear()
            section_stack.clear()
            key = ("h1", title)
            counts[key] = counts.get(key, 0) + 1
            root_section = key + (counts[key],)
            references.append(OPENING)
            section_ids.append(root_section)
            continue

        if level == 2:
            uncertain = False
        for old in [k for k in stack if k >= level]:
            del stack[old]
            section_stack.pop(old, None)

        if uncertain:
            # Parent unknown: keep the stack consistent but cite nothing here.
            references.append(None)
            section_ids.append(None)
            stack[level] = (title,)
            section_stack[level] = ("uncertain", number)
            continue

        if level == 2:
            parent_path, parent_section = (), root_section
        elif level - 1 in stack:
            parent_path, parent_section = stack[level - 1], section_stack[level - 1]
        elif any(k in stack for k in range(2, level - 1)):
            # Skipped level below a real h2+ ancestor: the format document gives
            # no parent, the application code picks the ancestor. Ambiguous.
            parent_path, parent_section = None, None
        else:  # nothing but the book title above: both readings agree
            parent_path, parent_section = (), root_section
        if parent_path is None:
            stack[level] = None
            section_stack[level] = None
            references.append(None)
            section_ids.append(None)
            continue
        path = parent_path + (title,)
        key = (parent_section, level, title)
        counts[key] = counts.get(key, 0) + 1
        section = key + (counts[key],)
        stack[level] = path
        section_stack[level] = section
        references.append(" > ".join(path))
        section_ids.append(section)

    return HeadingIndex(references, section_ids, problems)


def line_reference_data(lines: list[str]) -> tuple[list[str | None], list[tuple | None]]:
    """Heading path and section ID per line; ``None`` marks an ambiguous line."""
    index = analyze(lines)
    return index.references, index.section_ids


def line_references(lines: list[str]) -> list[str | None]:
    return analyze(lines).references


def span_reference(
    references: list[str | None],
    start: int,
    end: int,
    section_ids: list[tuple | None] | None = None,
) -> str:
    """Require a citation to stay inside one heading path and one section."""
    if start < 1 or end < start or end > len(references):
        raise ValueError(f"invalid citation span {start}-{end}")
    if section_ids is not None and len(section_ids) != len(references):
        raise ValueError("reference and section-ID arrays have different lengths")
    first = references[start - 1]
    if first is None:
        raise ValueError(f"line {start} sits under a malformed heading")
    first_section = section_ids[start - 1] if section_ids is not None else None
    for offset in range(start, end):
        if references[offset] is None:
            raise ValueError(f"line {offset + 1} sits under a malformed heading")
        if references[offset] != first:
            raise ValueError("citation crosses a heading boundary")
        if section_ids is not None and section_ids[offset] != first_section:
            raise ValueError("citation crosses a repeated-heading boundary")
    return first


def explain_ambiguity(problems: dict[int, str], line_no: int) -> str:
    """Name the malformed heading that most recently precedes *line_no*."""
    earlier = [n for n in problems if n <= line_no]
    if not earlier:
        return "the heading structure above this line is uncertain"
    n = max(earlier)
    return f"malformed heading at source line {n} ({problems[n]})"
