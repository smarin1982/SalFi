# Phase 11: Dashboard & Report - Context

**Gathered:** 2026-03-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Dedicated LATAM section in the existing Streamlit dashboard — analyst enters a corporate URL or uploads a PDF, runs the pipeline, passes the validation panel, and sees KPI cards, red flags, and a downloadable executive report. The S&P 500 section is never modified.

</domain>

<decisions>
## Implementation Decisions

### Layout de la sección LATAM
- `st.tabs(['S&P 500', 'LATAM'])` — tab separado, aislamiento total con la sección US
- Input (URL text input + st.file_uploader) y botón "Run" viven dentro del tab LATAM, no en el sidebar
- Múltiples empresas LATAM: selector dropdown (mismo patrón que S&P 500) — muestra una empresa a la vez
- Feedback durante el pipeline: `st.spinner` con mensajes de progreso por etapa ("Buscando PDF...", "Extrayendo datos...", "Calculando KPIs...")

### KPI cards y evidencia
- Mismo diseño base que los cards de S&P 500 — reutilizar el componente existente
- Añadir badge de país/moneda al card LATAM
- Indicador de fuente: texto pequeño inline debajo del valor KPI (ej: texto gris "fuente: pág. 14") — siempre visible, no tooltip
- Toggle de moneda (Moneda Original / USD) vive arriba de los cards, en la vista de empresa — afecta todos los valores
- Gráficas de tendencia: incluir solo si hay más de 1 año de datos; para empresas nuevas (1 año), mostrar solo valor actual

### Flujo del reporte ejecutivo
- Generación manual: botón "Generar reporte" visible después de que el analista ha revisado KPIs y red flags
- El reporte se renderiza en el dashboard (st.markdown) Y tiene botón de descarga PDF
- 4 secciones: Resumen de Gestión, KPIs Destacados, Red Flags Activas, Contexto Sectorial
- Comparables de web search (2-3 empresas del mismo sector/país via ddgs) van dentro de Contexto Sectorial
- Idioma del reporte: siempre español
- Contenido: solo texto narrativo (sin gráficas/charts en el PDF)
- Valores monetarios: mostrar ambos — moneda original + USD (ej: "COP 4.2B (~USD 1.05M)")

### Librería PDF
- Reportlab o fpdf2 — pure Python, sin dependencias nativas
- WeasyPrint descartado: GTK3/MSYS2 en Windows es complejidad innecesaria para un reporte de texto
- Formato del PDF: header limpio con nombre empresa + país + fecha; texto estructurado por secciones

### Claude's Discretion
- Algoritmo exacto de selección de comparables via ddgs
- Implementación interna del toggle de moneda (recálculo vs caching)
- Manejo de errores si Claude API falla durante generación del reporte
- Estilos tipográficos exactos del PDF
- Prompt engineering para las 4 secciones del reporte

</decisions>

<specifics>
## Specific Ideas

- El reporte es un documento ejecutivo para presentar — no necesita replicar el estilo visual del dashboard, solo ser limpio y profesional
- El toggle de moneda afecta toda la vista de empresa, no card por card
- La fuente del KPI siempre visible (no hover) porque es un dato de confianza clave para el analista

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 11-dashboard-report*
*Context gathered: 2026-03-09*
