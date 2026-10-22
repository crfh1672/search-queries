---
name: search-queries-dataset-builder
description: Generate, validate, and prepare semantic-search evaluation records from pinned .txt books inside Otzaria's library repository.
---

# Search Queries Dataset Builder

Create high-quality evaluation-query records for `https://github.com/crfh1672/search-queries`.

## Non-negotiable source rule

Every query and citation must be based on the exact committed `.txt` file located in `https://github.com/Otzaria/otzaria-library` under `ספרים/אוצריא/<category>/...`. This includes books imported to Otzaria from other libraries after they are committed into that library. Do not source dataset records directly from unrelated repositories, web pages, memory, or guessed locations.

Do not invent source paths, commit hashes, SHA-256 hashes, quotations, heading references, or line numbers. Pin the exact commit and verify the raw source's SHA-256 before creating records. The text source is not copied into the dataset repository; the metadata points to it.

## Before generating records

Read the current `README.md`, `schema/query.schema.json`, `schema/source.schema.json`, `tools/validate.py`, and a fixture or existing dataset. Follow current code over this skill if they differ.

For a selected Otzaria source:
1. Confirm its full path in `otzaria-library`, under `ספרים/אוצריא/<category>/`.
2. Copy the filename stem as `book_name`; use the first category after `ספרים/אוצריא/` as `source_category`.
3. Resolve and record a real 40-character commit SHA.
4. Calculate `origin_sha256` on the raw bytes of that file at that exact commit.
5. Preserve line breaks and markup in the source snapshot used to locate quotes and headings.

The metadata file is `<book_name>.מקור.json` and requires exactly: `book_name`, `source_category`, `id_prefix`, `origin_repo`, `origin_path`, `origin_commit`, `origin_sha256`, and `note`. `origin_repo` must be `https://github.com/Otzaria/otzaria-library`.

## Heading-based references

Otzaria `.txt` files use physical lines as content units and whole-line heading markup such as `<h1>` through `<h6>`. Parse the heading hierarchy from the raw source before removing HTML tags. Store `correct_ref` and `near_miss_ref` as the current heading path for their citation lines, such as `הלכות ציצית > סימן א` or, when the underlying Talmud file uses that heading, `דף ב.`. HTML heading text has tags removed but otherwise preserves the source title. Markdown heading references include the leading hashes (for example, `## Chapter`); level-1 headings map to `פתיחת הספר`.

Line fields contain absolute 1-based physical source line numbers or ranges. The quote text can be normalized for matching, but the line numbers and heading path must be derived from the entire source at the pinned commit, not a snippet or reformatted copy.

If the heading structure does not support a stable reference, preserve the exact line citation and flag it for review rather than inventing a page or section. A multi-line citation must remain within a single heading path.

## Query quality

Each record is an evaluation item, not merely a question/answer:
- Choose a specific claim or fact that the source passage supports.
- Write a natural query with meaningful lexical diversity but no added assumptions. Preserve meaning-critical qualifiers, conditions, negations, and named entities; lexical diversity must not change what the query asks.
- Select a short exact quote as evidence for the correct answer.
- Find a plausible near miss from the same pinned book that is topically or lexically similar but does not answer the query.
- If no defensible near miss exists, skip the record or flag it for human review; do not fabricate one.
- Do not let an LLM explanation or structural validation replace semantic review.

## Exact JSONL field order

Each line is one JSON object with exactly these 12 string fields, in order:

1. `id`
2. `query`
3. `type`
4. `correct_ref`
5. `correct_quote`
6. `correct_line`
7. `near_miss_ref`
8. `near_miss_quote`
9. `near_miss_line`
10. `near_miss_same_section`
11. `split`
12. `verified_by_human`

The ID follows `<id_prefix>-NNN`; `type` is `conceptual` or `short`; `split` is `train` or `test`. `near_miss_same_section` is `כן` exactly when the two reference strings are identical, otherwise `לא`. All fields are non-empty except `verified_by_human` in `drafts/`. Do not add extra keys.

The source's directory category, metadata category and book filename stem must match. Do not create hand-authored CSV; generate it from JSONL with the builder script or your local script that follows the schema exactly.

## Workflow: draft, review, promote

1. Write dataset files to `drafts/<source_category>/<book_name>/`.
2. Generate its CSV from JSONL.
3. Run source validation and repository unit tests.
4. Have a human check the query meaning, correct evidence, and near miss.
5. Fill `verified_by_human` with the verifier's name/ID and run:

```bash
python tools/promote_dataset.py "drafts/<source_category>/<book_name>"
```

Promotion is refused unless the dataset passes all checks, human verification is present, and the target path does not already exist. The approved dataset is moved to `datasets/<source_category>/<book_name>/`; do not keep divergent copies.

## Validation commands

```bash
python tools/validate.py
python tools/validate.py "drafts/<source_category>/<book_name>"
python -m unittest discover -s tests -v
```

Offline validation only works if the exact pinned source bytes are cached and their SHA-256 matches the metadata.

## License and provenance

Otzaria includes books from various upstream libraries, which may have different license or permission requirements. Being present in Otzaria is not proof that all books are freely redistributable. Keep the original provenance, check the license for the specific book before public redistribution or product integration, and retain any required attribution.
