"""
tests/test_latam_backfiller.py

Unit tests for latam_backfiller pure-logic functions.

No Playwright, no network, no parquet I/O (except tests that explicitly
create temp parquet files to verify the skip guard).
"""
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from latam_backfiller import (
    _extract_year_from_text,
    _years_already_in_parquet,
    BackfillResult,
    LatamBackfiller,
    BACKFILL_YEARS,
)


# ---------------------------------------------------------------------------
# _extract_year_from_text
# ---------------------------------------------------------------------------

def test_extract_year_url_with_year():
    assert _extract_year_from_text("estados-financieros-2022.pdf") == 2022


def test_extract_year_link_text():
    assert _extract_year_from_text("Ver estados financieros 2021") == 2021


def test_extract_year_ambiguous_returns_none():
    assert _extract_year_from_text("informe_gestion.pdf") is None


def test_extract_year_future_year_ignored():
    future_year = str(datetime.now().year + 2)
    assert _extract_year_from_text(f"report_{future_year}.pdf") is None


def test_extract_year_lower_bound_included():
    """2015 is the minimum accepted year."""
    assert _extract_year_from_text("annual-2015.pdf") == 2015


def test_extract_year_below_lower_bound_ignored():
    """Years before 2015 should not be returned."""
    assert _extract_year_from_text("reporte-2014.pdf") is None


def test_extract_year_current_year_included():
    current = datetime.now().year
    assert _extract_year_from_text(f"estados-{current}.pdf") == current


# ---------------------------------------------------------------------------
# _years_already_in_parquet
# ---------------------------------------------------------------------------

def test_years_already_in_parquet_missing_file(tmp_path):
    result = _years_already_in_parquet(tmp_path / "financials.parquet")
    assert result == set()


def test_years_already_in_parquet_reads_years(tmp_path):
    parquet_path = tmp_path / "financials.parquet"
    df = pd.DataFrame({"fiscal_year": [2021, 2022, 2023], "revenue": [100, 200, 300]})
    df.to_parquet(parquet_path)
    result = _years_already_in_parquet(parquet_path)
    assert result == {2021, 2022, 2023}


def test_years_already_in_parquet_empty_parquet(tmp_path):
    """A parquet with no rows returns an empty set (no crash)."""
    parquet_path = tmp_path / "financials.parquet"
    df = pd.DataFrame({"fiscal_year": pd.Series([], dtype=float)})
    df.to_parquet(parquet_path)
    result = _years_already_in_parquet(parquet_path)
    assert result == set()


# ---------------------------------------------------------------------------
# LatamBackfiller.get_target_years / get_missing_years
# ---------------------------------------------------------------------------

def test_get_target_years_returns_5(tmp_path):
    bf = LatamBackfiller("slug", "CO", tmp_path, "https://example.com")
    years = bf.get_target_years()
    assert len(years) == BACKFILL_YEARS
    current = datetime.now().year
    assert years[0] == current - 1  # most recent completed year


def test_get_target_years_descending(tmp_path):
    bf = LatamBackfiller("slug", "CO", tmp_path, "https://example.com")
    years = bf.get_target_years()
    assert years == sorted(years, reverse=True)


def test_get_missing_years_empty_parquet(tmp_path):
    bf = LatamBackfiller("slug", "CO", tmp_path, "https://example.com")
    missing = bf.get_missing_years()
    assert len(missing) == BACKFILL_YEARS  # all missing when no parquet exists


def test_get_missing_years_skips_existing(tmp_path):
    parquet_path = tmp_path / "financials.parquet"
    current = datetime.now().year
    yr = current - 1
    df = pd.DataFrame({"fiscal_year": [yr], "revenue": [100]})
    df.to_parquet(parquet_path)
    bf = LatamBackfiller("slug", "CO", tmp_path, "https://example.com")
    missing = bf.get_missing_years()
    assert yr not in missing
    assert len(missing) == BACKFILL_YEARS - 1


def test_get_missing_years_all_present(tmp_path):
    """When all 5 target years are in parquet, get_missing_years returns empty list."""
    parquet_path = tmp_path / "financials.parquet"
    current = datetime.now().year
    target_years = [current - i for i in range(1, BACKFILL_YEARS + 1)]
    df = pd.DataFrame({"fiscal_year": target_years})
    df.to_parquet(parquet_path)
    bf = LatamBackfiller("slug", "CO", tmp_path, "https://example.com")
    missing = bf.get_missing_years()
    assert missing == []


# ---------------------------------------------------------------------------
# BackfillResult status values
# ---------------------------------------------------------------------------

def test_backfill_result_statuses():
    r_ok = BackfillResult(year=2022, status="ok")
    assert r_ok.status == "ok"
    assert r_ok.pdf_path is None
    assert r_ok.extraction_result is None
    assert r_ok.confidence is None
    assert r_ok.error_msg is None

    r_skip = BackfillResult(year=2022, status="skipped")
    assert r_skip.status == "skipped"

    r_notfound = BackfillResult(year=2021, status="not_found", error_msg="404")
    assert r_notfound.error_msg == "404"
    assert r_notfound.status == "not_found"

    r_err = BackfillResult(year=2020, status="error", error_msg="timeout")
    assert r_err.status == "error"

    r_low = BackfillResult(year=2019, status="low_conf", confidence="Baja")
    assert r_low.status == "low_conf"
    assert r_low.confidence == "Baja"


def test_backfill_result_with_path(tmp_path):
    """BackfillResult holds a pdf_path when provided."""
    pdf = tmp_path / "report.pdf"
    r = BackfillResult(year=2023, status="ok", pdf_path=pdf)
    assert r.pdf_path == pdf


# ---------------------------------------------------------------------------
# LatamBackfiller skip guard integration (run_year skip path only)
# ---------------------------------------------------------------------------

def test_run_year_returns_skipped_when_year_in_parquet(tmp_path):
    """run_year() returns status='skipped' without downloading when year is present."""
    parquet_path = tmp_path / "financials.parquet"
    df = pd.DataFrame({"fiscal_year": [2022], "revenue": [500]})
    df.to_parquet(parquet_path)
    bf = LatamBackfiller("slug", "CO", tmp_path, "https://example.com")
    result = bf.run_year(year=2022, pdf_url="https://example.com/report.pdf",
                         currency_code="COP")
    assert result.status == "skipped"
    assert result.year == 2022


def test_run_year_force_reextract_bypasses_skip(tmp_path, monkeypatch):
    """force_reextract=True bypasses the skip guard (download will fail without network)."""
    parquet_path = tmp_path / "financials.parquet"
    df = pd.DataFrame({"fiscal_year": [2022], "revenue": [500]})
    df.to_parquet(parquet_path)

    # Monkeypatch _download_pdf to simulate immediate network error
    import latam_backfiller as b

    def _fake_download(url, out_dir, strategy, attempts, timeout=30):
        from latam_scraper import ScraperResult
        return ScraperResult(ok=False, error="simulated network error")

    monkeypatch.setattr(b, "_download_pdf", _fake_download)

    bf = b.LatamBackfiller("slug", "CO", tmp_path, "https://example.com")
    result = bf.run_year(year=2022, pdf_url="https://example.com/report.pdf",
                         currency_code="COP", force_reextract=True)
    # Should NOT be skipped — should attempt download and get not_found
    assert result.status == "not_found"
    assert result.year == 2022
