---
name: search-queries-dataset-builder
description: Generate, validate, and prepare semantic-search evaluation records from pinned .txt books inside Otzaria's library repository.
---

# Search Queries Dataset Builder

Create high-quality evaluation-query records for `https://github.com/crfh1672/search-queries`. The dataset is an evaluation benchmark, not a list of questions: every record needs a correct source passage and a plausible but wrong near-miss passage.

## Non-negotiable rules

- **Source.** Every query and citation must be based on the exact committed `.txt` file in `https://github.com/Otzaria/otzaria-library` that the Otzaria application actually ships (see "Packaged roots" below). Never source records from other repositories, web pages, memory, or guessed locations.
- **No invented values.** Never invent a source path, commit SHA, SHA-256, quotation, heading reference, or line number. Use only values verified against the exact source bytes at the pinned commit.
- **Human verification is human.** Never write anything into `verified_by_human` unless a named human actually compared the record with the source. Agents leave it empty. Approved datasets accept only names listed in `verifiers.txt`. Never claim in a report that a record was human-verified if no human did it.
- **Validation is not review.** Structural validation proves locations and consistency, not that a query is natural or that the near miss truly fails to answer it. Do not let an LLM explanation or a green CI replace semantic review.
- **Current code wins.** Read the current `README.md`, `schema/query.schema.json`, `schema/source.schema.json`, `tools/validate.py` and a fixture before generating. If they differ from this skill, follow the repository.

## Packaged roots

`origin_path` must be `<root>/ספרים/אוצריא/<category>/…/<book>.txt` where `<root>` is one of `PACKAGED_ROOTS` in `tools/library.py` (the roots the Otzaria release merges into its library, in the order of `BOOK_ROOTS` in `otzaria-library/manual_links_packaging.py`). These are not shipped and are rejected: `extraBooks/`, `docxToOtzaria/`, `DictaToOtzaria/לא ערוך/`, and `<root>/ספרים/<anything but אוצריא>/` such as `ספרים/לא ממויין/`.

A later root overrides an earlier one for the same relative path. `tools/validate.py` asks the library whether a later root holds the same relative path at the pinned commit and rejects the source if so: pin the copy the user actually sees.

## Preparing a source

1. Confirm the full path in `otzaria-library` and that it passes the rule above.
2. `book_name` is the filename stem; `source_category` is the first folder after `ספרים/אוצריא/`.
3. Record a real 40-character commit SHA.
4. Compute `origin_sha256` on the raw bytes of that file at that commit.
5. Keep the raw lines (with markup) for locating quotes and headings.

`<book_name>.מקור.json` has exactly: `book_name`, `source_category`, `id_prefix`, `origin_repo` (must be `https://github.com/Otzaria/otzaria-library`), `origin_path`, `origin_commit`, `origin_sha256`, `note`. `id_prefix` must be unique across all datasets.

## Heading-based references

Otzaria files use one physical line per unit and build their table of contents only from lines starting with `<h1>`–`<h6>`. Markdown `#` lines are ordinary body text and are never headings. References are derived from the raw source, before tags are stripped:

- `<h1>` is the book title; lines under it with no deeper heading cite `פתיחת הספר`.
- `correct_ref`/`near_miss_ref` are the heading path of the cited line, e.g. `הלכות ציצית > סימן א`, or `דף ב.` when the file's heading is that. A heading's text is the visible line text.
- A heading that skips a level (h2 then h4) has no parent, exactly as in Otzaria's TOC.
- `data-toc="none"` headings are not part of the path.
- A multi-line citation must stay inside one section; two sibling sections with the same title are different sections.
- A malformed heading (empty title, unterminated tag) makes the lines under it, up to the next `<h1>`/`<h2>`, *uncertain*. Do not cite them; the validator rejects such citations and names the malformed line. Other lines of the book are unaffected.

Line fields are absolute 1-based physical line numbers or ranges in the full source file at the pinned commit, never numbers from a snippet.

## Query quality

- Choose a specific claim the passage actually supports.
- Write a natural query with real lexical diversity but no added assumptions. Preserve every meaning-critical qualifier, condition, negation, relationship and named entity. Low overlap is useful only if the query still retrieves the correct passage and the near miss does not answer it.
- Select a short exact quote as evidence.
- Find a plausible near miss in the same pinned book that is topically or lexically close but does not answer the query. It must not share lines with the correct citation. A passage that merely continues the same point in the next lines is not a real negative.
- If no defensible near miss exists, skip the record or flag it for human review outside the dataset file.
- `type` is `conceptual` for a query needing conceptual or relational understanding and `short` for a short direct lookup.

## Exact JSONL field order

Each line is one JSON object with exactly these 12 string fields, in this order:

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

`id` is `<id_prefix>-NNN` and unique across all datasets. `type` is `conceptual` or `short`; `split` is `train` or `test`. `near_miss_same_section` is `כן` exactly when both citations lie in the very same section instance, otherwise `לא` (identical ref strings are not enough: sibling sections can share a title). All fields are non-empty except `verified_by_human` in `drafts/`. No extra keys. UTF-8 without BOM, newline at the end of the file.

## Preventing evaluation leakage

Use `split: "test"` only for queries kept for final measurement and `"train"` for development. Never create train/test copies of the same query or trivial paraphrases, and keep related queries or neighbouring source passages on the same side so near-duplicates do not leak across splits. If the user has not specified a split, follow the dataset's convention or ask one short question instead of guessing silently.

## Workflow: draft, review, promote

1. Write the files to `drafts/<source_category>/<book_name>/`.
2. Generate the CSV from the JSONL with `python skill/search-queries-dataset-builder/jsonl_to_csv.py in.jsonl out.csv`; never hand-author both.
3. Run `python tools/validate.py "drafts/<source_category>/<book_name>"` and `python -m unittest discover -s tests -v`.
4. A human checks query meaning, correct evidence and near miss.
5. Only then does a listed verifier's name go into `verified_by_human` and the folder is promoted:

```bash
python tools/promote_dataset.py "drafts/<source_category>/<book_name>"
```

Promotion is refused unless validation passes as an approved dataset (including `verifiers.txt`) and the target does not exist. Never keep divergent copies in `drafts/` and `datasets/`.

Offline validation works only if the pinned source (and its shadow check) is already cached.

## Completion report

When asked to create records, return the files and report:

- how many records were accepted and how many skipped, and why;
- whether source locations were verified against the pinned bytes;
- whether `tools/validate.py` and the unit tests were run, with any failures;
- whether a human verified the records (by default: no).

Never report a check as passed unless it was actually run and succeeded.

## License and provenance

Otzaria includes books from many upstream libraries with different licenses. Presence in Otzaria does not mean a book is freely redistributable. Keep the original provenance, check the specific book's license before public redistribution or product integration, and keep any required attribution.
