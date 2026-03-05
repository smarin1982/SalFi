"""Tests for company_registry.py — Phase 06-02.

TDD RED phase: all tests except test_parquet_schema_parity should fail
until company_registry.py is implemented.
"""

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from company_registry import (
    CompanyRecord,
    EXPECTED_FINANCIALS_COLS,
    EXPECTED_KPIS_COLS,
    make_slug,
    make_storage_path,
    write_meta_json,
)


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

def test_slug_with_accents():
    """Spanish accented vowels must be transliterated to ASCII."""
    assert make_slug("Clínica Las Américas") == "clinica-las-americas"


def test_slug_with_parens():
    """Parentheses must be stripped from the slug."""
    assert make_slug("EPS Sánitas (NUEVA)") == "eps-sanitas-nueva"


def test_slug_with_period():
    """Dots and S.A. suffixes must not appear in the slug."""
    result = make_slug("Organización Sanitas S.A.")
    assert isinstance(result, str)
    assert "." not in result
    assert "(" not in result
    assert ")" not in result


def test_slug_deterministic():
    """Same input must always produce the same slug — no randomness."""
    first = make_slug("TEST Ñoño")
    second = make_slug("TEST Ñoño")
    assert first == second


def test_slug_windows_path():
    """Slug must be safe for use as a Windows NTFS directory name."""
    slug = make_slug("Clínica Las Américas")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / slug
        path.mkdir()  # must not raise OSError on Windows
        assert path.exists()


# ---------------------------------------------------------------------------
# CompanyRecord dataclass
# ---------------------------------------------------------------------------

def test_regulatory_id_stored():
    """regulatory_id field must be stored correctly on CompanyRecord."""
    record = CompanyRecord(
        company_name="Test Clínica",
        slug="test-clinica",
        country="colombia",
        regulatory_id="NIT 123",
        regulatory_authority="Supersalud",
        source_url="http://example.com",
        currency_original="COP",
    )
    assert record.regulatory_id == "NIT 123"


# ---------------------------------------------------------------------------
# Storage path
# ---------------------------------------------------------------------------

def test_make_storage_path():
    """make_storage_path must create the directory and return a path containing
    latam/colombia/grupo-keralty."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        path = make_storage_path(base, "Colombia", "grupo-keralty")
        assert path.exists()
        assert "latam/colombia/grupo-keralty" in path.as_posix()


# ---------------------------------------------------------------------------
# meta.json writing
# ---------------------------------------------------------------------------

def test_write_meta_json():
    """write_meta_json must produce a JSON file with required keys."""
    record = CompanyRecord(
        company_name="Clínica Las Américas",
        slug="clinica-las-americas",
        country="colombia",
        regulatory_id="NIT 800.058.016-0",
        regulatory_authority="Supersalud",
        source_url="https://www.supersalud.gov.co",
        currency_original="COP",
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        write_meta_json(path, record)
        meta_file = path / "meta.json"
        assert meta_file.exists()
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert "company_name" in meta
        assert "slug" in meta
        assert "regulatory_id" in meta
        assert "low_confidence_fx" in meta


def test_ars_low_confidence_in_meta():
    """low_confidence_fx=True must be preserved in written meta.json."""
    record = CompanyRecord(
        company_name="Empresa ARS",
        slug="empresa-ars",
        country="argentina",
        regulatory_id="CUIT 30-12345678-9",
        regulatory_authority="SSN",
        source_url="https://example.com",
        currency_original="ARS",
        low_confidence_fx=True,
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        write_meta_json(path, record)
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        assert meta["low_confidence_fx"] is True


# ---------------------------------------------------------------------------
# Parquet schema parity — verifies US pipeline schema is intact
# ---------------------------------------------------------------------------

def test_parquet_schema_parity():
    """US pipeline financials.parquet must match EXPECTED_FINANCIALS_COLS exactly.

    This test should PASS even in the RED phase because it validates the
    reference schema, not the new implementation.
    """
    df = pd.read_parquet("data/clean/AAPL/financials.parquet")
    assert list(df.columns) == EXPECTED_FINANCIALS_COLS, (
        f"Schema mismatch.\nExpected: {EXPECTED_FINANCIALS_COLS}\nGot:      {list(df.columns)}"
    )
