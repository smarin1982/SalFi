---
phase: 12-learned-synonyms
plan: 07
subsystem: data-pipeline
tags: [python, jsonl, regex, noise-filter, candidate-queue, latam]

requires:
  - phase: 12-learned-synonyms
    provides: "_append_candidate() write path and get_review_candidates() read path established in plans 01-06"

provides:
  - "Write-time noise guard in _append_candidate() — year-pattern and stop-word labels never reach disk"
  - "_is_noise_label() helper for read-time backwards-compat cleanup of existing noisy JSONL"
  - "get_review_candidates() filters existing noise entries on read — no data loss, no file mutation"

affects: [latam-synonym-review-panel, learned-candidates-queue]

tech-stack:
  added: []
  patterns:
    - "Belt-and-suspenders noise filtering: write-time guard (fast path, no I/O) + read-time filter (backwards compat)"
    - "Module-level compiled regex (_CANDIDATE_YEAR_RE) — not inside function body, reused across calls"
    - "frozenset for O(1) stop-word lookup — lowercase normalisation at check time, not at constant definition"

key-files:
  created: []
  modified:
    - latam_extractor.py
    - latam_synonym_reviewer.py

key-decisions:
  - "[12-07 Noise Filter]: Write-time guard placed BEFORE try block in _append_candidate() — semantic guard, not I/O; noise labels never hit disk write path"
  - "[12-07 Noise Filter]: 'neto' blocked only as standalone whole-string match — 'ingreso neto' (phrase) still passes through"
  - "[12-07 Noise Filter]: learned_candidates.jsonl NOT modified — noise excluded at read time, preserving raw data integrity"
  - "[12-07 Noise Filter]: _is_noise_label() also returns True for len<4 labels — consistent with callers' existing guard; extra safety"

requirements-completed: [SYN-03]

duration: 6min
completed: 2026-03-12
---

# Phase 12 Plan 07: Candidate Queue Noise Filter Summary

**Dual-layer noise filter (write-time + read-time) eliminates year headers and aggregate stop-words from the learned synonym review queue without modifying historical JSONL data**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-12T14:47:32Z
- **Completed:** 2026-03-12T14:53:40Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Write-time guard in `_append_candidate()` prevents future accumulation: labels matching `^\d{4}$` or in `{"total","subtotal","suma","neto"}` return early with no I/O attempted
- Read-time filter `_is_noise_label()` in `latam_synonym_reviewer.py` cleans existing 146-record JSONL on every read — 5 noise labels suppressed, 135 actionable candidates surfaced
- SYN-03 verification gap closed: review panel now shows financial terminology instead of column headers like '2020' (seen 8x) and 'Total' (seen 12x)

## Task Commits

1. **Task 1: Write-time noise filter in _append_candidate()** - `87663ca` (feat)
2. **Task 2: Read-time noise filter in get_review_candidates()** - `3dc6dc2` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `latam_extractor.py` - Added `_CANDIDATE_YEAR_RE`, `_CANDIDATE_STOP_WORDS` module-level constants + early-return guard in `_append_candidate()` before try block
- `latam_synonym_reviewer.py` - Added `import re as _re_reviewer`, `_NOISE_YEAR_RE`, `_NOISE_STOP_WORDS`, `_is_noise_label()` helper, and filter call inside `get_review_candidates()`

## Decisions Made

- Write-time guard placed before the `try:` block (not inside it) — noise check is a semantic gate, not an I/O operation; fast path with zero disk access for noise labels
- `re` imported as `_re_reviewer` alias in `latam_synonym_reviewer.py` since `re` was not previously in scope — private alias avoids polluting module namespace
- `learned_candidates.jsonl` left unmodified — read-time filter handles backwards compatibility without data mutation; raw data preserved for future analysis

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The plan's verification script used `min_seen=1` as parameter name but the function signature uses `min_seen_count`. This was a documentation inconsistency in the plan — the correct parameter name was used in verification.

## Next Phase Readiness

- SYN-03 gap closed: candidate queue signal-to-noise ratio restored
- Review panel now surfaces actionable financial terms for the analyst
- Phase 12 gap closure plans complete; no further queue noise issues expected

---
*Phase: 12-learned-synonyms*
*Completed: 2026-03-12*
