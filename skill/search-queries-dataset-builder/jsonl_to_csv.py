#!/usr/bin/env python3
"""Convert a search-queries JSONL file into its schema-ordered CSV companion."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

FIELDS = [
    "id", "query", "type", "correct_ref", "correct_quote", "correct_line",
    "near_miss_ref", "near_miss_quote", "near_miss_line",
    "near_miss_same_amud", "split", "verified_by_human",
]
OPTIONAL_EMPTY = {"verified_by_human"}


def load_records(path: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: each JSONL line must be an object")
            missing = [field for field in FIELDS if field not in record]
            extra = [field for field in record if field not in FIELDS]
            if missing or extra:
                raise ValueError(
                    f"{path}:{line_number}: wrong fields; missing={missing}, extra={extra}"
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
            record_id = record["id"]
            if record_id in seen:
                raise ValueError(f"{path}:{line_number}: duplicate id {record_id!r}")
            seen.add(record_id)
            records.append({field: record[field] for field in FIELDS})
    if not records:
        raise ValueError(f"{path}: no records found")
    return records


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "Usage: python jsonl_to_csv.py INPUT.jsonl OUTPUT.csv",
            file=sys.stderr,
        )
        return 2
    source, destination = Path(argv[1]), Path(argv[2])
    try:
        records = load_records(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # utf-8-sig supports spreadsheet apps that expect a UTF-8 BOM.
        with destination.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=FIELDS,
                extrasaction="raise",
                lineterminator="\r\n",
            )
            writer.writeheader()
            writer.writerows(records)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {len(records)} records to {destination}")
    print("Note: source references and line numbers still require repository validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
