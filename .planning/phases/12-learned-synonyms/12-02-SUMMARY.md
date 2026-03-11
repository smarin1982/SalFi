---
phase: 12-learned-synonyms
plan: "02"
subsystem: latam
tags: [anthropic, claude-haiku, synonym-review, concept-map, dataclass]

# Dependency graph
requires:
  - phase: 12-01
    provides: learned_candidates.jsonl written by _append_candidate(), learned_synonyms.json loader in latam_concept_map

provides:
  - latam_synonym_reviewer.py with CandidateRecord + SuggestionResult dataclasses
  - get_review_candidates() filtering by seen_count threshold, excluding already-approved labels
  - suggest_mapping() calling claude-haiku-4-5 lazily, degrading gracefully without API key
  - approve_synonym() and reject_synonym() writing to learned_synonyms.json (idempotent, never raise)

affects:
  - 12-03 (review panel Streamlit UI uses these functions as its backend)
  - 12-04 (concept map loader uses learned_synonyms.json which approve_synonym writes)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Module-level import of latam_concept_map to avoid dotenv side-effects inside functions
    - Lazy import of anthropic.Anthropic inside suggest_mapping (only stdlib at module level)
    - All error paths return SuggestionResult (never raise) — graceful API degradation
    - Idempotent write functions use set membership check before appending

key-files:
  created:
    - latam_synonym_reviewer.py
  modified: []

key-decisions:
  - "Module-level latam_concept_map import avoids dotenv side-effects: importing latam_concept_map triggers python-dotenv loading, which would re-populate ANTHROPIC_API_KEY after os.environ.pop(); moving the import to module level ensures dotenv runs before any caller code modifies the environment"
  - "suggest_mapping uses module-level _CANONICAL_CHOICES list (not local import) to prevent key re-injection from dotenv inside the function"

patterns-established:
  - "Lazy Anthropic import: from anthropic import Anthropic inside suggest_mapping body — only stdlib at module level per plan constraint"
  - "Graceful API degradation: all exception paths return SuggestionResult(canonical=None, confidence='Baja', ...) rather than raising"
  - "Idempotent file writer: load existing entries -> check set membership -> append only if missing -> write"

requirements-completed:
  - SYN-03

# Metrics
duration: 4min
completed: 2026-03-11
---

# Phase 12 Plan 02: Synonym Reviewer Summary

**Claude-assisted suggestion engine for LATAM synonym review: get_review_candidates() + suggest_mapping() with claude-haiku-4-5, graceful API-key-absent degradation, and idempotent approve/reject writers**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-11T08:45:33Z
- **Completed:** 2026-03-11T08:49:28Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created `latam_synonym_reviewer.py` with `CandidateRecord` and `SuggestionResult` dataclasses used by the Plan 03 review panel
- `get_review_candidates()` reads `learned_candidates.jsonl`, filters by `seen_count >= min_seen_count` OR `force_labels`, excludes labels already in `learned_synonyms.json`, sorts by descending seen_count
- `suggest_mapping()` calls `claude-haiku-4-5` with Spanish financial terminology context; returns `SuggestionResult(canonical=None, confidence='Baja')` when API key absent or any error occurs — never raises
- `approve_synonym()` and `reject_synonym()` write idempotent entries to `learned_synonyms.json`; `reject_synonym` uses `__rejected__` sentinel to suppress labels from future review

## Task Commits

Each task was committed atomically:

1. **Task 1: Create latam_synonym_reviewer.py with get_review_candidates() and suggest_mapping()** - `830285c` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `latam_synonym_reviewer.py` - Suggestion engine: CandidateRecord/SuggestionResult dataclasses, get_review_candidates(), suggest_mapping(), approve_synonym(), reject_synonym()

## Decisions Made

- **Module-level latam_concept_map import:** `latam_concept_map` triggers `python-dotenv` at import time, which re-populates `ANTHROPIC_API_KEY` in `os.environ`. If the import happened inside `suggest_mapping()`, it would override any prior `os.environ.pop()` call — breaking the "no API key" degradation path. Moving the import to module level ensures dotenv runs at import time so callers can control the environment freely afterward.
- **Module-level `_CANONICAL_CHOICES`:** The canonical field list is extracted into a module-level variable using the results of the latam_concept_map import. This ensures `suggest_mapping()` uses the pre-loaded list without re-triggering dotenv side-effects.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Moved latam_concept_map import to module level to prevent dotenv re-injection**
- **Found during:** Task 1 verification (test 2 assertion failure)
- **Issue:** The original code imported `latam_concept_map` inside `suggest_mapping()`. This import triggered `python-dotenv`, which re-loaded `ANTHROPIC_API_KEY` from `.env` back into `os.environ` AFTER the test had called `os.environ.pop()`. As a result, the API key check `os.environ.get("ANTHROPIC_API_KEY")` saw the key and called the real Claude API instead of returning the graceful "no key" result.
- **Fix:** Moved `from latam_concept_map import LATAM_CONCEPT_MAP` to module level into a `_CANONICAL_CHOICES` variable. `suggest_mapping()` now uses `_CANONICAL_CHOICES` directly — no local import, no dotenv side-effect inside the function.
- **Files modified:** `latam_synonym_reviewer.py`
- **Verification:** All 5 assertions pass including test 2 (`canonical is None`, `confidence == 'Baja'`, `'ANTHROPIC_API_KEY' in reasoning`)
- **Committed in:** `830285c` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug)
**Impact on plan:** Required fix for the "never raises, degrades gracefully" correctness requirement. No scope creep.

## Issues Encountered

The `latam_concept_map.py` module calls `python-dotenv` on import (side-effect from project's `.env` loader). This was not documented and only surfaced during verification. The fix is clean and maintains all plan constraints (lazy Anthropic import, stdlib-only at module level, except for concept map).

## Next Phase Readiness

- `latam_synonym_reviewer.py` is the complete backend for the Plan 03 Streamlit review panel
- `get_review_candidates()`, `suggest_mapping()`, `approve_synonym()`, `reject_synonym()` are all ready to call from the UI
- No blockers for Plan 03

---
*Phase: 12-learned-synonyms*
*Completed: 2026-03-11*
