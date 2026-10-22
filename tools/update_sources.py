#!/usr/bin/env python3
"""Safely refresh line references for datasets whose upstream source changed."""
from __future__ import annotations

import argparse
import bisect
import csv
import difflib
import hashlib
import json
import os
import re
import sys
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


def reference_for_line(lines: list[str], line_no: int, book_name: str) -> str:
    """Return the exact heading path used by the Otzaria book's table of contents."""
    try:
        return source_refs.reference_at_line(lines, line_no)
    except ValueError as exc:
        raise UpdateProblem(str(exc)) from exc


def map_citation(
    row: dict[str, str], prefix: str, old: list[str], new: list[str],
    mapping: dict[int, int], book_name: str,
    reference_lines: list[str] | None = None,
) -> None:
    line_key, quote_key, ref_key = f"{prefix}_line", f"{prefix}_quote", f"{prefix}_ref"
    start, end = locate_quote(old, new, row[quote_key], parse_span(row[line_key]), mapping)
    ref_source = reference_lines if reference_lines is not None else new
    ref = reference_for_line(ref_source, start, book_name)
    if reference_for_line(ref_source, end, book_name) != ref:
        raise UpdateProblem(f"{prefix} quote crosses an Otzaria heading boundary")
    row[line_key] = str(start) if start == end else f"{start}-{end}"
    row[ref_key] = ref


def ensure_citations_do_not_overlap(row: dict[str, str]) -> None:
    correct_start, correct_end = parse_span(row["correct_line"])
    near_start, near_end = parse_span(row["near_miss_line"])
    if not (correct_end < near_start or near_end < correct_start):
        raise UpdateProblem(
            "correct and near-miss citation spans overlap after source mapping; manual review required"
        )


def repo_slug(url: str) -> str:
    parsed = urllib.parse.urlparse(url if "://" in url else f"https://github.com/{url}")
    if parsed.hostname not in {"github.com", "www.github.com"}:
        raise UpdateProblem("origin_repo must point to github.com")
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise UpdateProblem(f"cannot parse repository from {url!r}")
    return f"{parts[0]}/{parts[1].removesuffix('.git')}"


def latest_commit(meta: dict, ref: str) -> str:
    slug = repo_slug(meta["origin_repo"])
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
                row = json.loads(line)
            except json.JSONDecodeError as exc:
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
    with (directory / f"{name}.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (directory / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    with (directory / f"{name}.מקור.json").open("w", encoding="utf-8", newline="\n") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
        f.write("\n")


def update_dataset(directory: Path, ref: str) -> tuple[str, str | None]:
    name = directory.name
    meta_path = directory / f"{name}.מקור.json"
    jsonl_path = directory / f"{name}.jsonl"
    if not meta_path.is_file() or not jsonl_path.is_file() or not (directory / f"{name}.csv").is_file():
        raise UpdateProblem("required JSONL, CSV, or source metadata file is missing")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
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
    old_reference_lines = old_raw.decode("utf-8").split("\n")
    new_reference_lines = new_raw.decode("utf-8").split("\n")
    mapping, rows, issues = line_map(old, new), read_rows(jsonl_path), []
    for row in rows:
        original = dict(row)
        try:
            map_citation(row, "correct", old, new, mapping, name, new_reference_lines)
            map_citation(row, "near_miss", old, new, mapping, name, new_reference_lines)
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
    report = Path(args.report)
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
