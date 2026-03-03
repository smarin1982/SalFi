# Financial Analysis Dashboard

## What This Is

Sistema de análisis financiero automatizado con dos pipelines paralelos: (1) Pipeline US — scraping de SEC EDGAR para las Top 20 empresas del S&P 500, 10 años de histórico, 20 KPIs calculados automáticamente; (2) Pipeline LATAM — extracción vía scraping web y PDFs de empresas latinoamericanas (públicas, privadas y mixtas), normalización a USD, red flags y reporte ejecutivo. Todo visualizado en un dashboard Streamlit unificado con sección S&P 500 y sección LATAM. Destinado a uso profesional: due diligence, decisiones de crédito, análisis comparativo y presentaciones.

## Core Value

Un analista debe poder analizar la salud financiera de cualquier empresa — S&P 500 o LATAM — en segundos, con KPIs calculados automáticamente, red flags detectadas y un reporte ejecutivo listo para presentar.

## Current Milestone: v2.0 LATAM Financial Analysis Pipeline

**Goal:** Extender el sistema con un pipeline LATAM completo que extrae estados financieros desde websites corporativos y PDFs, normaliza a USD, calcula KPIs, detecta red flags y genera reportes ejecutivos descargables.

**Target features:**
- LATAM web scraper (Playwright) — navega websites, localiza documentos financieros
- PDF extractor (pdfplumber + pytesseract + pymupdf) — extrae tablas de estados financieros
- Currency normalizer (frankfurter API) — conversión a USD al tipo de cambio promedio del período
- Company registry LATAM — identificación por nombre + país; ID regulatorio para búsqueda en entes (Supersalud, SMV, SFC, CMF, CNV, CNBV)
- Web search para contexto sectorial (duckduckgo-search) y fuentes regulatorias
- Dashboard sección LATAM — con input de URL corporativa e integración al dashboard existente
- Red flags con severidad — alertas integradas en dashboard
- Reporte ejecutivo — visualización en dashboard + descarga PDF

## Requirements

### Validated

- ✓ Scraping automático de formularios 10-K desde SEC EDGAR vía CIK con rate-limit — v1.0/Phase 1
- ✓ Pipeline ETL modular: extracción, transformación y carga en archivos Parquet locales — v1.0/Phase 1-2
- ✓ Cálculo automático de 20 KPIs financieros por empresa/año — v1.0/Phase 2
- ✓ Dashboard Streamlit con gráficos comparativos multi-empresa y filtro temporal — v1.0/Phase 4
- ✓ Input dinámico: usuario ingresa un ticker → ETL al instante — v1.0/Phase 4
- ✓ 20 empresas base predefinidas (Top 20 S&P 500) — v1.0/Phase 3
- ✓ Extracción programada al inicio de cada trimestre (Windows Task Scheduler) — v1.0/Phase 5
- ✓ Datos limpios con tratamiento de valores faltantes, outliers preservados — v1.0/Phase 2

### Active

- [ ] Pipeline LATAM: scraping web + extracción de PDFs financieros
- [ ] Normalización de monedas LATAM a USD (tipo de cambio promedio del período)
- [ ] Registro de empresas LATAM por nombre + país con ID regulatorio
- [ ] Búsqueda web de contexto sectorial y fuentes regulatorias
- [ ] Dashboard sección LATAM con input de URL corporativa
- [ ] Red flags con severidad integradas en el dashboard
- [ ] Reporte ejecutivo: visualización en dashboard + descarga PDF

### Out of Scope

- Ajustes por inflación — valores nominales por diseño
- Aplicación web pública o deployment en la nube — es una interfaz local
- Datos intraday o de frecuencia menor a anual
- Output Excel/openpyxl — solo Streamlit dashboard
- Human-in-the-loop por cada herramienta — ETL automatizado (confirmación solo en decisiones críticas)
- Firecrawl y Tavily (APIs de pago) — se usan fallbacks gratuitos; se pueden activar en v3.0

## Context

- **API Key SEC**: `752615f59034781aeb9c4e0613887fa159a63d30e8e50efc25011f745229c59b`
- **Stack US (v1.0)**: Python, edgartools, Streamlit, Plotly, Pandas, PyArrow, loguru
- **Archivos core**: `scraper.py`, `processor.py`, `agent.py`, `app.py`
- **Almacenamiento US**: `data/raw/{TICKER}/facts.json`, `data/clean/{TICKER}/{financials,kpis}.parquet`
- **Stack LATAM (v2.0)**: + Playwright, pdfplumber, pytesseract, pymupdf, requests (frankfurter), duckduckgo-search, weasyprint
- **Almacenamiento LATAM**: `data/latam/{NOMBRE_PAIS}/` — mismo formato Parquet
- **Sector primario**: Salud — empresas públicas, privadas y mixtas con obligación normativa de publicar informes
- **Entes regulatorios LATAM relevantes**: Supersalud (CO), SMV (PE), SFC (CO), CMF (CL), CNV (AR), CNBV (MX)
- **Clase FinancialAgent**: Extensible — el pipeline LATAM reutiliza la misma interfaz con un adaptador diferente

## Constraints

- **Tech stack**: Python local (no Node, no cloud)
- **Rate limit SEC**: Máximo 10 peticiones/segundo — no aplica a LATAM pero respetar cortesía de crawling
- **Datos**: Valores nominales históricos; LATAM normalizado a USD con tipo de cambio promedio del período
- **Coexistencia**: Los dos pipelines son independientes — el pipeline US no se modifica
- **Entregable**: Código comentado y extensible — uso profesional

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Parquet para almacenamiento local | Velocidad de lectura vs CSV/JSON, evita re-scraping | ✓ Good |
| edgartools para extracción US | XBRL-native, rate limiting incorporado | ✓ Good |
| Streamlit + Plotly para UI | Dashboard local rápido, gráficos interactivos | ✓ Good |
| Valores nominales (sin inflación) | Comparabilidad directa con reportes oficiales | ✓ Good |
| Outliers preservados | Datos reales, no suavizados artificialmente | ✓ Good |
| loguru para logging | Consistente en scraper.py y processor.py | ✓ Good |
| Windows Task Scheduler para scheduling | InteractiveToken logon — accede a conda y .env | ✓ Good |
| Playwright (no Firecrawl) para LATAM | Gratuito, maneja JS dinámico, sin API key | — Pending |
| frankfurter API para FX | Gratuita, sin API key, promedio anual disponible | — Pending |
| Identificación LATAM por nombre+país | Empresas no siempre tienen ticker; ID regulatorio como secundario | — Pending |
| Dashboard unificado con dos secciones | Mantener experiencia cohesiva — no apps separadas | — Pending |
| weasyprint para PDF export | Python-nativo, integra con Streamlit download button | — Pending |

---
*Last updated: 2026-03-03 after milestone v2.0 initialization*
