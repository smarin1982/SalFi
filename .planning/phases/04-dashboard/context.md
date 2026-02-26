# Contexto de Fase 4: Dashboard Ejecutivo (CFO-Ready)

## 1. Objetivo del Producto
Desarrollar una interfaz de análisis financiero de alto impacto utilizando **Streamlit**. El dashboard debe permitir a un CFO visualizar rápidamente el rendimiento histórico de **HD (Home Depot)** y **PG (Procter & Gamble)**, con un enfoque en la legibilidad, la sobriedad estética y la agilidad de navegación.

## 2. Experiencia de Usuario (UX/UI)
La interfaz debe sentirse moderna, minimalista y profesional ("Estilo Bloomberg/Financial Times").

### A. Navegación y Control
*   **Selector de Compañía (Smart-Pick):** Ubicado en la parte superior (cerca del título). 
    *   Opciones: [HD, PG, Comparativo].
    *   Si se selecciona "Comparativo", el dashboard debe permitir superponer los datos de ambas compañías en el mismo KPI para análisis de benchmark.
*   **Barra Lateral (KPI Registry):** 
    *   Un listado vertical (Pick-list/Multiselect) con los 20 KPIs disponibles en los archivos `.parquet`.
    *   **Lógica de Visualización:** El usuario selecciona qué KPIs quiere ver. Se recomienda un máximo de 5 simultáneos para mantener el impacto visual.
    *   **Dinamismo:** El área central debe reconfigurarse automáticamente (layout dinámico) para ocupar todo el ancho de pantalla disponible según la cantidad de KPIs seleccionados.

### B. Visualización de Datos (The Main Canvas)
Cada KPI seleccionado se presentará en una "Tarjeta Ejecutiva" que contiene:
1.  **KPI Headline:** Nombre del indicador en tipografía clara.
2.  **Big Number:** Valor más reciente del KPI.
3.  **Delta Pill:** Indicador porcentual de variación vs. el periodo anterior (Verde/Rojo).
4.  **Historical Trend:** Un gráfico de líneas o área (Plotly) que muestre la evolución histórica completa presente en los datos.

## 3. Especificaciones Técnicas
*   **Framework:** Streamlit.
*   **Fuentes de Datos:** Archivos Parquet generados en la Fase 3:
    - `data/clean/HD/kpis.parquet`
    - `data/clean/PG/kpis.parquet`
    - `data/clean/HD/financials.parquet`
    - `data/clean/PG/financials.parquet`
*   **Gráficos:** Utilizar Plotly con un template "plotly_white" o personalizado para un look financiero limpio (sin grids innecesarios, ejes simplificados).
*   **Performance:** Implementar `@st.cache_data` para asegurar que el cambio entre KPIs y Compañías sea instantáneo.

## 4. Restricciones de Diseño
*   **Color Palette:** Uso de colores corporativos sobrios. El color solo debe usarse para resaltar variaciones (Delta) o diferenciar compañías en modo comparativo.
*   **Layout:** Aprovechar el `st.set_page_config(layout="wide")` para maximizar el espacio en monitores ejecutivos.
*   **Simplicidad:** Evitar el desorden visual (clutter). Si un KPI no está seleccionado, no debe ocupar espacio.

## 5. User Persona: El CFO
El usuario final no tiene tiempo para buscar datos. El dashboard debe "entregar" la respuesta de:
- "¿Cómo vamos?" (Número actual)
- "¿Mejor o peor que antes?" (Delta)
- "¿Cuál es la tendencia?" (Gráfico histórico)