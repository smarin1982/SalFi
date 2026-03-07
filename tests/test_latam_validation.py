"""
Unit tests for the non-UI logic of latam_validation.py.

Only tests pure Python functions (write_meta_json and static source checks).
No Streamlit dependency is required — these tests exercise disk I/O and
business logic only, leaving the Streamlit form rendering to human verification.

Run with:  python -m pytest tests/test_latam_validation.py -v
"""
import json
import re
from pathlib import Path

import pytest

from latam_validation import write_meta_json

# ── Shared fixture data ───────────────────────────────────────────────────────

_BASE_EXTRACTION = {
    "extracted_at": "2026-03-05T10:00:00Z",
    "pdf_path": "data/latam/CO/clinica-test/raw/report.pdf",
    "confidence_ingresos": "Alta",
    "confidence_utilidad_neta": "Media",
    "confidence_total_activos": "Alta",
    "confidence_deuda_total": "Baja",
    "source_page_ingresos": 12,
    "source_page_utilidad_neta": 15,
    "source_page_total_activos": 22,
    "source_page_deuda_total": 22,
    "ingresos": 5_200_000_000.0,
    "utilidad_neta": 312_000_000.0,
    "total_activos": 8_900_000_000.0,
    "deuda_total": 2_100_000_000.0,
}

_BASE_ORIGINAL = {
    "ingresos": 5_200_000_000.0,
    "utilidad_neta": 312_000_000.0,
    "total_activos": 8_900_000_000.0,
    "deuda_total": 2_100_000_000.0,
}


# ── Test 1: write_meta_json — no corrections ──────────────────────────────────

def test_write_meta_json_no_corrections(tmp_path, monkeypatch):
    """No field edited — meta.json written, human_validated=False, empty audit dict."""
    monkeypatch.chdir(tmp_path)

    corrected = dict(_BASE_ORIGINAL)
    original = dict(_BASE_ORIGINAL)

    write_meta_json("clinica-test", "CO", _BASE_EXTRACTION, corrected, original)

    meta_path = tmp_path / "data" / "latam" / "CO" / "clinica-test" / "meta.json"
    assert meta_path.exists(), "meta.json must be created"

    meta = json.loads(meta_path.read_text("utf-8"))
    assert meta["human_validated"] is False
    assert meta["human_validated_fields"] == {}


# ── Test 2: write_meta_json — one correction ──────────────────────────────────

def test_write_meta_json_one_correction(tmp_path, monkeypatch):
    """Ingresos edited — human_validated=True, only ingresos appears in audit dict."""
    monkeypatch.chdir(tmp_path)

    corrected = dict(_BASE_ORIGINAL)
    corrected["ingresos"] = 5_500_000_000.0   # analyst changed this

    original = dict(_BASE_ORIGINAL)

    write_meta_json("clinica-test", "CO", _BASE_EXTRACTION, corrected, original)

    meta_path = tmp_path / "data" / "latam" / "CO" / "clinica-test" / "meta.json"
    meta = json.loads(meta_path.read_text("utf-8"))

    assert meta["human_validated"] is True

    hvf = meta["human_validated_fields"]
    assert "ingresos" in hvf, "Corrected field must appear in human_validated_fields"
    assert hvf["ingresos"]["original"] == 5_200_000_000.0
    assert hvf["ingresos"]["corrected"] == 5_500_000_000.0

    # Other fields must NOT appear since they were not changed
    for field in ("utilidad_neta", "total_activos", "deuda_total"):
        assert field not in hvf, f"Unchanged field {field!r} must not appear in audit dict"


# ── Test 3: write_meta_json — all four fields corrected ──────────────────────

def test_write_meta_json_all_four_corrected(tmp_path, monkeypatch):
    """All four fields changed — human_validated=True, all four in audit dict."""
    monkeypatch.chdir(tmp_path)

    corrected = {
        "ingresos": 5_500_000_000.0,
        "utilidad_neta": 320_000_000.0,
        "total_activos": 9_000_000_000.0,
        "deuda_total": 2_200_000_000.0,
    }
    original = dict(_BASE_ORIGINAL)

    write_meta_json("clinica-test", "CO", _BASE_EXTRACTION, corrected, original)

    meta_path = tmp_path / "data" / "latam" / "CO" / "clinica-test" / "meta.json"
    meta = json.loads(meta_path.read_text("utf-8"))

    assert meta["human_validated"] is True

    hvf = meta["human_validated_fields"]
    for field in ("ingresos", "utilidad_neta", "total_activos", "deuda_total"):
        assert field in hvf, f"Corrected field {field!r} must appear in audit dict"
        assert "original" in hvf[field]
        assert "corrected" in hvf[field]


# ── Test 4: write_meta_json — parent directory created automatically ──────────

def test_write_meta_json_creates_parent_dir(tmp_path, monkeypatch):
    """Deeply nested path that doesn't exist — write_meta_json must not raise."""
    monkeypatch.chdir(tmp_path)

    # tmp_path is fresh — the full nested path definitely does not exist yet
    corrected = dict(_BASE_ORIGINAL)
    original = dict(_BASE_ORIGINAL)

    # Should not raise even though data/latam/MX/empresa-nueva/ doesn't exist
    write_meta_json("empresa-nueva", "MX", _BASE_EXTRACTION, corrected, original)

    meta_path = tmp_path / "data" / "latam" / "MX" / "empresa-nueva" / "meta.json"
    assert meta_path.exists(), "meta.json must be written even when parent dirs are absent"


# ── Test 5: write_meta_json — JSON is valid and confirmed_at is non-empty ─────

def test_write_meta_json_valid_json_and_confirmed_at(tmp_path, monkeypatch):
    """File must be valid UTF-8 JSON and contain a non-empty confirmed_at timestamp."""
    monkeypatch.chdir(tmp_path)

    corrected = dict(_BASE_ORIGINAL)
    original = dict(_BASE_ORIGINAL)

    write_meta_json("clinica-test", "CO", _BASE_EXTRACTION, corrected, original)

    meta_path = tmp_path / "data" / "latam" / "CO" / "clinica-test" / "meta.json"

    # Must parse without error
    meta = json.loads(meta_path.read_text("utf-8"))

    assert "confirmed_at" in meta, "confirmed_at key must be present"
    assert isinstance(meta["confirmed_at"], str), "confirmed_at must be a string"
    assert len(meta["confirmed_at"]) > 0, "confirmed_at must be non-empty"


# ── Test 6: Session state key prefix check (static analysis) ─────────────────

def test_no_unsafe_allow_html_and_key_prefixes():
    """
    Static analysis of latam_validation.py source:
    - Must NOT contain 'unsafe_allow_html'
    - All key= assignments must use 'latam_val_' or 'latam_' prefix
    """
    source_path = Path("C:/Users/Seb/AI 2026/latam_validation.py")
    source = source_path.read_text("utf-8")

    # Check that unsafe_allow_html is not used as a keyword argument
    # (it may appear in docstrings/comments explaining it is NOT used — that is fine)
    assert "unsafe_allow_html=True" not in source, (
        "latam_validation.py must not pass unsafe_allow_html=True to any st call"
    )

    # Extract all key= string literals (handles both single and double quotes)
    # Matches: key="some_value" or key='some_value'
    key_values = re.findall(r'key\s*=\s*["\']([^"\']+)["\']', source)

    # All widget keys must start with 'latam_val_' or 'latam_'
    for key_val in key_values:
        assert key_val.startswith("latam_val_") or key_val.startswith("latam_"), (
            f"Widget key {key_val!r} must use 'latam_val_' or 'latam_' prefix"
        )
