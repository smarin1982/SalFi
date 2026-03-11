---
phase: 12-learned-synonyms
plan: "03"
subsystem: dashboard-ui
tags: [streamlit, latam, synonyms, ui, review-panel]
dependency_graph:
  requires: [12-02]
  provides: [latam-synonym-review-panel]
  affects: [app.py]
tech_stack:
  added: []
  patterns: [lazy-import, session-state-per-row, st.expander-collapsed]
key_files:
  created: []
  modified:
    - app.py
decisions:
  - "_render_synonym_panel() defined before _render_latam_tab() — ensures call site resolves at definition time"
  - "Approved/rejected state stored in learned_synonyms.json (file) NOT session_state — survives app restarts"
  - "Claude suggestion state stored in session_state keyed latam_syn_suggestion_{i} — scoped to current candidate list order"
metrics:
  duration: "2 min"
  completed: "2026-03-11"
  tasks_completed: 1
  files_modified: 1
---

# Phase 12 Plan 03: Terminologia Aprendida Review Panel Summary

One-liner: Streamlit review panel with lazy-imported Claude suggestions, approve/reject controls, and file-persisted synonym state in the LATAM tab.

## What Was Built

Added `_render_synonym_panel()` to `app.py` — a collapsible `st.expander` panel at the bottom of the LATAM tab that closes the synonym learning loop:

- Threshold `number_input` (`latam_syn_min_seen`) filters which unmatched labels are shown
- Each candidate row displays label, seen_count, section from `CandidateRecord`
- "Sugerir con Claude" button calls `suggest_mapping()` lazily, stores `SuggestionResult` in `st.session_state`
- When suggestion is present, `text_input` pre-populated with `suggestion.canonical`; analyst can edit
- "Aprobar" writes mapping to `learned_synonyms.json` via `approve_synonym()` and calls `st.rerun()`
- "Rechazar" writes `__rejected__` sentinel via `reject_synonym()` and calls `st.rerun()`
- Without a suggestion, approve/reject controls still appear so analyst can enter mapping manually
- Empty-state `st.success` message when no candidates meet threshold — no errors shown

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add _render_synonym_panel() to app.py and call from _render_latam_tab() | 4c9c0ac | app.py |

## Deviations from Plan

None — plan executed exactly as written.

## Verification Results

Automated checks passed:
- `ast.parse()` syntax check: OK
- `_render_synonym_panel` defined and called: OK
- All new widget keys have `latam_syn_` prefix (1 static key: `latam_syn_min_seen`): OK
- No duplicate static widget keys: OK
- `latam_synonym_reviewer` not imported at top level: OK
- `python -m py_compile app.py`: PASSED

Manual verification: Pending — see checkpoint report below.

## Self-Check

- [x] `app.py` modified with 126 insertions
- [x] Commit `4c9c0ac` exists
- [x] `_render_synonym_panel` at line 755, `_render_latam_tab` at line 877 (correct order)
- [x] Call site at line 1028 inside `_render_latam_tab`

## Self-Check: PASSED
