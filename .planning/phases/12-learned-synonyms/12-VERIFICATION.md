---
phase: 12-learned-synonyms
verified: 2026-03-12T15:00:00Z
status: human_needed
score: 4/4 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 3/4
  gaps_closed:
    - "Labels matching r'^\\d{4}$' (year column headers like '2020', '2021') are never written to learned_candidates.jsonl — write-time guard added to _append_candidate() in latam_extractor.py"
    - "Aggregate stop-words used standalone ('Total', 'Subtotal', 'Suma', 'Neto') are never written to learned_candidates.jsonl"
    - "get_review_candidates() excludes noise labels already present in the file — _is_noise_label() filter applied at read time in latam_synonym_reviewer.py"
    - "Actionable financial terms like 'Ingresos por actividades ordinarias' still pass through (verified: 135 non-noise candidates in file)"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "End-to-end learning loop: run extraction on MiRed IPS PDF, approve a mapping via the Terminologia Aprendida panel, re-run extraction and confirm the label resolves to the approved canonical"
    expected: "After approval, the label disappears from the pending list and the next extraction populates the corresponding KPI field correctly"
    why_human: "Requires live Streamlit interaction + actual PDF extraction run — cannot verify programmatically"
  - test: "Visual inspection of Terminologia Aprendida panel in LATAM tab — confirm panel now shows actionable financial terms, not year strings or 'Total'"
    expected: "Panel expands to show <= ~20 meaningful candidates at min_seen=2; no '2020', '2021', 'Total' entries visible; Sugerir con Claude shows inline suggestion with confidence badge and reasoning"
    why_human: "Streamlit widget rendering and actual candidate list quality require a running app to assess visually"
---

# Phase 12: Learned Synonyms Verification Report

**Phase Goal:** Build an adaptive financial terminology learning system that captures unmatched Spanish labels from PDF extractions, accumulates candidates, and allows human-reviewed expansion of the concept map — improving extraction coverage over time without risk of silent mis-mappings

**Verified:** 2026-03-12T15:00:00Z
**Status:** human_needed (all automated checks passed; 2 human tests remain from initial verification)
**Re-verification:** Yes — gap closure after plan 07 (noise filter)

---

## Re-Verification Summary

Previous status was `gaps_found` (score 3/4). The gap was SYN-03: the candidate review queue was dominated by noise labels (year column headers, 'Total' aggregates) making the panel nearly unusable.

Plan 07 implemented a dual-layer noise filter:
- Write-time guard in `_append_candidate()` — `_CANDIDATE_YEAR_RE` and `_CANDIDATE_STOP_WORDS` module-level constants; early return before any I/O
- Read-time filter in `get_review_candidates()` — `_is_noise_label()` helper cleans existing 146-record JSONL on every read without mutating the file

Both commits verified present: `87663ca` (write-time filter) and `3dc6dc2` (read-time filter).

Automated test run confirms: `get_review_candidates(min_seen_count=1)` returns 135 candidates with 0 noise labels. No regressions on Truths 1, 2, or 4.

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Unmatched labels with numeric values are captured to data/latam/learned_candidates.jsonl during every extraction run — never blocking the pipeline | VERIFIED | `_append_candidate()` at line 220 of latam_extractor.py; called at lines 418, 507, 673 (all 3 extraction paths: pdfplumber, pymupdf, ocr). File exists with 146 records. |
| 2 | data/latam/learned_synonyms.json is loaded at latam_concept_map import time — approved synonyms immediately affect the next extraction without code changes | VERIFIED | `_LEARNED_SYNONYMS` dict populated at module load (5 seeded entries confirmed); `map_to_canonical('ganancia del año')` returns `'net_income'` at import time. |
| 3 | The "Terminologia Aprendida" panel shows pending candidates with Claude-assisted mapping suggestions on demand, with actionable signal-to-noise ratio | VERIFIED (automated) / HUMAN PENDING (visual) | `_is_noise_label()` confirmed correct for all 14 test cases. `get_review_candidates(min_seen_count=1)` returns 135 candidates, 0 noise labels. Panel wiring verified in app.py. Visual inspection requires running app. |
| 4 | Clicking Approve writes mapping to learned_synonyms.json and resolves on next extraction; Reject excludes label from future review | VERIFIED | `approve_synonym()` + `reject_synonym()` both write to file. `get_review_candidates()` excludes approved/rejected. `learned_synonyms.json` exists with 5 entries. |

**Score:** 4/4 truths verified (automated checks complete; 2 items need human visual confirmation)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `latam_extractor.py` | Noise-filtered _append_candidate() — write-time guard for years + stop-words | VERIFIED | `_CANDIDATE_YEAR_RE = re.compile(r"^\d{4}$")` at line 62; `_CANDIDATE_STOP_WORDS = frozenset({"total","subtotal","suma","neto"})` at line 63; guard at lines 235–241 before `try` block |
| `latam_synonym_reviewer.py` | Read-time noise filter in get_review_candidates() via _is_noise_label() | VERIFIED | `_NOISE_YEAR_RE` at line 58; `_NOISE_STOP_WORDS` at line 59; `_is_noise_label()` at line 62; filter call at line 120 inside `get_review_candidates()` |
| `latam_extractor.py` | Candidate capture: unmatched labels written to learned_candidates.jsonl | VERIFIED | `_CANDIDATES_FILE` at line 59; `_append_candidate()` called at lines 418, 507, 673 |
| `latam_concept_map.py` | learned_synonyms.json merge at import time | VERIFIED | `_load_learned_synonyms()` + `_LEARNED_SYNONYMS` at module level; fallback in `map_to_canonical()` |
| `latam_synonym_reviewer.py` | Claude-assisted mapping suggestion engine | VERIFIED | `CandidateRecord`, `SuggestionResult` dataclasses; `get_review_candidates()`, `suggest_mapping()`, `approve_synonym()`, `reject_synonym()` all present |
| `app.py` | Terminologia Aprendida panel inside LATAM tab | VERIFIED | `_render_synonym_panel()` wired into `_render_latam_tab()`; lazy import; all widget keys prefixed `latam_syn_` |
| `data/latam/learned_candidates.jsonl` | Append-only store of unmatched extraction labels | VERIFIED | File exists, 146 records, correct JSON-lines format |
| `data/latam/learned_synonyms.json` | Approved synonyms store | VERIFIED | File exists with 5 seeded high-confidence entries; loaded at import time |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `latam_extractor._append_candidate()` | No write for year/stop-word labels | `_CANDIDATE_YEAR_RE` + `_CANDIDATE_STOP_WORDS` early return at lines 238–241 | WIRED | Guard precedes `try` block — no I/O attempted for noise labels |
| `latam_synonym_reviewer.get_review_candidates()` | UI candidate list | `_is_noise_label()` filter at line 120 after approved-exclusion check | WIRED | Confirmed: 0 noise labels in output from 146-record file |
| `latam_extractor._extract_pdfplumber()` | `data/latam/learned_candidates.jsonl` | `_append_candidate()` at line 418 | WIRED | Confirmed in source |
| `latam_extractor._extract_pymupdf_text()` | `data/latam/learned_candidates.jsonl` | `_append_candidate()` at line 507 | WIRED | Confirmed in source |
| `latam_extractor._extract_ocr()` | `data/latam/learned_candidates.jsonl` | `_append_candidate()` at line 673 | WIRED | Confirmed in source |
| `latam_concept_map module load` | `data/latam/learned_synonyms.json` | `_load_learned_synonyms()` at module bottom | WIRED | `_LEARNED_SYNONYMS` populated at import; verified via python -c |
| `map_to_canonical()` | `_LEARNED_SYNONYMS` dict | fallback lookup after base map miss | WIRED | `map_to_canonical('ganancia del año')` returns `'net_income'` |
| `latam_syn_suggest_{i}` button | `suggest_mapping()` | lazy import inside `_render_synonym_panel()` | WIRED | Confirmed in app.py source |
| `latam_syn_approve_{i}` button | `approve_synonym()` | lazy import + call in `_render_synonym_panel()` | WIRED | Confirmed in app.py source |
| `latam_syn_reject_{i}` button | `reject_synonym()` | lazy import + call in `_render_synonym_panel()` | WIRED | Confirmed in app.py source |

---

## Requirements Coverage

Note: SYN-01 through SYN-04 are phase-internal requirement IDs defined in plan frontmatter only — they do not appear in .planning/REQUIREMENTS.md (which covers v1.0/v2.0 product requirements). No REQUIREMENTS.md traceability rows point to Phase 12. These IDs are self-contained plan contracts.

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SYN-01 | 12-01 | Capture unmatched labels to learned_candidates.jsonl during extraction | SATISFIED | All 3 extraction paths call `_append_candidate()`; file exists with real data |
| SYN-02 | 12-01 | Load learned_synonyms.json at concept map import time | SATISFIED | `_load_learned_synonyms()` + `_LEARNED_SYNONYMS` at module level; fallback in `map_to_canonical()` |
| SYN-03 | 12-02, 12-03, 12-07 | Terminologia Aprendida panel with Claude suggestion on demand; signal-to-noise ratio allows actionable review | SATISFIED | Panel functional; `suggest_mapping()` works; noise filter confirmed: 0 year/stop-word labels in 135-candidate output |
| SYN-04 | 12-01, 12-03 | Approve writes to learned_synonyms.json; Reject excludes from future review | SATISFIED | `approve_synonym()` + `reject_synonym()` both write to file; `get_review_candidates()` excludes approved/rejected |

---

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `data/latam/learned_candidates.jsonl` | 1 empty-label record (label="", value=null) from test run | Info | Filtered at read time by `get_review_candidates()` — no UI impact |
| None (resolved) | Previously: year strings and 'Total' aggregates in candidate queue | Resolved | Write-time + read-time filter added in plan 07 |

---

## Human Verification Required

### 1. End-to-End Learning Loop

**Test:** Run LatamAgent on MiRed IPS PDF → open LATAM tab → expand Terminologia Aprendida → click Sugerir con Claude on a legitimate financial term → edit if needed → click Aprobar → re-run extraction
**Expected:** The approved label maps to the correct canonical field in the next extraction; the term disappears from the pending review list
**Why human:** Requires live Streamlit interaction combined with an actual PDF extraction run

### 2. Panel Visual Quality After Noise Filter

**Test:** Run `streamlit run app.py`, navigate to LATAM tab, scroll to bottom, expand Terminologia Aprendida, set min_seen to 2
**Expected:** Panel shows a small set of actionable financial terms (no '2020', '2021', 'Total' entries); Sugerir con Claude shows a spinner then inline suggestion with confidence badge; no DuplicateWidgetID errors in terminal
**Why human:** Candidate list quality and Streamlit layout require a running app to assess

---

## Gaps Summary

No automated gaps remain. All four observable truths are verified. The SYN-03 gap from initial verification is fully closed by plan 07's dual-layer noise filter. Two human-verification items carry over from initial verification — these require a running app and are not blockers to phase completion, only to a final "passed" verdict.

---

_Verified: 2026-03-12T15:00:00Z_
_Verifier: Claude (gsd-verifier)_
_Re-verification: Yes (plan 07 gap closure)_
