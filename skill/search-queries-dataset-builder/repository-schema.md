# Reference: `crfh1672/search-queries` dataset structure

Repository: https://github.com/crfh1672/search-queries

The checked-out repository, README, schema files, and validator are the source of truth. Read them before every substantial generation task.

## Canonical source rule

Every query, correct quote, near miss, reference, and line number must be based on a real `.txt` book committed in `https://github.com/Otzaria/otzaria-library`, under a path containing `ספרים/אוצריא/<category>/...`. This includes books imported into Otzaria from other libraries once they are present at that path. Never point at an arbitrary upstream library or invent references.

Source metadata records the precise repo-relative path, full 40-character commit SHA, and SHA-256 of the raw source file at that commit. The raw book itself is not copied into the query dataset repository.

## Folder structure

```
drafts/<source_category>/<book_name>/
  <book_name>.jsonl
  <book_name>.csv
  <book_name>.מקור.json

datasets/<source_category>/<book_name>/
  <book_name>.jsonl
  <book_name>.csv
  <book_name>.מקור.json
```

`source_category` must equal the first folder under `ספרים/אוצריא/` in `origin_path`, and `book_name` must equal the filename stem of that `.txt` source. For example, a path beginning `MoreBooks/ספרים/אוצריא/תלמוד בבלי/...` has category `תלמוד בבלי`; a path beginning `MoreBooks/ספרים/אוצריא/שות/...` has category `שות`.

`drafts/` allows `verified_by_human` to be empty. Promotion into `datasets/` requires a human verification value and a clean validator run. JSONL is canonical; CSV must be regenerated from it.

## Record fields

Exactly 12 string fields in this order:

`id`, `query`, `type`, `correct_ref`, `correct_quote`, `correct_line`, `near_miss_ref`, `near_miss_quote`, `near_miss_line`, `near_miss_same_section`, `split`, `verified_by_human`.

- `type`: `conceptual` or `short`.
- `split`: `train` or `test`.
- `near_miss_same_section`: `כן` exactly when the two reference strings are equal, otherwise `לא`.
- IDs follow `<id_prefix>-NNN` with at least three digits.
- All values are strings; all fields must be non-empty except `verified_by_human` in drafts.

## Source metadata

The metadata file `<book_name>.מקור.json` has exactly:

- `book_name`
- `source_category`
- `id_prefix`
- `origin_repo` (must be `https://github.com/Otzaria/otzaria-library`)
- `origin_path` (relative `.txt` path below `ספרים/אוצריא/`)
- `origin_commit` (full 40-character SHA)
- `origin_sha256` (64-character SHA-256 of the raw source bytes)
- `note`

Never guess a path, commit, hash, line number, heading, or quotation.

## References, headings and lines

Otzaria source files use physical lines as content units and heading lines such as `<h1>` to `<h6>`. The validator derives a human-readable heading path from the active hierarchy. Examples might be `הלכות ציצית > סימן א`, `שאלות ותשובות > סימן א`, or a Talmud book's actual heading `דף ב.`.

The book's headings must be parsed from the original source before stripping HTML tags. Line numbers refer to the entire source file with original physical line breaks. The validator then normalizes text for quote matching; it verifies both that the quote occurs within the declared line range and that the heading path matches that range. A span crossing a heading boundary is rejected.

## Query-quality rules

Each record needs a natural query, an exact source-backed correct passage, and a plausible but semantically wrong near miss, all from the same pinned source book. The correct and near-miss citations must not overlap or share lines. A structurally valid record is not proof of semantic quality; human review is required before promotion.

## Commands

```bash
python tools/validate.py
python tools/validate.py "drafts/<category>/<book>"
python tools/validate.py "datasets/<category>/<book>"
python -m unittest discover -s tests -v
python tools/promote_dataset.py "drafts/<category>/<book>"
```

Offline validation requires the pinned raw source to exist in the cache and match the recorded SHA-256.

## License note

Otzaria contains works from multiple contributing libraries and license regimes. Do not assume that all sources carry the same license; verify the individual book's provenance and terms before public redistribution or integration into a product.
