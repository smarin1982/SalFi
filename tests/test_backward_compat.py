"""
Backward compatibility tests for Phase 11 LATAM integration.
Verifies S&P 500 section is unaffected by LATAM additions.
Run: pytest tests/test_backward_compat.py -v
"""
import ast
import re
import sys
from pathlib import Path

APP_PATH = Path(__file__).parent.parent / "app.py"
REPORT_GEN_PATH = Path(__file__).parent.parent / "report_generator.py"


def test_app_syntax_valid():
    """app.py must parse without syntax errors."""
    source = APP_PATH.read_text(encoding="utf-8")
    ast.parse(source)  # raises SyntaxError if invalid


def test_no_top_level_latam_imports():
    """
    No LATAM-specific modules imported at app.py module level.
    All LATAM imports must be inside functions (lazy pattern).
    """
    source = APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"anthropic", "fpdf", "kaleido", "LatamAgent", "latam_validation",
                 "latam_processor", "latam_extractor", "latam_scraper", "web_search",
                 "red_flags", "company_registry"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in forbidden, (
                    f"Top-level import of '{alias.name}' in app.py is forbidden — "
                    f"must be lazy (inside function with try/except ImportError)"
                )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in forbidden, (
                f"Top-level 'from {node.module} import ...' in app.py is forbidden — "
                f"must be lazy (inside function with try/except ImportError)"
            )


def test_no_duplicate_widget_keys():
    """All widget key= values in app.py must be unique (no DuplicateWidgetID)."""
    source = APP_PATH.read_text(encoding="utf-8")
    keys = re.findall(r'key=["\']([\w_]+)["\']', source)
    duplicates = [k for k in set(keys) if keys.count(k) > 1]
    assert not duplicates, (
        f"Duplicate widget keys found in app.py: {duplicates}\n"
        f"These will cause streamlit.errors.DuplicateWidgetID at runtime."
    )


def test_all_latam_keys_prefixed():
    """New LATAM widget keys must start with 'latam_'."""
    source = APP_PATH.read_text(encoding="utf-8")
    all_keys = re.findall(r'key=["\']([\w_]+)["\']', source)
    # Known S&P 500 keys (from Phase 4 implementation)
    sp500_keys = {"new_ticker_input", "load_ticker_btn"}
    kpi_keys = {k for k in all_keys if k.startswith("kpi_")}
    latam_keys = {k for k in all_keys if k.startswith("latam_")}
    other_keys = set(all_keys) - sp500_keys - kpi_keys - latam_keys
    assert not other_keys, (
        f"Widget keys found that are neither latam_ prefixed nor known S&P 500 keys: {other_keys}\n"
        f"Add 'latam_' prefix to new LATAM keys."
    )


def test_tabs_structure_present():
    """app.py must use st.tabs(['S&P 500', 'LATAM']) for section isolation."""
    source = APP_PATH.read_text(encoding="utf-8")
    assert "st.tabs" in source, "st.tabs() call not found in app.py — required for DASHL-03 isolation"
    assert '"S&P 500"' in source or "'S&P 500'" in source, "S&P 500 tab label not found"
    assert '"LATAM"' in source or "'LATAM'" in source, "LATAM tab label not found"


def test_report_generator_syntax_valid():
    """report_generator.py must parse without syntax errors."""
    source = REPORT_GEN_PATH.read_text(encoding="utf-8")
    ast.parse(source)


def test_report_generator_no_top_level_sdk_imports():
    """report_generator.py must not import anthropic/fpdf/kaleido at top level."""
    source = REPORT_GEN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"anthropic", "fpdf", "kaleido"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in forbidden, (
                    f"Top-level import of '{alias.name}' in report_generator.py — must be lazy"
                )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in forbidden, (
                f"Top-level 'from {node.module}' in report_generator.py — must be lazy"
            )


def test_report_generator_api_key_guard():
    """generate_executive_report() must have ANTHROPIC_API_KEY guard."""
    source = REPORT_GEN_PATH.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" in source, "ANTHROPIC_API_KEY guard missing from report_generator.py"


def test_report_generator_timeout_set():
    """Claude API client must use explicit timeout (Pitfall 3 mitigation)."""
    source = REPORT_GEN_PATH.read_text(encoding="utf-8")
    assert "timeout=" in source, (
        "Anthropic client timeout= not set in report_generator.py — "
        "add timeout=120.0 to Anthropic() constructor to prevent Pitfall 3"
    )


def test_report_generator_public_api():
    """report_generator.py must expose the three required public functions."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("report_generator", REPORT_GEN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "generate_executive_report"), "Missing generate_executive_report()"
    assert hasattr(mod, "build_pdf_bytes"), "Missing build_pdf_bytes()"
    assert hasattr(mod, "fetch_comparables"), "Missing fetch_comparables()"


def test_build_pdf_bytes_produces_valid_pdf():
    """build_pdf_bytes() must return bytes starting with b'%PDF'."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("report_generator", REPORT_GEN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pdf = mod.build_pdf_bytes(
        "## Test\nContenido de prueba con caracteres: a e i o u n",
        "Empresa Prueba S.A.",
        "CO",
        2024,
    )
    assert isinstance(pdf, bytes), f"Expected bytes, got {type(pdf)}"
    assert pdf[:4] == b"%PDF", f"Not a valid PDF — header: {pdf[:10]}"


def test_generate_report_no_key_returns_error_string():
    """generate_executive_report() returns an error string (not exception) when API key missing."""
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location("report_generator", REPORT_GEN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    orig_key = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        result = mod.generate_executive_report(
            kpis={}, red_flags=[], comparables=[],
            company={"name": "Test", "country": "CO", "currency_original": "COP", "fiscal_year": 2024}
        )
        assert isinstance(result, str), f"Expected str, got {type(result)}"
        assert result.startswith("[Error"), f"Expected error string starting with '[Error', got: {result[:60]}"
    finally:
        if orig_key:
            os.environ["ANTHROPIC_API_KEY"] = orig_key
