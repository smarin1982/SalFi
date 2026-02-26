"""
agent.py — Phase 3: Orchestration & Batch
Sole responsibility: coordinate scraper.py + processor.py per ticker.
No XBRL parsing, no SEC API calls, no KPI formulas — those stay in their modules.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from tqdm import tqdm

import scraper   # requires .env with EDGAR_IDENTITY (raises EnvironmentError if missing)
import processor

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"

METADATA_COLUMNS = [
    "ticker", "last_downloaded", "last_processed",
    "fy_count", "status", "error_message", "fields_missing",
]

# GOOG and GOOGL share the same CIK. The batch runs both — each gets its own
# facts.json and Parquet files with identical content. Both are legitimate
# dashboard tickers (Class A vs Class C shares).
BASE_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG",
    "BRK.B", "TSLA", "LLY", "AVGO", "JPM", "V", "UNH",
    "XOM", "MA", "JNJ", "WMT", "PG", "HD",
]


# ---------------------------------------------------------------------------
# Metadata helpers — all state persisted to data/cache/metadata.parquet
# ---------------------------------------------------------------------------

def _load_metadata(data_dir: Path) -> pd.DataFrame:
    """
    Load metadata.parquet indexed by ticker.
    Creates empty DataFrame if file does not exist.
    Forward-compatible: adds missing columns (None default) if schema evolved.
    """
    path = data_dir / "cache" / "metadata.parquet"
    if path.exists():
        df = pd.read_parquet(path).set_index("ticker")
        # Forward-compatible: ensure all expected columns exist
        for col in METADATA_COLUMNS[1:]:  # skip "ticker" (it's the index)
            if col not in df.columns:
                df[col] = None
        return df
    return pd.DataFrame(columns=METADATA_COLUMNS).set_index("ticker")


def _save_metadata(meta: pd.DataFrame, data_dir: Path) -> None:
    """Atomic write of metadata DataFrame to data/cache/metadata.parquet."""
    path = data_dir / "cache" / "metadata.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    meta.reset_index().to_parquet(tmp, index=False, engine="pyarrow")
    if path.exists():
        path.unlink()  # Windows NTFS: unlink before rename
    tmp.rename(path)


def _update_metadata(
    ticker: str,
    result: dict,
    scraped: bool,
    data_dir: Path,
) -> None:
    """
    Upsert one ticker row in metadata.parquet.
    scraped=True  → update last_downloaded to now.
    scraped=False → preserve existing last_downloaded (skip-scrape path).
    Called immediately after each successful ticker run (enables batch resumability).
    """
    meta = _load_metadata(data_dir)
    now = pd.Timestamp.now()

    # Preserve existing last_downloaded when not scraped
    if not scraped and ticker in meta.index:
        last_dl = meta.loc[ticker, "last_downloaded"]
    else:
        last_dl = now

    meta.loc[ticker] = {
        "last_downloaded":  last_dl,
        "last_processed":   now,
        "fy_count":         len(result.get("fiscal_years", [])),
        "status":           result.get("status", "success"),
        "error_message":    result.get("error", None),
        "fields_missing":   ",".join(result.get("fields_missing", [])),
    }
    _save_metadata(meta, data_dir)
    logger.debug(f"Metadata updated for {ticker} (scraped={scraped})")


def _update_metadata_error(ticker: str, error_msg: str, data_dir: Path) -> None:
    """Record a failed ticker in metadata so partial batch runs are visible."""
    meta = _load_metadata(data_dir)
    now = pd.Timestamp.now()
    existing_last_dl = meta.loc[ticker, "last_downloaded"] if ticker in meta.index else None
    meta.loc[ticker] = {
        "last_downloaded":  existing_last_dl,
        "last_processed":   now,
        "fy_count":         0,
        "status":           "error",
        "error_message":    error_msg[:500],  # cap length
        "fields_missing":   None,
    }
    _save_metadata(meta, data_dir)


# ---------------------------------------------------------------------------
# Staleness detection
# ---------------------------------------------------------------------------

def _same_quarter(ts1: pd.Timestamp, ts2: pd.Timestamp) -> bool:
    """
    Returns True if both timestamps fall in the same calendar year AND quarter.
    Q1: Jan-Mar (1), Q2: Apr-Jun (2), Q3: Jul-Sep (3), Q4: Oct-Dec (4).

    Verified edge cases:
      Jan 1 2026  → (2026, 1)
      Mar 31 2026 → (2026, 1) — same ✓
      Apr 1 2026  → (2026, 2) — different ✓
      Dec 31 2026 → (2026, 4)
      Jan 1 2027  → (2027, 1) — different year ✓
    """
    def _q(ts: pd.Timestamp) -> tuple:
        return (ts.year, (ts.month - 1) // 3 + 1)
    return _q(ts1) == _q(ts2)


# ---------------------------------------------------------------------------
# FinancialAgent — ORCHS-01 + ORCHS-02
# ---------------------------------------------------------------------------

class FinancialAgent:
    """
    Orchestrates scraper.py + processor.py for one ticker.
    Stateless between instantiations — all persistent state lives in metadata.parquet.
    Safe to re-run after crashes, safe to call from dashboard.
    """

    def __init__(self, ticker: str, data_dir: Path = DATA_DIR):
        self.ticker = ticker.upper()
        self.data_dir = data_dir

    def needs_update(self) -> bool:
        """
        Returns True if ticker should be re-scraped.
        Re-scrape if: (a) no metadata row exists, OR (b) last_downloaded is not current-quarter.
        Returns False (skip scrape) if data was downloaded this calendar quarter.
        """
        meta = _load_metadata(self.data_dir)
        if self.ticker not in meta.index:
            logger.debug(f"{self.ticker}: no metadata — needs update")
            return True
        last_dl_raw = meta.loc[self.ticker, "last_downloaded"]
        if last_dl_raw is None or pd.isna(last_dl_raw):
            return True
        last_dl = pd.Timestamp(last_dl_raw)
        current = _same_quarter(last_dl, pd.Timestamp.now())
        logger.debug(f"{self.ticker}: last_downloaded={last_dl.date()}, current_quarter={current}")
        return not current

    def run(self, force_refresh: bool = False) -> dict:
        """
        Full ETL for this ticker. Returns result dict with status and processor output.

        Behavior:
        - If needs_update() is False (current-quarter data) AND force_refresh=False:
            Skips scraper.scrape(). Still runs processor.process() to pick up KPI_REGISTRY changes.
            Returns {"status": "skipped_scrape", "ticker": ..., ...processor result...}
        - Otherwise:
            Runs scraper.scrape() then processor.process().
            Returns {"status": "success", "ticker": ..., ...processor result...}

        Raises ValueError (invalid ticker or no XBRL data) — propagates from scraper/processor.
        Raises FileNotFoundError — propagates from processor if facts.json missing.
        """
        logger.info(f"[{self.ticker}] Starting ETL run (force_refresh={force_refresh})")

        if not force_refresh and not self.needs_update():
            logger.info(f"[{self.ticker}] Current-quarter data found — skipping scrape")
            result = processor.process(self.ticker, self.data_dir)
            result["status"] = "skipped_scrape"
            _update_metadata(self.ticker, result, scraped=False, data_dir=self.data_dir)
            logger.info(f"[{self.ticker}] Done (skipped_scrape): {len(result['fiscal_years'])} FY")
            return {"status": "skipped_scrape", "ticker": self.ticker, **result}

        # Full ETL path
        scraper.scrape(self.ticker, force_refresh=force_refresh)
        result = processor.process(self.ticker, self.data_dir)
        result["status"] = "success"
        _update_metadata(self.ticker, result, scraped=True, data_dir=self.data_dir)
        logger.info(f"[{self.ticker}] Done (success): {len(result['fiscal_years'])} FY, "
                    f"{len(result['kpi_columns'])} KPIs")
        return {"status": "success", "ticker": self.ticker, **result}
