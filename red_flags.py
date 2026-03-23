"""FLAG-01 / FLAG-02: Pure-Python rules engine reading thresholds from YAML.

Evaluates KPI DataFrames against healthcare sector thresholds from config/red_flags.yaml.
Returns a sorted list of RedFlag objects (Alta first).

Usage:
    from red_flags import evaluate_flags, load_config, RedFlag

    flags = evaluate_flags(kpis_df, financials_df, sector="healthcare")
    for flag in flags:
        print(f"[{flag.severity}] {flag.name}")
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from loguru import logger

# Default config path: config/red_flags.yaml relative to this file
CONFIG_PATH = Path(__file__).parent / "config" / "red_flags.yaml"


@dataclass
class RedFlag:
    """A detected financial red flag with severity and supporting evidence."""

    flag_id: str
    name: str
    description: str
    severity: str  # "Alta" | "Media" | "Baja"
    kpi: str | None  # None for special/multi-year flags
    kpi_value: float | None
    fiscal_year: int | None
    threshold_triggered: dict


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    """Load YAML threshold file.

    If config_path does not exist, logs a warning and returns {} instead of
    raising FileNotFoundError — allows evaluate_flags() to degrade gracefully.

    Args:
        config_path: path to red_flags.yaml

    Returns:
        Parsed YAML dict, or {} if file is missing.
    """
    if not config_path.exists():
        logger.warning(
            f"red_flags.yaml not found at {config_path} — skipping flag evaluation"
        )
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _evaluate_threshold(value: float, threshold: dict) -> bool:
    """Check if value triggers a threshold spec.

    Threshold dict keys: gt, lt, gte, lte.
    All conditions present in the dict must be True for the threshold to trigger.

    Args:
        value: numeric KPI value to test
        threshold: dict with optional keys "gt", "lt", "gte", "lte"

    Returns:
        True if all threshold conditions are satisfied.
    """
    checks: dict[str, Any] = {
        "gt": lambda v, t: v > t,
        "lt": lambda v, t: v < t,
        "gte": lambda v, t: v >= t,
        "lte": lambda v, t: v <= t,
    }
    return all(fn(value, threshold[k]) for k, fn in checks.items() if k in threshold)


def _evaluate_special_flags(
    kpis_sorted: pd.DataFrame,
    financials_sorted: pd.DataFrame,
    config: dict,
) -> list[RedFlag]:
    """Evaluate special flags requiring multi-year or cross-statement logic.

    FLAG-S01: FCO negativo con utilidad positiva (most recent year only)
    FLAG-S02: Perdidas consecutivas >= 2 anos (full history)

    Note: Single-year companies never trigger FLAG-S02 — correct behavior, not a bug.
    Consecutive flags require at least 2 years of data with consecutive negative margins.

    Args:
        kpis_sorted: kpis DataFrame sorted ascending by fiscal_year
        financials_sorted: financials DataFrame sorted ascending by fiscal_year
        config: parsed red_flags.yaml dict

    Returns:
        List of RedFlag objects for triggered special flags.
    """
    flags: list[RedFlag] = []

    # --- FLAG-S01: FCO negativo con utilidad positiva ---
    # operating_cash_flow lives in financials.parquet (not kpis.parquet)
    if (
        "operating_cash_flow" in financials_sorted.columns
        and "net_income" in financials_sorted.columns
    ):
        latest = financials_sorted.iloc[-1]
        fcf = latest.get("operating_cash_flow")
        net = latest.get("net_income")
        if pd.notna(fcf) and pd.notna(net) and fcf < 0 and net > 0:
            flags.append(
                RedFlag(
                    flag_id="FLAG-S01",
                    name="FCO negativo con utilidad positiva",
                    description=(
                        "Flujo de caja operativo negativo mientras la utilidad neta"
                        " es positiva — posible problema de calidad de ganancias"
                    ),
                    severity="Alta",
                    kpi=None,
                    kpi_value=None,
                    fiscal_year=int(latest["fiscal_year"]),
                    threshold_triggered={
                        "operating_cash_flow": float(fcf),
                        "net_income": float(net),
                    },
                )
            )

    # --- FLAG-S02: Perdidas consecutivas ---
    # Uses net_profit_margin from kpis.parquet sorted by fiscal_year
    if "net_profit_margin" in kpis_sorted.columns:
        net_margins = kpis_sorted[["fiscal_year", "net_profit_margin"]].dropna()
        if not net_margins.empty:
            consecutive = 0
            max_consecutive = 0
            last_loss_year: int | None = None

            for _, row in net_margins.iterrows():
                if row["net_profit_margin"] < 0:
                    consecutive += 1
                    last_loss_year = int(row["fiscal_year"])
                    max_consecutive = max(max_consecutive, consecutive)
                else:
                    consecutive = 0

            if max_consecutive >= 2:
                flags.append(
                    RedFlag(
                        flag_id="FLAG-S02",
                        name="Perdidas consecutivas",
                        description=(
                            f"Perdidas netas durante {max_consecutive}"
                            " ano(s) consecutivo(s)"
                        ),
                        severity="Alta",
                        kpi="net_profit_margin",
                        kpi_value=None,
                        fiscal_year=last_loss_year,
                        threshold_triggered={"consecutive_loss_years": max_consecutive},
                    )
                )
            elif max_consecutive == 1:
                flags.append(
                    RedFlag(
                        flag_id="FLAG-S02",
                        name="Perdidas consecutivas",
                        description="Perdida neta en al menos 1 anio reciente",
                        severity="Media",
                        kpi="net_profit_margin",
                        kpi_value=None,
                        fiscal_year=last_loss_year,
                        threshold_triggered={"consecutive_loss_years": max_consecutive},
                    )
                )

    return flags


def evaluate_flags(
    kpis_df: pd.DataFrame,
    financials_df: pd.DataFrame,
    sector: str = "healthcare",
    config_path: Path = CONFIG_PATH,
) -> list[RedFlag]:
    """Evaluate all flags against a company's KPI and financials DataFrames.

    Uses the most recent fiscal year for single-KPI flags.
    Uses full multi-year history for consecutive-loss and FCO flags.
    Loads YAML config once per call (not per flag).

    If config/red_flags.yaml is missing, returns [] with a warning log instead
    of raising FileNotFoundError.

    Args:
        kpis_df: DataFrame from kpis.parquet (columns: fiscal_year + 20 KPI columns)
        financials_df: DataFrame from financials.parquet (columns: fiscal_year + raw fields)
        sector: sector key from YAML config (default: "healthcare")
        config_path: path to red_flags.yaml

    Returns:
        List of RedFlag objects, sorted by severity (Alta first, then Media, then Baja).
    """
    # Load config once — not per flag
    config = load_config(config_path)
    if not config:
        # Missing YAML file already logged in load_config()
        return []

    flags: list[RedFlag] = []

    # Sort both DataFrames by fiscal_year ascending for multi-year logic
    kpis_sorted = kpis_df.sort_values("fiscal_year")
    financials_sorted = financials_df.sort_values("fiscal_year")

    # Latest year row for single-KPI threshold flags
    latest_year = kpis_sorted["fiscal_year"].max()
    latest_kpis = kpis_sorted[kpis_sorted["fiscal_year"] == latest_year].iloc[0]

    # Get sector config (fallback to healthcare if sector not found)
    sector_config = config.get("sectors", {}).get(
        sector, config.get("sectors", {}).get("healthcare", {})
    )

    # --- Single-KPI threshold flags ---
    for flag_spec in sector_config.get("flags", []):
        kpi_name = flag_spec["kpi"]
        if kpi_name not in latest_kpis or pd.isna(latest_kpis[kpi_name]):
            continue

        value = float(latest_kpis[kpi_name])
        triggered_severity = None
        triggered_threshold = None

        # Evaluate in priority order: Alta > Media > Baja
        for severity in ["Alta", "Media", "Baja"]:
            threshold = flag_spec["thresholds"].get(severity)
            if threshold and _evaluate_threshold(value, threshold):
                triggered_severity = severity
                triggered_threshold = threshold
                break

        if triggered_severity:
            flags.append(
                RedFlag(
                    flag_id=flag_spec["id"],
                    name=flag_spec["name"],
                    description=flag_spec["description"],
                    severity=triggered_severity,
                    kpi=kpi_name,
                    kpi_value=value,
                    fiscal_year=int(latest_year),
                    threshold_triggered=triggered_threshold,
                )
            )

    # --- Special multi-year flags ---
    flags.extend(_evaluate_special_flags(kpis_sorted, financials_sorted, config))

    # Sort: Alta > Media > Baja (NOT alphabetically — explicit order required)
    severity_order = {"Alta": 0, "Media": 1, "Baja": 2}
    flags.sort(key=lambda f: severity_order.get(f.severity, 3))

    return flags
