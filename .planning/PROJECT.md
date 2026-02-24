# SP500 Financial Dashboard

## What This Is

Sistema de análisis financiero automatizado que realiza Web Scraping de la SEC (EDGAR), procesa estados financieros anuales (10-K) de los últimos 10 años y genera un Dashboard interactivo en Streamlit. Permite comparar las 20 empresas más importantes del S&P 500 por capitalización de mercado, con capacidad de agregar dinámicamente cualquier otro ticker del índice. Destinado a uso profesional: presentaciones, reportes y análisis comparativo para clientes.

## Core Value

Un analista debe poder comparar la salud financiera de cualquier empresa del S&P 500 en segundos — sin hacer scraping manual ni esperar cargas — con 10 años de historia y 20 KPIs calculados automáticamente.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Scraping automático de formularios 10-K desde SEC EDGAR vía CIK con rate-limit (≤10 req/seg)
- [ ] Pipeline ETL modular: extracción, transformación y carga en archivos Parquet locales
- [ ] Cálculo automático de 20 KPIs financieros por empresa/año (crecimiento, rentabilidad, liquidez, solvencia, eficiencia)
- [ ] Dashboard Streamlit con gráficos comparativos de líneas multi-empresa y filtro temporal
- [ ] Input dinámico: usuario ingresa un ticker → sistema busca CIK y dispara ETL al instante
- [ ] 20 empresas base predefinidas (Top 20 S&P 500 por market cap)
- [ ] Extracción programada al inicio de cada trimestre
- [ ] Datos limpios con tratamiento de valores faltantes (media/mediana móvil, valores nominales, outliers preservados)

### Out of Scope

- Ajustes por inflación — se usan valores nominales por diseño
- Aplicación web pública o deployment en la nube — es una interfaz local
- Datos de empresas fuera del S&P 500 — el input dinámico solo busca tickers del índice
- Datos intraday o de frecuencia menor a anual — solo 10-K (anual)

## Context

- **API Key SEC**: `752615f59034781aeb9c4e0613887fa159a63d30e8e50efc25011f745229c59b`
- **Mapeo Ticker-CIK**: Descargar JSON oficial de la SEC al iniciar para resolución inmediata de tickers
- **Almacenamiento**: Carpeta local `/data/` en formato `.parquet` para evitar scraping repetido
- **Stack definido**: Python, edgartools o sec-api, Streamlit, Plotly, Pandas, PyArrow
- **Estructura de código**: 3 archivos principales — `scraper.py`, `processor.py`, `app.py` + `requirements.txt`
- **Top 20 empresas base**: Apple (AAPL), Microsoft (MSFT), Nvidia (NVDA), Amazon (AMZN), Meta (META), Alphabet A (GOOGL), Alphabet C (GOOG), Berkshire Hathaway (BRK.B), Tesla (TSLA), Eli Lilly (LLY), Broadcom (AVGO), JPMorgan Chase (JPM), Visa (V), UnitedHealth (UNH), ExxonMobil (XOM), Mastercard (MA), Johnson & Johnson (JNJ), Walmart (WMT), Procter & Gamble (PG), Home Depot (HD)
- **Clase FinancialAgent**: El agente principal debe ser extensible para nuevas métricas o fuentes de datos

## Constraints

- **Tech stack**: Python local (no Node, no cloud) — arquitectura orientada a ejecución en máquina del usuario
- **Rate limit SEC**: Máximo 10 peticiones/segundo con User-Agent correcto — obligatorio por políticas de la SEC
- **Datos**: Solo valores nominales históricos, sin normalización por inflación
- **Entregable**: Código altamente comentado y extensible — uso profesional requiere mantenibilidad

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Parquet para almacenamiento local | Velocidad de lectura vs CSV/JSON, evita re-scraping | — Pending |
| edgartools/sec-api para extracción | Abstracción sobre EDGAR que respeta rate limits | — Pending |
| Streamlit + Plotly para UI | Dashboard local rápido de construir, gráficos interactivos | — Pending |
| Valores nominales (sin inflación) | Comparabilidad directa con reportes SEC oficiales | — Pending |
| Tratamiento de outliers: preservar | Datos reales, no suavizados artificialmente | — Pending |

---
*Last updated: 2026-02-24 after initialization*
