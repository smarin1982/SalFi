# Requirements: Financial Analysis Dashboard

**Defined:** 2026-02-24
**Milestone activo:** v2.0 — LATAM Financial Analysis Pipeline
**Core Value:** Un analista debe poder analizar la salud financiera de cualquier empresa — S&P 500 o LATAM — en segundos, con KPIs calculados automáticamente, red flags detectadas y un reporte ejecutivo listo para presentar.

## v1.0 Requirements (Validated)

### Extraction (XTRCT)

- [x] **XTRCT-01**: El sistema descarga el JSON oficial de la SEC con mapeo Ticker→CIK al iniciar, permitiendo resolución inmediata de cualquier ticker — Phase 1
- [x] **XTRCT-02**: El sistema implementa un rate-limiter de máximo 10 peticiones/segundo con header User-Agent correcto conforme a políticas de la SEC — Phase 1
- [x] **XTRCT-03**: El sistema extrae formularios 10-K de los últimos 10 años por CIK usando edgartools — Phase 1
- [x] **XTRCT-04**: El sistema almacena los datos crudos (facts.json) en `/data/raw/{TICKER}/` como checkpoint antes de cualquier transformación — Phase 1

### Transformation (XFORM)

- [x] **XFORM-01**: El sistema normaliza conceptos XBRL usando un CONCEPT_MAP con listas de prioridad — Phase 2
- [x] **XFORM-02**: El sistema trata valores faltantes, preserva outliers y mantiene valores nominales sin ajuste por inflación — Phase 2
- [x] **XFORM-03**: El sistema calcula automáticamente los 20 KPIs financieros para cada empresa/año — Phase 2
- [x] **XFORM-04**: El sistema almacena datos limpios y KPIs en Parquet en `/data/clean/{TICKER}/` — Phase 2

### Orchestration (ORCHS)

- [x] **ORCHS-01**: El sistema implementa `FinancialAgent` con `KPI_REGISTRY` extensible — Phase 3
- [x] **ORCHS-02**: El sistema detecta si los datos son del trimestre actual y omite re-scraping si están vigentes — Phase 3
- [x] **ORCHS-03**: El sistema ejecuta ETL para el batch de 20 empresas base del S&P 500 en la inicialización — Phase 3

### Scheduling (SCHED)

- [x] **SCHED-01**: El sistema ejecuta el ETL completo al inicio de cada trimestre via Windows Task Scheduler — Phase 5

### Dashboard (DASH)

- [x] **DASH-01**: El dashboard muestra gráficos comparativos multi-empresa para cualquier KPI del catálogo — Phase 4
- [x] **DASH-02**: El dashboard incluye filtro temporal para ajustar la ventana de análisis — Phase 4
- [x] **DASH-03**: El dashboard incluye campo de ticker → dispara ETL → agrega empresa al análisis — Phase 4
- [x] **DASH-04**: El dashboard implementa `@st.cache_data` en todas las consultas Parquet — Phase 4

## v2.0 Requirements

### Scraping LATAM (SCRAP)

- [ ] **SCRAP-01**: El sistema usa búsqueda semántica (`ddgs site:empresa.com filetype:pdf "Estado de Situación Financiera"`) como estrategia primaria de descubrimiento de PDFs — Playwright solo como fallback cuando la búsqueda no produce resultados directos
- [ ] **SCRAP-02**: El sistema puede buscar documentos financieros de una empresa en portales regulatorios (Supersalud CO, SMV PE, SFC CO, CMF CL, CNV AR, CNBV MX) usando el ID regulatorio como clave
- [ ] **SCRAP-03**: El sistema ejecuta búsquedas web (ddgs) para obtener contexto sectorial y empresas comparables del sector salud
- [ ] **SCRAP-04**: El analista puede subir manualmente un PDF (drag & drop) en el dashboard como fallback de emergencia cuando el scraper falla por captcha o bloqueo de IP — el pipeline de procesamiento es idéntico independientemente del origen del PDF

### Extracción PDF (PDF)

- [ ] **PDF-01**: El extractor lee PDFs digitales y retorna datos estructurados de balance general, P&L y flujo de caja usando pdfplumber y PyMuPDF, manejando layouts de múltiples columnas y notas al pie
- [ ] **PDF-02**: El extractor activa OCR (pytesseract + Tesseract) automáticamente cuando detecta un PDF escaneado, sin intervención del usuario
- [ ] **PDF-03**: Cada extracción reporta un score de confianza (Alta/Media/Baja) visible en el dashboard
- [ ] **PDF-04**: El extractor registra la ubicación fuente de cada valor extraído (número de página, sección del documento) para trazabilidad del dato

### Normalización de Moneda (FX)

- [ ] **FX-01**: El sistema convierte valores LATAM a USD usando el tipo de cambio promedio del período reportado con estrategia tiered: frankfurter (BRL/MXN) → API secundaria estable (COP/PEN/CLP/ARS)
- [ ] **FX-02**: Las empresas con datos en ARS muestran un banner de baja confianza sobre la volatilidad cambiaria argentina
- [ ] **FX-03**: La sección LATAM del dashboard permite alternar entre vista en moneda original y vista en USD, mostrando el tipo de tasa aplicada (promedio anual / cierre de período) como nota junto a cada valor

### Registro de Empresas LATAM (COMP)

- [ ] **COMP-01**: El analista identifica una empresa LATAM por nombre + país; el sistema genera un slug URL-safe para almacenamiento
- [ ] **COMP-02**: El sistema almacena el ID regulatorio (NIT/RUC/RUT) como identificador secundario para búsqueda en portales
- [ ] **COMP-03**: Los datos LATAM se persisten en `data/latam/{country}/{slug}/` con el mismo esquema Parquet que el pipeline US

### Integración KPI (KPI)

- [ ] **KPI-01**: `latam_processor.py` mapea los datos extraídos al esquema de los 20 KPIs existentes reutilizando `calculate_kpis()` de `processor.py` sin modificarlo
- [ ] **KPI-02**: `LatamAgent` orquesta el pipeline completo (scrape → extraer → normalizar → procesar) con detección de datos desactualizados vía `needs_update()`
- [ ] **KPI-03**: `latam_concept_map.py` contiene un diccionario de sinónimos contables en español para el sector salud que mapea términos LATAM variables ("Ingresos por prestación de servicios", "Ventas de servicios de salud", "Ingresos operacionales", etc.) a los campos estándar del pipeline

### Red Flags (FLAG)

- [ ] **FLAG-01**: El sistema detecta automáticamente red flags financieras (Deuda/EBITDA > 4x, FCO negativo con utilidad positiva, pérdidas consecutivas ≥ 2 años, etc.) y asigna severidad Alta/Media/Baja
- [ ] **FLAG-02**: Los umbrales de red flags son configurables por sector en un archivo YAML

### Validación Humana Lite (VAL)

- [ ] **VAL-01**: Antes de escribir a Parquet, el sistema presenta al analista los valores financieros clave detectados (Ingresos, Utilidad Neta, Total Activos, Deuda) para confirmación o corrección — el pipeline no avanza sin aprobación explícita en esta etapa

### Reporte Ejecutivo (RPT)

- [ ] **RPT-01**: El dashboard renderiza un reporte ejecutivo con secciones: Resumen de Gestión, KPIs destacados, Red Flags activas y Contexto Sectorial comparativo — texto narrativo generado por Claude API (claude-opus-4-6)
- [ ] **RPT-02**: El analista puede descargar el reporte como PDF desde un botón en el dashboard
- [ ] **RPT-03**: El reporte incluye benchmark de 2-3 empresas comparables del sector obtenidas vía web search

### Dashboard LATAM (DASHL)

- [ ] **DASHL-01**: El dashboard tiene una sección LATAM dedicada con campo de ingreso de URL corporativa y opción de drag & drop de PDF para agregar y procesar una empresa nueva
- [ ] **DASHL-02**: La sección LATAM muestra KPI cards, trend charts y red flags usando los mismos componentes visuales que la sección S&P 500
- [ ] **DASHL-03**: La sección S&P 500 existente funciona sin cambios después de integrar la sección LATAM (backwards compatibility verificada con test explícito)
- [ ] **DASHL-04**: Junto a cada valor de KPI en la sección LATAM, el dashboard muestra un enlace o indicador de la página fuente del PDF de donde fue extraído ese dato

## v3.0 Requirements (Deferred)

### APIs de pago
- **PAID-01**: Integración con Firecrawl como scraper principal (mejor manejo de JS complejo)
- **PAID-02**: Integración con Tavily API para web search de mayor calidad

### Scheduling LATAM
- **SCHED-02**: Scheduler trimestral para actualización automática de empresas LATAM registradas

### Analytical Features
- **ANLYT-01**: Screener multi-métrica (filtrar S&P 500 por combinaciones de KPIs)
- **ANLYT-02**: Gráficos scatter (correlación entre dos KPIs)
- **ANLYT-03**: Vista normalizada (% of revenue, crecimiento indexado)
- **ANLYT-04**: Exportación a CSV/DataFrame para Jupyter

## Out of Scope

| Feature | Reason |
|---------|--------|
| Output Excel/openpyxl | Solo Streamlit dashboard — decisión de diseño v2.0 |
| Ajustes por inflación | Valores nominales; toggle moneda original/USD cubre la necesidad |
| Deployment en la nube | Aplicación local |
| Datos intraday o sub-anuales | Solo reportes anuales |
| Firecrawl / Tavily (pago) | Deferido a v3.0; usar fallbacks gratuitos |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| XTRCT-01..04 | Phase 1 | Complete |
| XFORM-01..04 | Phase 2 | Complete |
| ORCHS-01..03 | Phase 3 | Complete |
| SCHED-01 | Phase 5 | Complete |
| DASH-01..04 | Phase 4 | Complete |
| FX-01, FX-02 | Phase 6 | Pending |
| COMP-01, COMP-02, COMP-03 | Phase 6 | Pending |
| SCRAP-01, SCRAP-02, SCRAP-04 | Phase 7 | Pending |
| PDF-01, PDF-02, PDF-03, PDF-04 | Phase 8 | Pending |
| KPI-01, KPI-03 | Phase 8 | Pending |
| SCRAP-03 | Phase 9 | Pending |
| KPI-02 | Phase 9 | Pending |
| FLAG-01, FLAG-02 | Phase 9 | Pending |
| VAL-01 | Phase 10 | Pending |
| FX-03 | Phase 11 | Pending |
| RPT-01, RPT-02, RPT-03 | Phase 11 | Pending |
| DASHL-01, DASHL-02, DASHL-03, DASHL-04 | Phase 11 | Pending |

**Coverage:**
- v2.0 requirements: 26 total (+7 nuevos)
- Mapped to phases: 26
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-24*
*Last updated: 2026-03-03 after v2.0 review — 7 nuevos requisitos incorporados (SCRAP-04, PDF-04, FX-03, KPI-03, VAL-01, DASHL-04 + Phase 10 Human Validation Lite)*
