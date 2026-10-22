#!/usr/bin/env python3
"""Safely refresh line references for datasets whose upstream source changed."""
from __future__ import annotations

import argparse
import bisect
import csv
import difflib
import hashlib
import io
import json
import os
import re
import stat
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS_DIR)
import library  # noqa: E402
import source_refs  # noqa: E402

FIELDS = [
    "id", "query", "type", "correct_ref", "correct_quote", "correct_line",
    "near_miss_ref", "near_miss_quote", "near_miss_line",
    "near_miss_same_section", "split", "verified_by_human",
]
LINE_RE = re.compile(r"^(\d+)(?:-(\d+))?$")
API = "https://api.github.com"


class UpdateProblem(Exception):
    """Raised when a source cannot be updated without guessing."""


class DuplicateJSONKeyError(ValueError):
    """Raised when JSON contains an ambiguous duplicate object key."""


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJSONKeyError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def is_path_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def path_has_link_component(path: Path) -> Path | None:
    path = Path(path).absolute()
    for component in reversed((path, *path.parents)):
        if is_path_link(component):
            return component
    return None


def reject_symlink_tree(directory: Path) -> None:
    if path_has_link_component(directory) is not None:
        raise UpdateProblem(f"dataset path contains a symlink or junction: {directory}")
    for current, dirs, files in os.walk(directory, followlinks=False):
        base = Path(current)
        for name in list(dirs):
            candidate = base / name
            if is_path_link(candidate):
                raise UpdateProblem(f"dataset contains a symlink or junction: {candidate}")
        for name in files:
            candidate = base / name
            if is_path_link(candidate):
                raise UpdateProblem(f"dataset contains a symlink or junction: {candidate}")


def normalized_lines(raw: bytes) -> list[str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UpdateProblem(f"source is not UTF-8: {exc}") from exc
    return [library.norm(line.rstrip("\r")) for line in text.split("\n")]


def parse_span(value: str) -> tuple[int, int]:
    match = LINE_RE.fullmatch(value)
    if not match:
        raise UpdateProblem(f"invalid line range {value!r}")
    start = int(match.group(1))
    end = int(match.group(2) or start)
    if start < 1 or end < start:
        raise UpdateProblem(f"invalid line range {value!r}")
    return start, end


def line_map(old: list[str], new: list[str]) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(
        a=old, b=new, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            for offset in range(a2 - a1):
                mapping[a1 + offset] = b1 + offset
    return mapping


def quote_locations(lines: list[str], quote: str) -> list[tuple[int, int]]:
    needle = library.norm(quote)
    if not needle:
        return []
    starts, cursor = [], 0
    for line in lines:
        starts.append(cursor)
        cursor += len(line) + 1
    flat = " ".join(lines)
    found, offset = set(), 0
    while True:
        hit = flat.find(needle, offset)
        if hit < 0:
            break
        finish = hit + len(needle) - 1
        first = max(0, bisect.bisect_right(starts, hit) - 1)
        last = max(0, bisect.bisect_right(starts, finish) - 1)
        found.add((first + 1, last + 1))
        offset = hit + 1
    return sorted(found)


def locate_quote(old: list[str], new: list[str], quote: str,
                 old_span: tuple[int, int], mapping: dict[int, int]) -> tuple[int, int]:
    a, b = old_span
    old_hits = [loc for loc in quote_locations(old, quote)
                if loc[0] >= a and loc[1] <= b]
    if len(old_hits) != 1:
        raise UpdateProblem(f"quote is not unique inside old lines {a}-{b}")
    hits = quote_locations(new, quote)
    if not hits:
        raise UpdateProblem("quote text changed or disappeared; manual review required")
    old_a, old_b = old_hits[0]
    indexes = range(old_a - 1, old_b)
    if all(i in mapping for i in indexes):
        mapped = [mapping[i] for i in indexes]
        if mapped == list(range(mapped[0], mapped[0] + len(mapped))):
            candidate = (mapped[0] + 1, mapped[-1] + 1)
            if candidate in hits:
                return candidate
    if len(hits) == 1:
        return hits[0]
    raise UpdateProblem(f"quote has {len(hits)} possible new locations")


def reference_for_line(references: list[str], line_no: int, book_name: str) -> str:
    """Return a precomputed heading path for a 1-based source line."""
    if line_no < 1 or line_no > len(references):
        raise UpdateProblem(
            f"{book_name}: line {line_no} is outside source (1-{len(references)})"
        )
    return references[line_no - 1]


def map_citation(
    row: dict[str, str], prefix: str, old: list[str], new: list[str],
    mapping: dict[int, int], book_name: str, references: list[str],
    section_ids: list[int] | None = None,
) -> None:
    line_key, quote_key, ref_key = f"{prefix}_line", f"{prefix}_quote", f"{prefix}_ref"
    start, end = locate_quote(old, new, row[quote_key], parse_span(row[line_key]), mapping)
    # The endpoints alone are not sufficient: a nested/intermediate heading can
    # make a span leave and later return to the same textual reference.
    reference_for_line(references, start, book_name)
    try:
        ref = source_refs.span_reference(references, start, end, section_ids)
    except ValueError as exc:
        raise UpdateProblem(f"{prefix} quote crosses an Otzaria heading boundary: {exc}") from exc
    row[line_key] = str(start) if start == end else f"{start}-{end}"
    row[ref_key] = ref


def ensure_citations_do_not_overlap(row: dict[str, str]) -> None:
    correct_start, correct_end = parse_span(row["correct_line"])
    near_start, near_end = parse_span(row["near_miss_line"])
    if not (correct_end < near_start or near_end < correct_start):
        raise UpdateProblem(
            "correct and near-miss citation spans overlap after source mapping; manual review required"
        )


def latest_commit(meta: dict, ref: str) -> str:
    # validate_source_origin has already enforced the canonical repository URL.
    slug = library.repo_slug(meta["origin_repo"])
    query = urllib.parse.urlencode({"path": meta["origin_path"], "sha": ref, "per_page": "1"})
    request = urllib.request.Request(
        f"{API}/repos/{slug}/commits?{query}",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "search-queries-source-updater",
                 "X-GitHub-Api-Version": "2022-11-28"},
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, list) or not data:
        raise UpdateProblem("GitHub returned no commit for the source path")
    sha = data[0].get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise UpdateProblem("GitHub returned an invalid commit SHA")
    return sha


def read_rows(path: Path) -> list[dict[str, str]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line, object_pairs_hook=unique_json_object)
            except (json.JSONDecodeError, DuplicateJSONKeyError) as exc:
                raise UpdateProblem(f"invalid JSONL line {number}: {exc}") from exc
            if not isinstance(row, dict) or list(row) != FIELDS:
                raise UpdateProblem(f"JSONL line {number} does not match the 12-field schema")
            if any(not isinstance(row[key], str) for key in FIELDS):
                raise UpdateProblem(f"JSONL line {number} has non-string fields")
            rows.append(row)
    if not rows:
        raise UpdateProblem("dataset JSONL is empty")
    return rows


def write_dataset(directory: Path, name: str, rows: list[dict[str, str]], meta: dict) -> None:
    """Stage all output files first and roll back if any replacement fails."""
    reject_symlink_tree(directory)
    jsonl_text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)

    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=FIELDS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)

    metadata_text = json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    targets = [
        (directory / f"{name}.jsonl", jsonl_text.encode("utf-8")),
        (directory / f"{name}.csv", ("\ufeff" + csv_buffer.getvalue()).encode("utf-8")),
        (directory / f"{name}.מקור.json", metadata_text.encode("utf-8")),
    ]
    originals: dict[Path, bytes] = {}
    staged: dict[Path, Path] = {}
    replaced: list[Path] = []

    try:
        # Capture every original before replacing any file. Refuse symlinked or
        # non-regular targets rather than reading/writing through a redirect.
        for target, _ in targets:
            if is_path_link(target):
                raise UpdateProblem(f"refusing to replace symlink/junction: {target}")
            info = target.lstat()
            if not os.path.isfile(target) or not stat.S_ISREG(info.st_mode):
                raise UpdateProblem(f"required output is not a regular file: {target}")
            fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    raise UpdateProblem(f"output changed while opening: {target}")
                chunks = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(fd)
                if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
                ):
                    raise UpdateProblem(f"output changed while reading: {target}")
                originals[target] = b"".join(chunks)
            finally:
                os.close(fd)

        # Build all replacement files on the same filesystem and fsync before
        # any canonical dataset path changes.
        for target, payload in targets:
            fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=directory)
            temp = Path(temp_name)
            staged[target] = temp
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())

        reject_symlink_tree(directory)
        for target, _ in targets:
            if is_path_link(target):
                raise UpdateProblem(f"output became a symlink/junction during refresh: {target}")
            os.replace(staged[target], target)
            replaced.append(target)
        # Persist directory entry updates where supported.
        try:
            directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except Exception as exc:
        rollback_errors = []
        for target in reversed(replaced):
            try:
                fd, restore_name = tempfile.mkstemp(
                    prefix=f".{target.name}.rollback.", suffix=".tmp", dir=directory
                )
                with os.fdopen(fd, "wb") as handle:
                    handle.write(originals[target])
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(restore_name, target)
            except Exception as rollback_exc:
                rollback_errors.append(f"{target}: {rollback_exc}")
        if rollback_errors:
            raise UpdateProblem(
                f"dataset refresh failed ({exc}); rollback also failed for: " + "; ".join(rollback_errors)
            ) from exc
        if isinstance(exc, UpdateProblem):
            raise
        raise UpdateProblem(f"dataset refresh failed; original files restored: {exc}") from exc
    finally:
        for temp in staged.values():
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


def update_dataset(directory: Path, ref: str) -> tuple[str, str | None]:
    reject_symlink_tree(directory)
    name = directory.name
    meta_path = directory / f"{name}.מקור.json"
    jsonl_path = directory / f"{name}.jsonl"
    if not meta_path.is_file() or not jsonl_path.is_file() or not (directory / f"{name}.csv").is_file():
        raise UpdateProblem("required JSONL, CSV, or source metadata file is missing")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"), object_pairs_hook=unique_json_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateJSONKeyError) as exc:
        raise UpdateProblem(f"source metadata is not valid JSON: {exc}") from exc
    expected = library.SOURCE_META_KEYS
    if not isinstance(meta, dict) or set(meta) != expected or meta.get("book_name") != name:
        raise UpdateProblem("source metadata does not match the expected schema")
    try:
        library.validate_source_origin(meta)
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateProblem(f"invalid Otzaria source provenance: {exc}") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", str(meta["origin_commit"])):
        raise UpdateProblem("origin_commit must be a full 40-character SHA")
    commit = latest_commit(meta, ref)
    new_raw = library.fetch(meta, commit)  # Always fetch the exact commit we resolved.
    new_hash = hashlib.sha256(new_raw).hexdigest()
    if new_hash == meta["origin_sha256"]:
        return f"{name}: source unchanged", None
    old_raw, problem = library.get_pinned(name, meta, offline=False)
    if problem or old_raw is None:
        raise UpdateProblem(f"cannot load pinned source: {problem or 'unknown error'}")
    old, new = normalized_lines(old_raw), normalized_lines(new_raw)
    new_reference_lines = new_raw.decode("utf-8").split("\n")
    try:
        new_references, new_section_ids = source_refs.line_reference_data(new_reference_lines)
    except ValueError as exc:
        raise UpdateProblem(f"candidate source headings are invalid: {exc}") from exc
    mapping, rows, issues = line_map(old, new), read_rows(jsonl_path), []
    for row in rows:
        original = dict(row)
        try:
            map_citation(row, "correct", old, new, mapping, name, new_references, new_section_ids)
            map_citation(row, "near_miss", old, new, mapping, name, new_references, new_section_ids)
            ensure_citations_do_not_overlap(row)
            row["near_miss_same_section"] = "כן" if row["correct_ref"] == row["near_miss_ref"] else "לא"
        except UpdateProblem as exc:
            issues.append(f"- {row['id']} ({row['query']}): {exc}")
            row.clear()
            row.update(original)
    if issues:
        report = (
            f"## {name}\n\nPinned commit: {meta['origin_commit']}\n\n"
            f"Candidate commit: {commit}\n\nCandidate SHA-256: {new_hash}\n\n"
            "No dataset files or pinned metadata were changed because at least one quote needs review.\n\n"
            + "\n".join(issues) + "\n"
        )
        return f"{name}: manual review required; dataset unchanged", report
    meta["origin_commit"], meta["origin_sha256"] = commit, new_hash
    write_dataset(directory, name, rows, meta)
    return f"{name}: references updated to {commit}", None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="main")
    parser.add_argument("--datasets-dir", default="datasets")
    parser.add_argument("--report", default="SOURCE_UPDATE_REPORT.md")
    args = parser.parse_args()
    root = Path(args.datasets_dir)
    if path_has_link_component(root) is not None:
        print(f"Refusing to scan a dataset path containing a symlink or junction: {root}", file=sys.stderr)
        return 1
    if root.exists() and not root.is_dir():
        print(f"Dataset root is not a directory: {root}", file=sys.stderr)
        return 1

    # Validate the report destination before changing any dataset files.
    report = Path(args.report)
    if path_has_link_component(report) is not None:
        print(f"Refusing to write a report path containing a symlink or junction: {report}", file=sys.stderr)
        return 1
    if not report.parent.exists() or not report.parent.is_dir():
        print(f"Report parent directory does not exist: {report.parent}", file=sys.stderr)
        return 1
    if report.exists() and not report.is_file():
        print(f"Report destination is not a regular file: {report}", file=sys.stderr)
        return 1

    issues, results = [], []
    dirs = sorted({p.parent for p in root.rglob("*.מקור.json")}) if root.exists() else []
    for directory in dirs:
        try:
            result, issue = update_dataset(directory, args.ref)
            results.append(result)
            if issue:
                issues.append(issue)
        except Exception as exc:
            results.append(f"{directory.name}: not updated ({type(exc).__name__}: {exc})")
            issues.append(f"## {directory.name}\n\nDataset unchanged. Error: {type(exc).__name__}: {exc}\n")
    if issues:
        report.write_text("# Source update report — manual review required\n\n" + "\n\n".join(issues), encoding="utf-8")
    elif report.exists():
        report.unlink()
    for result in results:
        print(result)
    print(f"Checked {len(dirs)} dataset(s); {len(issues)} need manual review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
