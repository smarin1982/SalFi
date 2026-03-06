"""
Unit tests for latam_scraper.py — SCRAP-01 and SCRAP-04.

Wave 0 gap: All tests written before implementation.
Expected initial state: all 9 tests fail with ImportError/ModuleNotFoundError.
After implementation (Task 2): all 9 tests pass.

Test coverage:
  - ScraperResult dataclass semantics
  - search() success and no-result paths (mocked ddgs + requests)
  - RatelimitException retry behaviour
  - _download_pdf() magic-byte validation
  - _validate_pdf_magic() true/false
  - handle_upload() save path
  - scrape_with_playwright() thread isolation smoke test (integration)
"""
import pytest
import tempfile
from pathlib import Path
from io import BytesIO
from unittest.mock import patch, MagicMock
import latam_scraper
from latam_scraper import ScraperResult, search, scrape_with_playwright, handle_upload, _validate_pdf_magic


# ---------------------------------------------------------------------------
# 1. ScraperResult dataclass
# ---------------------------------------------------------------------------

def test_scraper_result_ok_false_by_default():
    result = ScraperResult(ok=False, strategy="ddgs", error="none found")
    assert result.failed is True
    assert result.ok is False


# ---------------------------------------------------------------------------
# 2. search() — success path (all network calls mocked)
# ---------------------------------------------------------------------------

def test_search_success_mocked(tmp_path):
    ddgs_results = [{"href": "https://empresa.com/informe-2023.pdf", "title": "Informe", "body": ""}]

    head_resp = MagicMock()
    head_resp.status_code = 200
    head_resp.headers = {"Content-Type": "application/pdf"}

    get_resp = MagicMock()
    get_resp.status_code = 200
    get_resp.iter_content = MagicMock(return_value=[b"%PDF-1.4 fake content"])
    get_resp.raise_for_status = MagicMock()

    with patch("latam_scraper.DDGS") as mock_ddgs_cls, \
         patch("latam_scraper.requests.head", return_value=head_resp), \
         patch("latam_scraper.requests.get", return_value=get_resp), \
         patch("latam_scraper.time.sleep"):

        mock_ddgs_instance = MagicMock()
        mock_ddgs_cls.return_value = mock_ddgs_instance
        mock_ddgs_instance.text.return_value = ddgs_results

        result = search("empresa.com", 2023, out_dir=tmp_path)

    assert result.ok is True
    assert result.strategy == "ddgs"
    assert result.pdf_path is not None
    assert result.pdf_path.name.endswith(".pdf")


# ---------------------------------------------------------------------------
# 3. search() — no PDF href in any result
# ---------------------------------------------------------------------------

def test_search_no_pdf_href(tmp_path):
    ddgs_results = [{"href": "https://empresa.com/page.html", "title": "Informe", "body": ""}]

    with patch("latam_scraper.DDGS") as mock_ddgs_cls, \
         patch("latam_scraper.time.sleep"):

        mock_ddgs_instance = MagicMock()
        mock_ddgs_cls.return_value = mock_ddgs_instance
        mock_ddgs_instance.text.return_value = ddgs_results

        result = search("empresa.com", 2023, out_dir=tmp_path)

    assert result.ok is False
    assert result.error is not None and len(result.error) > 0
    assert result.strategy == "ddgs"


# ---------------------------------------------------------------------------
# 4. search() — RatelimitException triggers retry behaviour
# ---------------------------------------------------------------------------

def test_search_ratelimit_retries(tmp_path):
    from ddgs.exceptions import RatelimitException

    with patch("latam_scraper.DDGS") as mock_ddgs_cls, \
         patch("latam_scraper.time.sleep"):

        mock_ddgs_instance = MagicMock()
        mock_ddgs_cls.return_value = mock_ddgs_instance
        mock_ddgs_instance.text.side_effect = RatelimitException("rate limited")

        result = search("empresa.com", 2023, out_dir=tmp_path)

    assert result.ok is False
    # At least one attempt was recorded with ddgs: prefix
    assert any("ddgs:" in a for a in result.attempts)


# ---------------------------------------------------------------------------
# 5. _download_pdf() — HTML interstitial detected via magic bytes
# ---------------------------------------------------------------------------

def test_download_pdf_validates_magic_bytes(tmp_path):
    from latam_scraper import _download_pdf

    head_resp = MagicMock()
    head_resp.status_code = 200
    head_resp.headers = {"Content-Type": "application/pdf"}

    get_resp = MagicMock()
    get_resp.status_code = 200
    get_resp.iter_content = MagicMock(return_value=[b"<html>CAPTCHA</html>"])
    get_resp.raise_for_status = MagicMock()

    with patch("latam_scraper.requests.head", return_value=head_resp), \
         patch("latam_scraper.requests.get", return_value=get_resp):

        result = _download_pdf(
            url="https://fake.com/report.pdf",
            out_dir=tmp_path,
            strategy="ddgs",
            attempts=[],
        )

    assert result.ok is False
    assert "not a valid PDF" in result.error


# ---------------------------------------------------------------------------
# 6. _validate_pdf_magic() — valid PDF
# ---------------------------------------------------------------------------

def test_validate_pdf_magic_true(tmp_path):
    pdf_file = tmp_path / "valid.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake content")
    assert _validate_pdf_magic(pdf_file) is True


# ---------------------------------------------------------------------------
# 7. _validate_pdf_magic() — HTML file (not a PDF)
# ---------------------------------------------------------------------------

def test_validate_pdf_magic_false(tmp_path):
    html_file = tmp_path / "page.pdf"
    html_file.write_bytes(b"<html>page</html>")
    assert _validate_pdf_magic(html_file) is False


# ---------------------------------------------------------------------------
# 8. handle_upload() — saves file to raw/ and returns ok=True
# ---------------------------------------------------------------------------

def test_handle_upload_saves_file(tmp_path):
    mock_upload = MagicMock()
    mock_upload.getvalue.return_value = b"%PDF-1.4 real pdf content"
    mock_upload.name = "informe-2023.pdf"

    result = handle_upload(uploaded_file=mock_upload, out_dir=tmp_path)

    assert result.ok is True
    assert result.strategy == "upload"
    assert result.pdf_path is not None
    assert result.pdf_path.exists()
    assert result.pdf_path.read_bytes() == b"%PDF-1.4 real pdf content"


# ---------------------------------------------------------------------------
# 9. scrape_with_playwright() — thread isolation smoke test (integration)
#    NOTE: ok may be True or False — either is correct. No exception = pass.
# ---------------------------------------------------------------------------

def test_scrape_with_playwright_returns_result(tmp_path):
    result = scrape_with_playwright(
        base_url="https://example.com",
        year=2023,
        out_dir=tmp_path,
        attempts=[],
    )
    assert isinstance(result, ScraperResult)
    assert result.strategy == "playwright"
    # ok may be False (no PDF on example.com) — that is correct and expected
