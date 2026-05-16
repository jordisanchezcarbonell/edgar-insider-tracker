"""EDGAR Insider Tracker — dashboard Streamlit (Fase 5).

Lee de `data/edgar.db` (snapshot commiteado al repo para que Community Cloud
arranque sin re-correr el pipeline). Toda la lógica analítica vive en
`src/edgar_insider/analysis/` — esta app es pura orquestación y UI.

Ejecutar local: `streamlit run app.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit Community Cloud no instala el paquete en editable; añadimos src/
# al path manualmente (mismo truco que los scripts/).
REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from edgar_insider.analysis.metrics import (  # noqa: E402
    monthly_activity,
    net_flow_by_category,
    signal_ratio,
    top_insiders_by_p,
)
from edgar_insider.analysis.price_impact import post_p_returns  # noqa: E402
from edgar_insider.analysis.queries import list_tickers, load_prices, load_transactions  # noqa: E402
from edgar_insider.config import DB_PATH  # noqa: E402
from edgar_insider.storage.schema import connect  # noqa: E402
from edgar_insider.ui.charts import (  # noqa: E402
    monthly_activity_chart,
    price_with_p_markers_chart,
)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="EDGAR Insider Tracker",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_conn():
    """Una sola conexión por sesión Streamlit (re-usada entre reruns)."""
    if not DB_PATH.exists():
        st.error(
            f"No existe `{DB_PATH.relative_to(REPO_ROOT)}`. "
            "Ejecuta el pipeline (`scripts/download_initial_batch.py`, "
            "`scripts/load_all.py`, `scripts/fetch_prices.py`) para generarla."
        )
        st.stop()
    return connect(DB_PATH)


@st.cache_data(show_spinner=False)
def cached_transactions(ticker: str) -> pd.DataFrame:
    return load_transactions(get_conn(), ticker=ticker)


@st.cache_data(show_spinner=False)
def cached_prices(ticker: str) -> pd.DataFrame:
    return load_prices(get_conn(), ticker)


@st.cache_data(show_spinner=False)
def cached_post_p(ticker: str, windows: tuple[int, ...]) -> pd.DataFrame:
    return post_p_returns(get_conn(), ticker, windows=windows)


# ---------------------------------------------------------------------------
# Sidebar — filtros
# ---------------------------------------------------------------------------

st.sidebar.title("Filtros")

tickers = list_tickers(get_conn())
if not tickers:
    st.error("La BBDD existe pero está vacía. Ejecuta `python scripts/load_all.py`.")
    st.stop()

ticker = st.sidebar.selectbox("Empresa", tickers, index=0)
tx_all = cached_transactions(ticker)

# Rango de fechas: por defecto, cubre todo lo disponible para el ticker.
if tx_all.empty:
    st.warning(f"No hay transacciones cargadas para {ticker}.")
    st.stop()

min_date = tx_all["transaction_date"].min().date()
max_date = tx_all["transaction_date"].max().date()
date_range = st.sidebar.date_input(
    "Rango de fechas",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)
# st.date_input puede devolver tupla o fecha única según interacción.
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

available_codes = sorted(tx_all["transaction_code"].unique())
selected_codes = st.sidebar.multiselect(
    "Códigos de transacción",
    options=available_codes,
    default=available_codes,
    help="P=compra real, S=venta, F=tax withholding, M=ejercicio derivado, "
         "A=award, G=gift, D=disposición a la empresa",
)

only_p = st.sidebar.toggle("Solo compras P (señal directa)", value=False)
if only_p:
    selected_codes = ["P"]

st.sidebar.markdown("---")
st.sidebar.caption(
    "📊 [Código en GitHub](https://github.com/) · "
    "Datos: [SEC EDGAR](https://www.sec.gov/edgar.shtml) + Yahoo Finance"
)

# ---------------------------------------------------------------------------
# Filtros aplicados
# ---------------------------------------------------------------------------

start_ts = pd.Timestamp(start_date)
end_ts = pd.Timestamp(end_date)
tx = tx_all[
    (tx_all["transaction_date"] >= start_ts)
    & (tx_all["transaction_date"] <= end_ts)
    & (tx_all["transaction_code"].isin(selected_codes))
].copy()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

issuer_name = tx_all["issuer_name"].iloc[0]
st.title(f"{ticker} — {issuer_name}")
st.caption(
    "Análisis de actividad insider sobre Forms 4 de SEC EDGAR. "
    "Sin scores compuestos: cada métrica responde una pregunta verificable."
)

# KPIs sobre el conjunto filtrado
sig = signal_ratio(tx) if not tx.empty else pd.DataFrame()
n_tx = len(tx)
n_insiders = tx["insider_cik"].nunique() if not tx.empty else 0
p_share = sig["p_share"].iloc[0] if not sig.empty else 0.0
planned_s_share = sig["planned_s_share"].iloc[0] if not sig.empty else 0.0

k1, k2, k3, k4 = st.columns(4)
k1.metric("Transacciones", f"{n_tx}")
k2.metric("Insiders únicos", f"{n_insiders}")
k3.metric("% compras P (señal)", f"{p_share:.1%}")
k4.metric("% S bajo plan 10b5-1", f"{planned_s_share:.1%}",
          help="Las ventas bajo Rule 10b5-1 están pre-agendadas: menor valor informativo")

st.markdown("")

if tx.empty:
    st.info("No hay transacciones para los filtros actuales. Ajusta el sidebar.")
    st.stop()

# ---------------------------------------------------------------------------
# Sección: Actividad mensual
# ---------------------------------------------------------------------------

st.subheader("Actividad mensual por código")
st.caption(
    "Las compras P (verde) son el único código que representa una decisión "
    "discrecional de poner dinero. El resto es comp / vesting / ejercicios."
)
st.plotly_chart(monthly_activity_chart(monthly_activity(tx)), width="stretch")

# ---------------------------------------------------------------------------
# Sección: Precio + marcadores P
# ---------------------------------------------------------------------------

st.subheader("Precio del ticker con compras P marcadas")
st.caption(
    "Triángulos verdes = días en que un insider compró en mercado abierto. "
    "Hover para insider, shares y precio reportado por la SEC."
)
prices = cached_prices(ticker)
p_for_chart = tx_all[tx_all["transaction_code"] == "P"]  # P sin filtros temporales para contexto
st.plotly_chart(
    price_with_p_markers_chart(prices, p_for_chart, ticker),
    width="stretch",
)

# ---------------------------------------------------------------------------
# Sección: Top insiders por P
# ---------------------------------------------------------------------------

st.subheader("Top insiders por compras P")
top = top_insiders_by_p(tx, top_n=10)
if top.empty:
    st.info("Ningún insider hizo compras P en este rango/filtros.")
else:
    st.dataframe(
        top[["insider_name", "n_p", "notional_usd", "first_p_date", "last_p_date"]].rename(
            columns={
                "insider_name": "Insider",
                "n_p": "Nº compras",
                "notional_usd": "Notional USD",
                "first_p_date": "1ª compra",
                "last_p_date": "Última compra",
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Notional USD": st.column_config.NumberColumn(format="$%.0f"),
        },
    )

# ---------------------------------------------------------------------------
# Sección: Tabla de transacciones filtrable
# ---------------------------------------------------------------------------

st.subheader("Transacciones (búsqueda y ordenación en columnas)")
display_cols = [
    "transaction_date", "insider_name", "officer_title",
    "transaction_code", "transaction_category",
    "shares", "price_per_share", "ownership_nature",
    "under_10b5_1_plan", "indirect_owner_explanation",
]
tx_display = tx[display_cols].copy()
tx_display["transaction_date"] = tx_display["transaction_date"].dt.strftime("%Y-%m-%d")
st.dataframe(
    tx_display.rename(columns={
        "transaction_date": "Fecha",
        "insider_name": "Insider",
        "officer_title": "Cargo",
        "transaction_code": "Cód.",
        "transaction_category": "Categoría",
        "shares": "Shares",
        "price_per_share": "Precio",
        "ownership_nature": "Tipo",
        "under_10b5_1_plan": "10b5-1",
        "indirect_owner_explanation": "Si indirecto, vehículo",
    }),
    hide_index=True,
    width="stretch",
    height=350,
)

# ---------------------------------------------------------------------------
# Sección: Net flow
# ---------------------------------------------------------------------------

st.subheader("Net flow por categoría")
st.caption(
    "Acquired – Disposed. En 'M' (ejercicio de derivado) ambos lados se compensan "
    "porque ejercer una opción es adquirir acciones + disponer del derivado."
)
nf = net_flow_by_category(tx)
st.dataframe(
    nf.rename(columns={
        "transaction_category": "Categoría",
        "n": "Nº",
        "shares_acquired": "Shares adq.",
        "shares_disposed": "Shares disp.",
        "shares_net": "Shares net",
        "notional_acquired": "$ adq.",
        "notional_disposed": "$ disp.",
        "notional_net": "$ net",
    }).drop(columns=["ticker"]),
    hide_index=True,
    width="stretch",
    column_config={
        col: st.column_config.NumberColumn(format="$%.0f")
        for col in ["$ adq.", "$ disp.", "$ net"]
    },
)

# ---------------------------------------------------------------------------
# Sección: Price impact post-P
# ---------------------------------------------------------------------------

st.subheader("Price impact post-P (returns a +5/+10/+30 días)")
st.caption(
    "Para cada compra P del ticker (en TODO el histórico, no filtrado), "
    "calculamos el return acumulado a N días vs el return medio de cualquier "
    "ventana de N días del mismo ticker (baseline intra-ticker)."
)
pir = cached_post_p(ticker, windows=(5, 10, 30))
if pir.empty:
    st.info(
        "Sin datos: o no hay compras P, o falta cargar precios "
        "(`python scripts/fetch_prices.py`)."
    )
else:
    has_warning = pir["warning"].notna().any()
    if has_warning:
        n_p_total = int(pir["n"].iloc[0])
        st.warning(
            f"⚠️ **Caveat estadístico obligatorio**: N = {n_p_total} compras P. "
            "Muestra insuficiente para inferencia. Estos números son **descriptivos**, "
            "no predictivos. No se pueden derivar p-values ni intervalos de confianza. "
            "Esta limitación es estructural, no un bug del análisis."
        )
    st.dataframe(
        pir.rename(columns={
            "window_days": "Horizonte (días)",
            "n": "N",
            "mean_return_after_p": "Mean post-P",
            "median_return_after_p": "Median post-P",
            "mean_return_baseline": "Mean baseline",
            "median_return_baseline": "Median baseline",
            "diff_mean": "Diff (mean)",
            "warning": "Caveat",
        }),
        hide_index=True,
        width="stretch",
        column_config={
            "Mean post-P": st.column_config.NumberColumn(format="%.2f%%"),
            "Median post-P": st.column_config.NumberColumn(format="%.2f%%"),
            "Mean baseline": st.column_config.NumberColumn(format="%.2f%%"),
            "Median baseline": st.column_config.NumberColumn(format="%.2f%%"),
            "Diff (mean)": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    "Proyecto educativo. Datos: SEC EDGAR (Forms 4) + Yahoo Finance (precios). "
    "Forms 4 se publican con retraso de hasta 2 días tras la transacción — "
    "este dashboard nunca refleja actividad insider en tiempo real."
)
