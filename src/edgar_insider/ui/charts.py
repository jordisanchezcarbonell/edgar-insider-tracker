"""Figuras Plotly para la app Streamlit (Fase 5).

Mantenemos los plots aquí (no inline en `app.py`) para que sean reutilizables
y testeables: una función Python que devuelve `go.Figure` se puede inspeccionar
desde un notebook, importar desde otro contexto, o testear con un assert sobre
la estructura de la figura.

Decisión visual clave: **P sobresale, ruido se difumina**. La paleta está
diseñada para que un vistazo bastse para ver dónde hay compras reales. Los
demás códigos van en escala de grises/azules, deliberadamente bajos en
saturación.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from edgar_insider.ui.labels import CODE_LEGEND_LABELS

# Paleta jerárquica: P y S son los códigos "decisión consciente"; el resto
# es típicamente vesting / ejercicio / impuestos (no señal direccional).
CODE_COLORS: dict[str, str] = {
    "P": "#16a34a",   # verde sólido — compra real de mercado
    "S": "#ea580c",   # naranja saturado — venta
    "F": "#9ca3af",   # gris medio — tax withholding
    "M": "#94a3b8",   # gris-azulado — ejercicio de derivado
    "A": "#cbd5e1",   # gris claro — award/grant
    "G": "#a78bfa",   # lila tenue — gift
    "D": "#cbd5e1",   # gris claro — disposition to issuer
}

# Orden visual en stacks/leyendas: lo importante arriba.
CODE_ORDER = ["P", "S", "F", "M", "A", "G", "D"]


def _code_legend(code: str) -> str:
    """Texto humano para la leyenda. Fallback al código crudo si no mapeado."""
    return CODE_LEGEND_LABELS.get(code, code)


def _empty_figure(message: str) -> go.Figure:
    """Figura placeholder cuando los filtros no devuelven datos."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5,
        showarrow=False,
        font=dict(size=14, color="#64748b"),
    )
    fig.update_layout(
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(t=20, b=20, l=20, r=20),
        height=300,
    )
    return fig


def monthly_activity_chart(monthly_df: pd.DataFrame) -> go.Figure:
    """Stacked bar de actividad mensual por código de transacción.

    Espera el output de `metrics.monthly_activity`: columnas
    `ticker, year_month, transaction_code, count`.

    La leyenda muestra etiquetas humanas (`"P · Compra de mercado"`) en
    vez del código crudo. Plotly no separa "color key" de "legend label",
    así que mapeamos a una columna derivada antes de pintar.
    """
    if monthly_df.empty:
        return _empty_figure("Sin transacciones para los filtros seleccionados")

    df = monthly_df.copy()
    df["code_label"] = df["transaction_code"].map(_code_legend).fillna(df["transaction_code"])
    # Re-mapeamos las claves de colores y orden a las etiquetas humanas.
    color_map = {_code_legend(c): col for c, col in CODE_COLORS.items()}
    label_order = [_code_legend(c) for c in CODE_ORDER]

    fig = px.bar(
        df,
        x="year_month",
        y="count",
        color="code_label",
        color_discrete_map=color_map,
        category_orders={"code_label": label_order},
        labels={
            "year_month": "Mes",
            "count": "Nº transacciones",
            "code_label": "Código",
        },
    )
    fig.update_layout(
        barmode="stack",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(t=40, b=20, l=10, r=10),
        height=380,
        plot_bgcolor="white",
    )
    # Forzamos categorical: si dejamos que Plotly infiera el tipo, parsea
    # "2026-03" como timestamp y elige ticks irregulares ("Feb 1, Mar 29…")
    # que confunden. Como label discreta, cada mes se muestra una sola vez.
    fig.update_xaxes(showgrid=False, type="category")
    fig.update_yaxes(gridcolor="#e2e8f0")
    return fig


def price_with_p_markers_chart(
    prices_df: pd.DataFrame,
    p_transactions: pd.DataFrame,
    ticker: str,
) -> go.Figure:
    """Serie del precio diario adj_close + marcadores triangulares verdes en cada P.

    `prices_df` indexado por fecha (output de `queries.load_prices`).
    `p_transactions` con columnas insider_name, transaction_date, shares, price_per_share.

    Si una P cae en día no-trading, alineamos al siguiente día con precio
    disponible vía `merge_asof` direction='forward'.
    """
    if prices_df.empty:
        return _empty_figure(
            f"No hay precios cargados para {ticker}. "
            "Ejecuta `python scripts/fetch_prices.py`."
        )

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=prices_df.index,
        y=prices_df["adj_close"],
        mode="lines",
        name="Precio (adj. close)",
        line=dict(color="#0f172a", width=1.5),
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:.2f}<extra></extra>",
    ))

    if not p_transactions.empty:
        # Alinea cada P al siguiente día de trading disponible (P en fin de semana
        # cae al lunes). merge_asof requiere ordenación previa.
        prices_for_merge = (
            prices_df["adj_close"].reset_index().rename(columns={"date": "trading_date"})
        )
        p_sorted = p_transactions.sort_values("transaction_date").copy()
        p_sorted["transaction_date"] = pd.to_datetime(p_sorted["transaction_date"])
        merged = pd.merge_asof(
            p_sorted,
            prices_for_merge,
            left_on="transaction_date",
            right_on="trading_date",
            direction="forward",
        )
        # Filtra los que no encontraron precio (P posteriores al último día de prices).
        merged = merged.dropna(subset=["adj_close"])

        if not merged.empty:
            fig.add_trace(go.Scatter(
                x=merged["trading_date"],
                y=merged["adj_close"],
                mode="markers",
                name="Compra insider (P)",
                marker=dict(
                    color=CODE_COLORS["P"],
                    size=12,
                    symbol="triangle-up",
                    line=dict(color="white", width=1),
                ),
                customdata=merged[["insider_name", "shares", "price_per_share"]].values,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "%{x|%Y-%m-%d}<br>"
                    "%{customdata[1]:,.0f} shares @ $%{customdata[2]:.2f}<extra></extra>"
                ),
            ))

    fig.update_layout(
        xaxis_title=None,
        yaxis_title="Precio ajustado (USD)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(t=40, b=20, l=10, r=10),
        height=400,
        plot_bgcolor="white",
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#e2e8f0")
    return fig
