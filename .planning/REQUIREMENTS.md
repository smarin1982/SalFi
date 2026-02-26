# Requirements: SP500 Financial Dashboard

**Defined:** 2026-02-24
**Core Value:** Un analista debe poder comparar la salud financiera de cualquier empresa del S&P 500 en segundos — con 10 años de historia y 20 KPIs calculados automáticamente desde datos oficiales de la SEC.

## v1 Requirements

### Extraction (XTRCT)

- [x] **XTRCT-01**: El sistema descarga el JSON oficial de la SEC con mapeo Ticker→CIK al iniciar, permitiendo resolución inmediata de cualquier ticker
- [x] **XTRCT-02**: El sistema implementa un rate-limiter de máximo 10 peticiones/segundo con header User-Agent correcto conforme a políticas de la SEC
- [x] **XTRCT-03**: El sistema extrae formularios 10-K de los últimos 10 años por CIK usando edgartools, accediendo a los endpoints XBRL de la SEC
- [x] **XTRCT-04**: El sistema almacena los datos crudos (facts.json) en `/data/raw/{TICKER}/` como checkpoint antes de cualquier transformación

### Transformation (XFORM)

- [x] **XFORM-01**: El sistema normaliza conceptos XBRL usando un CONCEPT_MAP con listas de prioridad (7+ nombres de concepto por campo) para garantizar cobertura de todas las empresas del Top 20
- [x] **XFORM-02**: El sistema trata valores faltantes usando media/mediana móvil, preserva outliers como datos reales y mantiene valores nominales sin ajuste por inflación
- [x] **XFORM-03**: El sistema calcula automáticamente los 20 KPIs financieros para cada empresa/año: Revenue Growth (YoY), CAGR (10Y), Gross Profit Margin, Operating Margin, Net Profit Margin, EBITDA Margin, ROE, ROA, Current Ratio, Quick Ratio, Cash Ratio, Working Capital, Debt-to-Equity, Debt-to-EBITDA, Interest Coverage, Debt-to-Assets, Asset Turnover, Inventory Turnover, DSO, Cash Conversion Cycle
- [x] **XFORM-04**: El sistema almacena datos limpios y KPIs calculados en formato Parquet en `/data/clean/{TICKER}/` (financials.parquet + kpis.parquet)

### Orchestration (ORCHS)

- [x] **ORCHS-01**: El sistema implementa una clase `FinancialAgent` extensible que orquesta extracción + transformación para un ticker, con `KPI_REGISTRY` para agregar KPIs sin cambios estructurales
- [x] **ORCHS-02**: El sistema detecta si los datos de un ticker ya son del trimestre actual (`needs_update()`) y omite el re-scraping si están vigentes
- [ ] **ORCHS-03**: El sistema ejecuta automáticamente el ETL para el batch de 20 empresas base del S&P 500 (AAPL, MSFT, NVDA, AMZN, META, GOOGL, GOOG, BRK.B, TSLA, LLY, AVGO, JPM, V, UNH, XOM, MA, JNJ, WMT, PG, HD) en la inicialización

### Scheduling (SCHED)

- [ ] **SCHED-01**: El sistema ejecuta el ETL completo al inicio de cada trimestre de forma programada vía Windows Task Scheduler o APScheduler (<4.0), actualizando los datos de todas las empresas cargadas

### Dashboard (DASH)

- [ ] **DASH-01**: El dashboard muestra gráficos de líneas comparativos (Streamlit + Plotly) que permiten seleccionar múltiples empresas simultáneamente para cualquier KPI del catálogo de 20
- [ ] **DASH-02**: El dashboard incluye filtro temporal (slider o selector) para ajustar la ventana de análisis dentro de los 10 años disponibles
- [ ] **DASH-03**: El dashboard incluye un campo de texto donde el usuario ingresa cualquier ticker del S&P 500, el sistema resuelve el CIK, dispara el ETL y agrega la empresa al análisis de forma inmediata
- [ ] **DASH-04**: El dashboard implementa `@st.cache_data` en todas las consultas a Parquet para evitar re-queries en cada interacción del usuario

## v2 Requirements

### Analytical Features

- **ANLYT-01**: Screener multi-métrica (filtrar S&P 500 por combinaciones de KPIs — ej. ROE > 20% AND Debt-to-Equity < 1)
- **ANLYT-02**: Gráficos scatter (correlación entre dos KPIs a través del universo de empresas)
- **ANLYT-03**: Vista normalizada (% of revenue, crecimiento indexado) para comparación eliminando distorsión de tamaño
- **ANLYT-04**: Exportación a CSV/DataFrame para análisis en Jupyter

### Scheduling (extended)

- **SCHED-02**: Detección de stale data (run manifest con timestamps de última actualización)
- **SCHED-03**: Notificación cuando la actualización trimestral completa o falla

### Resilience

- **RESIL-01**: Escritura atómica en ETL (escribe en temp, mueve solo si completa sin error)
- **RESIL-02**: Manejo de restatements (10-K/A) — deduplicación por fecha de filing más reciente
- **RESIL-03**: Flags visuales en el dashboard para eventos M&A que rompen la continuidad de la serie temporal

## Out of Scope

| Feature | Reason |
|---------|--------|
| Ajustes por inflación | Diseño explícito: valores nominales para comparabilidad directa con SEC |
| Datos intraday / precios en tiempo real | Solo 10-K anual; precios de mercado fuera del scope |
| Datos de empresas fuera del S&P 500 | El input dinámico busca solo tickers del índice |
| Deployment en la nube | Interfaz local; no hay requerimiento de acceso remoto |
| Métricas non-GAAP | Solo datos de reportes oficiales SEC |
| Datos de earnings calls / transcripts | Solo estados financieros cuantitativos |
| Chat / AI narratives sobre los datos | Dashboard analítico, no asistente conversacional |
| Datos 10-Q (trimestrales) | Solo anuales en v1 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| XTRCT-01 | Phase 1 | Complete (01-01) |
| XTRCT-02 | Phase 1 | Complete (01-01) |
| XTRCT-03 | Phase 1 | Complete |
| XTRCT-04 | Phase 1 | Complete |
| XFORM-01 | Phase 2 | Complete |
| XFORM-02 | Phase 2 | Complete |
| XFORM-03 | Phase 2 | Complete |
| XFORM-04 | Phase 2 | Complete |
| ORCHS-01 | Phase 3 | Complete |
| ORCHS-02 | Phase 3 | Complete |
| ORCHS-03 | Phase 3 | Pending |
| SCHED-01 | Phase 5 | Pending |
| DASH-01 | Phase 4 | Pending |
| DASH-02 | Phase 4 | Pending |
| DASH-03 | Phase 4 | Pending |
| DASH-04 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-24*
*Last updated: 2026-02-25 after 01-01 completion (XTRCT-01, XTRCT-02 marked complete)*
