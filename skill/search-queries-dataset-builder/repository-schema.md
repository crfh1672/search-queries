# Reference: `crfh1672/search-queries` dataset structure

Repository: https://github.com/crfh1672/search-queries

This reference summarizes the repository structure inspected when this Skill was created. The repository itself remains the source of truth; re-read its current README, schema, and validator before each substantial generation task.

## Dataset files

A dataset named `<masechet>` lives in `datasets/<masechet>/` and contains:

- `<masechet>.jsonl` — canonical records, one JSON object per line.
- `<masechet>.csv` — generated from JSONL and identical by record ID and field values.
- `<masechet>.מקור.json` — source identity and provenance metadata.

The source text itself is not stored in this repository. Records point to a file in the source library at a pinned Git commit, with a SHA-256 hash. The validator checks that the fetched file at that commit matches the hash.

## Record field order

The schema currently requires exactly these 12 string fields, in order:

`id`, `query`, `type`, `correct_ref`, `correct_quote`, `correct_line`, `near_miss_ref`, `near_miss_quote`, `near_miss_line`, `near_miss_same_amud`, `split`, `verified_by_human`.

There are no additional properties. Only `verified_by_human` may be empty. `type` currently allows `conceptual` and `short`; `split` allows `test` and `train`; `near_miss_same_amud` allows `כן` and `לא`. IDs follow the metadata prefix and a hyphen plus at least three digits.

## Source metadata keys

The metadata file currently requires exactly:

- `masechet`
- `id_prefix`
- `origin_repo`
- `origin_path`
- `origin_commit`
- `origin_sha256`
- `note`

`origin_commit` must be a full 40-character hexadecimal commit SHA. `origin_sha256` must match the raw source file at that commit.

## Line and quote rules

- Line numbers refer to the entire source file after the repository's normalization and HTML-tag removal process, beginning at 1.
- References use the expected format `<masechet> <folio> ע"א` or `<masechet> <folio> ע"ב`.
- Each quote must occur in the line/range declared for it and be inside the referenced page/side.
- Correct and near-miss quote ranges must not overlap or share a line.
- `near_miss_same_amud` is checked by exact equality of `correct_ref` and `near_miss_ref`.
- Normalization strips Hebrew cantillation/vowels and HTML tags, unifies Hebrew quote marks, and normalizes `יהוה` to `ה'`.

## Validation commands

Run from the repository root:

```bash
python tools/validate.py
python tools/validate.py datasets/<masechet>
python tools/validate.py --offline
python -m unittest discover -s tests -v
```

The offline form works only when the pinned source is already cached and matches the recorded hash.
