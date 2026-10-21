---
name: search-queries-dataset-builder
description: Generate and validate evaluation-query records for the crfh1672/search-queries repository. Use when creating Hebrew semantic-search queries with exact source references, line-numbered quotes, difficult near-miss passages, or JSONL/CSV dataset files compatible with its schema.
---

# Search Queries Dataset Builder

Create high-quality semantic-search evaluation records that are compatible with `https://github.com/crfh1672/search-queries`.

## Core rules

- Treat the target repository's current `README.md`, `schema/query.schema.json`, `tools/validate.py`, and an existing dataset as the source of truth. If a local clone is available, inspect these before generating data. If the schema has changed, follow the checked-out schema rather than stale notes in this Skill.
- The dataset is an evaluation benchmark, not just a list of queries. Each record needs both a correct source passage and a plausible but incorrect near-miss passage.
- Never invent a source reference, quotation, line number, repository path, commit SHA, or SHA-256 hash. Use only values verified against the exact source file and pinned commit.
- Never claim that a record is human-verified unless a human actually checked it. Leave `verified_by_human` as an empty string otherwise.
- Keep query wording semantically faithful but lexically diverse. Lower overlap with the source is valuable only when the query remains natural, answerable from the correct passage, and not answerable from the near-miss. Do not optimize for token difference at the expense of correctness.
- Do not let an LLM-generated explanation or score replace validation against the source text.

## Workflow

### 1. Inspect repository requirements

Read the repository `README.md`, `schema/query.schema.json`, `tools/validate.py`, and one existing record (or fixture). Confirm:

- the exact set and order of record fields;
- allowed values for `type`, `split`, and `near_miss_same_amud`;
- the ID prefix and numbering rule;
- how source references and line numbers are represented;
- the source metadata required for a new dataset;
- how JSONL and CSV are validated and generated.

If the local repository or source files are unavailable, request or use only an explicitly supplied source file with preserved line numbering. Do not substitute guessed source locations.

### 2. Establish source provenance

For each dataset, use the exact source file and pinned commit specified by the dataset metadata. The required metadata file is `<masechet>.מקור.json`; consult the repository schema and README for its exact fields. Obtain `origin_commit` and `origin_sha256` from verifiable source data; never invent either value.

Preserve the original line boundaries and page/section headings. The validator counts lines in the full normalized source file, not in a text snippet passed to the model. If the source has been truncated, reflowed, or stripped of headings such that line numbers cannot be verified, do not fabricate them.

### 3. Select a useful source passage

For each candidate query:

1. Identify a specific proposition, distinction, result, or detail that the source passage actually supports.
2. Select a short exact quotation that proves the passage is relevant.
3. Record the correct source reference and absolute source line number(s).
4. Confirm that the citation points to the relevant folio/page and side using the repository's convention.

Citations and quotes must be drawn from the original source after applying only the normalization accepted by the repository validator. Do not paraphrase text in a quote field.

### 4. Generate the query

Write a query that a real user might type. Aim for meaningful lexical diversity:

- Prefer a different natural vocabulary and sentence structure from the source where possible.
- Use a modern, direct question or information need rather than mechanically replacing individual words.
- Preserve every meaning-critical distinction, qualifier, condition, negation, relationship, and named entity.
- Avoid adding assumptions or asking for facts that cannot be answered from the selected passage.
- Do not force unfamiliar synonyms or unnatural wording merely to reduce overlap.

A query with low lexical overlap is useful only if it still retrieves the correct passage. Prefer several genuinely distinct queries over near-duplicates. Choose `type: "conceptual"` for a query requiring conceptual or relational understanding, and `type: "short"` for a short/direct lookup, subject to the values accepted by the repository schema.

### 5. Choose a hard near miss

Find another exact passage in the same source file that a search engine might rank for the query but that does not answer it.

A useful near miss should be plausibly related through wording, topic, or neighboring context, but semantically fail the query. Avoid arbitrary unrelated text and avoid a passage that also answers the query; that would create a false negative.

- Record its exact reference, quotation, and absolute line number(s).
- The correct quote and near-miss quote must come from different, non-overlapping source lines.
- Set `near_miss_same_amud` to `"כן"` exactly when `correct_ref` and `near_miss_ref` are identical; otherwise set it to `"לא"`. Follow the validator's equality rule, not an informal guess about whether passages feel nearby.
- If no defensible near miss can be found, do not invent one. Skip the record or flag it for human review outside the dataset file.

### 6. Create JSONL records

Each line in `<masechet>.jsonl` must be one JSON object, with exactly the 12 fields below in precisely this order. All values must be strings.

1. `id`
2. `query`
3. `type`
4. `correct_ref`
5. `correct_quote`
6. `correct_line`
7. `near_miss_ref`
8. `near_miss_quote`
9. `near_miss_line`
10. `near_miss_same_amud`
11. `split`
12. `verified_by_human`

Repository-specific constraints:

- `id` must match `<id_prefix>-NNN`, using a unique sequential identifier and the prefix in the metadata.
- `type` must be one of the schema's allowed values (currently `conceptual` or `short`).
- `split` must be exactly `train` or `test`.
- `near_miss_same_amud` must be exactly `כן` or `לא`.
- All fields must be non-empty except `verified_by_human`, which may be empty.
- Do not add fields such as `evidence`, `score`, `reason`, or `lexical_overlap`; the repository rejects extra keys.
- Escape quotes and backslashes correctly in JSON. Use UTF-8 without a BOM and end the file with a newline.

### 7. Prevent evaluation leakage

Use `split: "test"` only for benchmark queries intended for final measurement; use `split: "train"` for records used in development or training. Do not make train/test copies of the same query or trivial paraphrases. When possible, group related queries or source passages consistently so near-duplicates do not leak across splits. If the user does not specify a split, ask one concise question or follow the established dataset convention without silently guessing.

### 8. Generate CSV from JSONL

Treat JSONL as the canonical data file. Generate `<masechet>.csv` from it using the exact same 12-column header and field order. Never author JSONL and CSV independently, because they must match by `id` and every field.

This Skill includes `scripts/jsonl_to_csv.py` for creating the CSV. Example:

```bash
python scripts/jsonl_to_csv.py datasets/מסכת/מסכת.jsonl datasets/מסכת/מסכת.csv
```

The script validates the JSONL record structure before writing CSV. It does not validate source line numbers; the repository's own validator does that.

### 9. Validate before delivery

Run the repository's own checks from the repository root:

```bash
python tools/validate.py datasets/מסכת
python -m unittest discover -s tests -v
```

The first command should be run with network access when needed to fetch the pinned source, or with `--offline` only when a valid source cache exists. Fix all validation errors before presenting the dataset as ready.

Remember: schema validation confirms structural and source-location consistency, but it does not prove that a query is semantically faithful or that the near miss truly fails to answer it. Review these aspects separately and use human spot checks, especially for subtle distinctions.

## Completion report

When asked to create records, return the generated files and report:

- how many records were accepted and how many were skipped;
- whether source locations were verified;
- whether repository validation and tests were run, including any failures;
- whether a human verified the records.

Never report checks as passed unless they were actually run successfully.
