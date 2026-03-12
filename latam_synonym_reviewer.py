"""Synonym reviewer: reads learned candidates and suggests canonical field mappings via Claude API.

Does NOT auto-apply suggestions. All suggestions require human approval via the
Streamlit review panel before being written to learned_synonyms.json.
"""
from __future__ import annotations

import json
import os
import re as _re_reviewer
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

_CANDIDATES_FILE = Path("data/latam/learned_candidates.jsonl")
_SYNONYMS_FILE = Path("data/latam/learned_synonyms.json")

# Load canonical field names at module level so dotenv side-effects (if any)
# from latam_concept_map happen before caller code pops env vars in tests.
try:
    from latam_concept_map import LATAM_CONCEPT_MAP as _CONCEPT_MAP
    _CANONICAL_CHOICES: list[str] = list(_CONCEPT_MAP.keys())
except Exception:
    _CANONICAL_CHOICES = [
        "revenue", "cost_of_revenue", "gross_profit", "operating_income",
        "net_income", "total_assets", "total_liabilities", "equity",
        "long_term_debt", "short_term_debt", "cash_and_equivalents",
        "operating_cash_flow", "capital_expenditures", "depreciation_amortization",
        "ebitda", "interest_expense", "income_tax", "inventory",
        "accounts_receivable", "accounts_payable",
    ]


@dataclass
class CandidateRecord:
    label: str
    value: float
    page: int
    section: str
    company: str
    country: str
    pdf: str
    seen_count: int
    companies_seen: list[str]
    timestamp: str


@dataclass
class SuggestionResult:
    label: str
    canonical: Optional[str]          # None if Claude cannot determine
    confidence: str                    # "Alta", "Media", "Baja"
    reasoning: str                     # Spanish explanation for the analyst
    alternative_canonicals: list[str] = field(default_factory=list)


_NOISE_YEAR_RE = _re_reviewer.compile(r"^\d{4}$")
_NOISE_STOP_WORDS = frozenset({"total", "subtotal", "suma", "neto"})


def _is_noise_label(label: str) -> bool:
    """Return True if label is a noise entry (year header or aggregate stop-word).

    Used to filter existing learned_candidates.jsonl records that were captured
    before the write-time filter was added — backwards compatibility clean-up.
    """
    stripped = label.strip()
    if not stripped or len(stripped) < 4:
        return True
    if _NOISE_YEAR_RE.match(stripped):
        return True
    if stripped.lower() in _NOISE_STOP_WORDS:
        return True
    return False


def get_review_candidates(
    min_seen_count: int = 2,
    force_labels: Optional[list[str]] = None,
) -> list[CandidateRecord]:
    """Return candidates eligible for review.

    Eligibility: seen_count >= min_seen_count OR label in force_labels.
    Labels already present in learned_synonyms.json are excluded (already approved).
    Returns [] if learned_candidates.jsonl does not exist.
    """
    if not _CANDIDATES_FILE.exists():
        return []

    # Load already-approved labels to exclude them
    approved_labels: set[str] = set()
    if _SYNONYMS_FILE.exists():
        try:
            entries = json.loads(_SYNONYMS_FILE.read_text(encoding="utf-8"))
            approved_labels = {e.get("label", "").strip().lower() for e in entries}
        except Exception:
            pass

    force_set = {lbl.strip().lower() for lbl in (force_labels or [])}
    candidates: list[CandidateRecord] = []

    with open(_CANDIDATES_FILE, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            label_lower = rec.get("label", "").strip().lower()
            if not label_lower:
                continue
            # Skip already approved
            if label_lower in approved_labels:
                continue
            # Skip noise labels: year column headers and standalone aggregate stop-words
            if _is_noise_label(rec.get("label", "")):
                continue
            # Include if meets threshold or explicitly forced
            seen = rec.get("seen_count", 1)
            if seen >= min_seen_count or label_lower in force_set:
                candidates.append(CandidateRecord(
                    label=rec.get("label", ""),
                    value=rec.get("value", 0.0),
                    page=rec.get("page", 0),
                    section=rec.get("section", ""),
                    company=rec.get("company", ""),
                    country=rec.get("country", ""),
                    pdf=rec.get("pdf", ""),
                    seen_count=seen,
                    companies_seen=rec.get("companies_seen", [rec.get("company", "")]),
                    timestamp=rec.get("timestamp", ""),
                ))

    # Sort: highest seen_count first
    candidates.sort(key=lambda c: c.seen_count, reverse=True)
    return candidates


def suggest_mapping(candidate: CandidateRecord) -> SuggestionResult:
    """Call Claude API (claude-haiku-4-5) to suggest a canonical field for a candidate label.

    Returns SuggestionResult with canonical=None and Baja confidence if:
    - ANTHROPIC_API_KEY is not set
    - Claude API returns an error
    - Claude response cannot be parsed

    Never raises.
    """
    # Use module-level canonical choices (loaded at import time to avoid dotenv side-effects)
    canonical_choices = _CANONICAL_CHOICES

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return SuggestionResult(
            label=candidate.label,
            canonical=None,
            confidence="Baja",
            reasoning="[ANTHROPIC_API_KEY no configurada — configura la variable de entorno para obtener sugerencias automáticas]",
        )

    # Format value magnitude for context
    value = candidate.value
    if value >= 1_000_000_000:
        value_str = f"{value / 1_000_000_000:.1f}B"
    elif value >= 1_000_000:
        value_str = f"{value / 1_000_000:.1f}M"
    elif value >= 1_000:
        value_str = f"{value / 1_000:.1f}K"
    else:
        value_str = str(value)

    prompt = f"""Eres un experto en terminología contable latinoamericana. Tu tarea es mapear una etiqueta financiera en español al campo canónico correcto de un esquema de datos financieros.

Etiqueta encontrada en PDF: "{candidate.label}"
Sección del estado financiero: {candidate.section or "desconocida"}
Magnitud del valor: {value_str} (moneda local)
País: {candidate.country or "desconocido"}
Veces vista en distintas empresas: {candidate.seen_count}

Campos canónicos disponibles (elige UNO):
{json.dumps(canonical_choices, ensure_ascii=False, indent=2)}

Responde ÚNICAMENTE con un objeto JSON con esta estructura exacta:
{{
  "canonical": "<nombre_del_campo_canónico_o_null>",
  "confidence": "<Alta|Media|Baja>",
  "reasoning": "<explicación breve en español, máximo 2 oraciones>",
  "alternatives": ["<campo_alternativo_1>", "<campo_alternativo_2>"]
}}

Si la etiqueta no corresponde a ningún campo canónico, usa null en "canonical" y explica por qué.
Si es un typo o variante de una etiqueta conocida, indícalo en reasoning."""

    try:
        from anthropic import Anthropic

        client = Anthropic(timeout=30.0)
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            system="Eres un experto en contabilidad latinoamericana. Responde siempre con JSON válido y nada más.",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        parsed = json.loads(raw)
        canonical = parsed.get("canonical")
        # Validate canonical is in the allowed list (or None)
        if canonical and canonical not in canonical_choices:
            canonical = None
            parsed["confidence"] = "Baja"
            parsed["reasoning"] = f"[Campo sugerido por Claude no reconocido: {canonical}] " + parsed.get("reasoning", "")

        return SuggestionResult(
            label=candidate.label,
            canonical=canonical,
            confidence=parsed.get("confidence", "Baja"),
            reasoning=parsed.get("reasoning", ""),
            alternative_canonicals=parsed.get("alternatives", []),
        )

    except Exception as exc:  # noqa: BLE001
        try:
            from loguru import logger
            logger.warning(f"suggest_mapping failed for '{candidate.label}': {exc}")
        except Exception:
            pass
        return SuggestionResult(
            label=candidate.label,
            canonical=None,
            confidence="Baja",
            reasoning=f"[Error al consultar Claude API: {type(exc).__name__}]",
        )


def approve_synonym(label: str, canonical: str, approved_by: str = "user") -> None:
    """Append an approved synonym to learned_synonyms.json.

    Creates the file if it does not exist. Skips if label already present (idempotent).
    Never raises.
    """
    try:
        _SYNONYMS_FILE.parent.mkdir(parents=True, exist_ok=True)
        entries: list[dict] = []
        if _SYNONYMS_FILE.exists():
            try:
                entries = json.loads(_SYNONYMS_FILE.read_text(encoding="utf-8"))
            except Exception:
                entries = []

        label_lower = label.strip().lower()
        # Idempotent: skip if already present
        existing = {e.get("label", "").strip().lower() for e in entries}
        if label_lower in existing:
            return

        entries.append({
            "label": label_lower,
            "canonical": canonical,
            "approved_by": approved_by,
            "date": str(date.today()),
        })
        _SYNONYMS_FILE.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        try:
            from loguru import logger
            logger.warning(f"approve_synonym failed: {exc}")
        except Exception:
            pass


def reject_synonym(label: str) -> None:
    """Mark a label as rejected by adding a sentinel entry with canonical=null.

    This prevents it from re-appearing in the review panel.
    Never raises.
    """
    approve_synonym(label=label, canonical="__rejected__", approved_by="user")
