#!/usr/bin/env python3
"""Convert a search-queries JSONL file into its schema-ordered CSV companion."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

FIELDS = [
    "id", "query", "type", "correct_ref", "correct_quote", "correct_line",
    "near_miss_ref", "near_miss_quote", "near_miss_line",
    "near_miss_same_section", "split", "verified_by_human",
]
OPTIONAL_EMPTY = {"verified_by_human"}
ID_RE = re.compile(r"^[a-z]+-\d{3,}$")
LINE_RE = re.compile(r"^(\d+)(?:-(\d+))?$")
TYPES = {"conceptual", "short"}
SPLITS = {"test", "train"}
YESNO = {"כן", "לא"}


def is_path_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None:
        return bool(is_junction())
    # Python < 3.12 on Windows: a junction is a reparse point.
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & 0x400)


def path_has_link_component(path: Path) -> Path | None:
    path = Path(path).absolute()
    for component in reversed((path, *path.parents)):
        if is_path_link(component):
            return component
    return None


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_line_range(value: str, path: Path, line_number: int, field: str) -> tuple[int, int]:
    match = LINE_RE.fullmatch(value)
    if not match:
        raise ValueError(f"{path}:{line_number}: invalid {field} range {value!r}")
    if len(match.group(1)) > 4000 or len(match.group(2) or "") > 4000:
        raise ValueError(f"{path}:{line_number}: invalid {field} range (number too long)")
    start = int(match.group(1))
    end = int(match.group(2) or match.group(1))
    if start < 1 or end < start:
        raise ValueError(f"{path}:{line_number}: invalid {field} range {value!r}")
    return start, end


def load_records(path: Path) -> list[dict[str, str]]:
    if path_has_link_component(path) is not None:
        raise ValueError(f"{path}: input path must not contain symlinks or junctions")
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line, object_pairs_hook=unique_json_object)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: each JSONL line must be an object")
            if list(record) != FIELDS:
                missing = [field for field in FIELDS if field not in record]
                extra = [field for field in record if field not in FIELDS]
                raise ValueError(
                    f"{path}:{line_number}: wrong fields/order; missing={missing}, extra={extra}"
                )
            for field in FIELDS:
                value = record[field]
                if not isinstance(value, str):
                    raise ValueError(
                        f"{path}:{line_number}: field {field!r} must be a string"
                    )
                if not value.strip() and field not in OPTIONAL_EMPTY:
                    raise ValueError(
                        f"{path}:{line_number}: required field {field!r} is empty"
                    )

            if not ID_RE.fullmatch(record["id"]):
                raise ValueError(f"{path}:{line_number}: invalid ID {record['id']!r}")
            if record["id"] in seen:
                raise ValueError(f"{path}:{line_number}: duplicate id {record['id']!r}")
            seen.add(record["id"])
            if record["type"] not in TYPES:
                raise ValueError(f"{path}:{line_number}: invalid type {record['type']!r}")
            if record["split"] not in SPLITS:
                raise ValueError(f"{path}:{line_number}: invalid split {record['split']!r}")
            if record["near_miss_same_section"] not in YESNO:
                raise ValueError(
                    f"{path}:{line_number}: near_miss_same_section must be כן or לא"
                )
            if record["correct_quote"] == record["near_miss_quote"]:
                raise ValueError(f"{path}:{line_number}: correct and near-miss quotes are identical")

            correct_start, correct_end = parse_line_range(
                record["correct_line"], path, line_number, "correct_line"
            )
            near_start, near_end = parse_line_range(
                record["near_miss_line"], path, line_number, "near_miss_line"
            )
            if not (correct_end < near_start or near_end < correct_start):
                raise ValueError(
                    f"{path}:{line_number}: correct and near-miss ranges overlap"
                )

            # Without the source text only the impossible case can be caught;
            # tools/validate.py checks the exact section identity.
            if (record["near_miss_same_section"] == "כן"
                    and record["correct_ref"] != record["near_miss_ref"]):
                raise ValueError(
                    f"{path}:{line_number}: near_miss_same_section disagrees with references"
                )
            records.append({field: record[field] for field in FIELDS})
    if not records:
        raise ValueError(f"{path}: no records found")
    return records


def replacement_mode(destination: Path) -> int:
    """Preserve existing permissions; new files respect the current umask."""
    try:
        info = destination.lstat()
    except FileNotFoundError:
        mask = os.umask(0)
        os.umask(mask)
        return 0o666 & ~mask
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{destination}: output destination is not a regular file")
    return stat.S_IMODE(info.st_mode)


def write_csv_atomic(destination: Path, records: list[dict[str, str]]) -> None:
    if path_has_link_component(destination) is not None:
        raise ValueError(f"{destination}: output path must not contain symlinks or junctions")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path_has_link_component(destination) is not None:
        raise ValueError(f"{destination}: output path must not contain symlinks or junctions")
    mode = replacement_mode(destination)

    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=FIELDS,
                extrasaction="raise",
                lineterminator="\r\n",
            )
            writer.writeheader()
            writer.writerows(records)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        if path_has_link_component(destination) is not None:
            raise ValueError(f"{destination}: output path became a symlink or junction")
        os.replace(temporary, destination)
        try:
            directory_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "Usage: python jsonl_to_csv.py INPUT.jsonl OUTPUT.csv",
            file=sys.stderr,
        )
        return 2
    source, destination = Path(argv[1]).absolute(), Path(argv[2]).absolute()
    try:
        same_path = source.resolve() == destination.resolve()
    except OSError as exc:
        print(f"ERROR: unable to compare input/output paths: {exc}", file=sys.stderr)
        return 1
    if same_path:
        print("ERROR: input and output paths must be different", file=sys.stderr)
        return 2
    try:
        records = load_records(source)
        write_csv_atomic(destination, records)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {len(records)} records to {destination}")
    print("Note: source references and line numbers still require repository validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
