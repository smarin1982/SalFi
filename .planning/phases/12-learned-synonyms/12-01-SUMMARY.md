---
phase: 12-learned-synonyms
plan: "01"
subsystem: latam-extraction
tags: [learned-synonyms, candidate-capture, concept-map, synonym-expansion]
dependency_graph:
  requires: [latam_extractor.py, latam_concept_map.py]
  provides: [data/latam/learned_candidates.jsonl, data/latam/learned_synonyms.json]
  affects: [latam_extractor.py, latam_concept_map.py]
tech_stack:
  added: []
  patterns: [append-only JSONL candidate store, import-time JSON loader, fallback lookup chain]
key_files:
  created:
    - data/latam/learned_synonyms.json
  modified:
    - latam_extractor.py
    - latam_concept_map.py
decisions:
  - "Learned synonyms are stored as lowercase labels in _LEARNED_SYNONYMS dict; map_to_canonical uses label.strip().lower() for fallback lookup (no accent normalization in learned path — labels are pre-normalized in JSON)"
  - "Base LATAM_CONCEPT_MAP always wins on conflict: _LEARNED_SYNONYMS fallback only reached after the base map loop returns None"
  - "_append_candidate uses read-modify-write (JSONL rewritten in full) — safe in single-threaded extraction context; deduplication by label.strip().lower()"
  - "All three extraction layers (pdfplumber, pymupdf, ocr) capture unmatched labels — ensures complete coverage regardless of PDF type"
metrics:
  duration: "3min"
  completed: "2026-03-11"
  tasks_completed: 2
  files_modified: 3
---

# Phase 12 Plan 01: Learned Synonyms — Candidate Capture + Concept Map Loader Summary

Wire unmatched-label capture into all three extraction layers and extend map_to_canonical() with a JSON-backed fallback that loads approved synonyms at import time.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add _append_candidate() to latam_extractor + call on unmatched labels | 6d866e7 | latam_extractor.py |
| 2 | Add learned_synonyms.json loader to latam_concept_map + seed file | 67bbf16 | latam_concept_map.py, data/latam/learned_synonyms.json |

## What Was Built

**latam_extractor.py — candidate capture:**
- `_CANDIDATES_FILE = Path("data/latam/learned_candidates.jsonl")` constant added
- `_append_candidate(label, value, page, section, company, country, pdf)` helper:
  - Creates `data/latam/` directory on first use (no FileNotFoundError)
  - Deduplicates by `label.strip().lower()` — increments `seen_count` and updates `companies_seen` on repeat
  - Rewrites JSONL atomically (read-modify-write, single-threaded context)
  - Wrapped entirely in try/except — never raises, logs warning via loguru on failure
- Called in `_extract_pdfplumber`, `_extract_pymupdf_text`, and `_extract_ocr` after every unmatched label with a numeric value
- Labels shorter than 4 characters skipped in all three layers

**latam_concept_map.py — synonym loader:**
- `_LEARNED_SYNONYMS_FILE = Path("data/latam/learned_synonyms.json")` constant added
- `_load_learned_synonyms()` loads JSON at import time — returns `{}` if file missing or malformed
- `_LEARNED_SYNONYMS: dict[str, str]` populated at module load
- `map_to_canonical()` extended with fallback block after base map miss: `label.strip().lower()` lookup in `_LEARNED_SYNONYMS`

**data/latam/learned_synonyms.json — seed file:**
5 high-confidence MiRed IPS entries seeded:
- `ganancia antes de impuesto` → `operating_income`
- `ganancia o perdida del año` → `net_income`
- `ganancia del año` → `net_income`
- `amornizaciones` (OCR typo) → `depreciation_amortization`
- `amortizaciones` → `depreciation_amortization`

## Verification Results

Task 1 — All 4 assertions passed:
- First write creates file with correct label and seen_count=1
- Same label increments seen_count to 2, updates companies_seen
- Different label adds new record (2 total)
- Empty/None input does not raise

Task 2 — All 7 assertions passed:
- Base map regression: `Ingresos operacionales` → `revenue` (unchanged)
- `Ganancia antes de impuesto` → `operating_income`
- `Ganancia o Perdida del año` → `net_income`
- `GANANCIA DEL AÑO` → `net_income` (case-insensitive)
- `Amornizaciones` → `depreciation_amortization`
- Unknown label returns None
- Base map wins on conflict (attempted override to `WRONG_FIELD` rejected)

Overall: `python -m py_compile` passes for both files.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

Files exist:
- FOUND: latam_extractor.py (modified)
- FOUND: latam_concept_map.py (modified)
- FOUND: data/latam/learned_synonyms.json

Commits exist:
- FOUND: 6d866e7 (Task 1)
- FOUND: 67bbf16 (Task 2)
