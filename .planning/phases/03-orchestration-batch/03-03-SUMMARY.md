---
phase: 03-orchestration-batch
plan: "03"
subsystem: batch
tags: [batch, cli, tqdm, metadata, run_batch]
dependency_graph:
  requires: [03-01, 03-02, agent.py]
  provides: [run_batch(), __main__ CLI, 20x kpis.parquet]
  affects: [agent.py]
tech_stack:
  added: [tqdm]
  patterns: [sequential batch with per-ticker isolation, argparse CLI, progress bar]
key_files:
  created: []
  modified:
    - C:/Users/Seb/AI 2026/agent.py
decisions:
  - "Sequential batch chosen over async — SEC rate limit is global; concurrent fetches would still serialize at EDGAR"
  - "Per-ticker try/except in run_batch() ensures one failure never aborts remaining tickers"
  - "tqdm progress bar prints to stderr — does not interfere with redirected stdout logging"
  - "AAPL and BRK.B reported skipped_scrape because raw facts.json was already fresh this quarter"
metrics:
  duration_minutes: 10
  completed_date: "2026-02-26"
  tasks_completed: 2
  files_created: 0
  files_modified: 1
---

# Phase 3 Plan 03: Batch Runner & CLI Summary

**One-liner:** `run_batch()` and `__main__` CLI appended to agent.py; full 20-ticker batch completed with 18 success, 2 skipped_scrape, 0 failed.

## What Was Built

`agent.py` extended with batch orchestration (ORCHS-03). No new files — all additions appended to existing agent.py.

### New Symbols Added to agent.py

| Symbol | Type | Purpose |
|--------|------|---------|
| `run_batch()` | module fn | Sequential batch runner over ticker list with tqdm progress |
| `__main__` block | CLI entry | `python agent.py [--force] [TICKER ...]` |

### run_batch() Logic

```python
def run_batch(tickers=None, force_refresh=False, data_dir=DATA_DIR):
    if tickers is None:
        tickers = BASE_TICKERS
    results = {}
    for ticker in tqdm(tickers, desc="Batch"):
        try:
            agent = FinancialAgent(ticker, data_dir)
            result = agent.run(force_refresh=force_refresh)
            results[ticker] = result
        except Exception as e:
            _update_metadata_error(ticker, str(e), data_dir)
            results[ticker] = {"status": "error", "error": str(e)}
    return results
```

Per-ticker isolation: any unhandled exception in FinancialAgent.run() is caught, written to metadata, and batch continues.

### CLI Interface

```
python agent.py                    # batch all 20 BASE_TICKERS
python agent.py --force            # force re-scrape all 20
python agent.py AAPL MSFT          # run specific tickers
python agent.py --force TSLA       # force single ticker
```

## Batch Run Results (2026-02-26)

Full 20-ticker batch executed via `python agent.py`:

| Status | Count | Tickers |
|--------|-------|---------|
| success | 18 | MSFT, NVDA, AMZN, META, GOOGL, GOOG, TSLA, LLY, AVGO, JPM, V, UNH, XOM, MA, JNJ, WMT, PG, HD |
| skipped_scrape | 2 | AAPL, BRK.B (raw facts.json already fresh this quarter) |
| error | 0 | — |

All 20 tickers have `data/clean/{TICKER}/kpis.parquet` confirmed present.

### Output Artifacts Verified

```
data/clean/AAPL/kpis.parquet   ✓
data/clean/MSFT/kpis.parquet   ✓
data/clean/NVDA/kpis.parquet   ✓
data/clean/AMZN/kpis.parquet   ✓
data/clean/META/kpis.parquet   ✓
data/clean/GOOGL/kpis.parquet  ✓
data/clean/GOOG/kpis.parquet   ✓
data/clean/BRK.B/kpis.parquet  ✓
data/clean/TSLA/kpis.parquet   ✓
data/clean/LLY/kpis.parquet    ✓
data/clean/AVGO/kpis.parquet   ✓
data/clean/JPM/kpis.parquet    ✓
data/clean/V/kpis.parquet      ✓
data/clean/UNH/kpis.parquet    ✓
data/clean/XOM/kpis.parquet    ✓
data/clean/MA/kpis.parquet     ✓
data/clean/JNJ/kpis.parquet    ✓
data/clean/WMT/kpis.parquet    ✓
data/clean/PG/kpis.parquet     ✓
data/clean/HD/kpis.parquet     ✓
```

## Commits

| Hash | Task | Description |
|------|------|-------------|
| 4fbc949 | Task 1 | feat(03-03): add run_batch() and __main__ CLI to agent.py |
| a0a4ee3 | Task 2 | feat(03-03): run full 20-ticker batch; all tickers processed successfully |

## Deviations from Plan

None — plan executed exactly as written. AAPL and BRK.B skipped_scrape is expected behavior (cached this quarter).

## Self-Check: PASSED
