"""Análisis de price impact post-P (Bloque B — requiere precios externos).

Descarga OHLCV diario desde Yahoo Finance y los cachea en la tabla `prices`.
Después responde la pregunta: "¿el ticker sube en los N días siguientes a
una compra P de un insider?".

Filosofía honesta (recordatorio):
- Reportamos `n` siempre. Si `n < 30` añadimos un `warning` explícito.
- La baseline es el return medio de TODAS las ventanas de N días del mismo
  ticker en el período cubierto (no SPY, no factor model — la baseline
  intra-ticker controla por el regime general de ese ticker). Documentación
  de alternativas en comentarios; no las hacemos por ahora.
- Usamos `adj_close` (no `close`) — gestiona splits y dividendos. Crítico
  para que los returns no sean basura ante un split.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Sequence

import pandas as pd

from edgar_insider.analysis.queries import load_prices


def ensure_prices(
    conn: sqlite3.Connection,
    tickers: Iterable[str],
    start: str,
    end: str,
) -> dict[str, int]:
    """Descarga OHLCV en [start, end] para los tickers dados y persiste en `prices`.

    Estrategia simple: pedimos siempre el rango completo a yfinance y dejamos
    que la BBDD haga el dedupe con `INSERT OR REPLACE`. Para 5 tickers y un
    año de histórico son ~10s de fetch — no merece la pena complicar con
    cálculo de fechas faltantes.

    Devuelve dict {ticker: filas_insertadas_o_actualizadas}.

    `INSERT OR REPLACE` (no IGNORE) porque ajustes por split modifican
    retroactivamente todos los `adj_close` — si re-fetcheamos, queremos que
    los datos viejos se actualicen.
    """
    # Importar yfinance aquí (no a nivel de módulo) para que los tests que
    # no usan precios no carguen una dependencia opcional pesada.
    import yfinance as yf

    inserted: dict[str, int] = {}
    for ticker in tickers:
        df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
        if df.empty:
            inserted[ticker] = 0
            continue

        # yfinance devuelve DatetimeIndex con timezone. Normalizamos a date naive.
        df.index = df.index.tz_localize(None).normalize()
        # Columnas: Open, High, Low, Close, Adj Close, Volume, (Dividends, Stock Splits)
        rows = [
            (
                ticker,
                date.strftime("%Y-%m-%d"),
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
                float(row["Adj Close"]),
                int(row["Volume"]),
            )
            for date, row in df.iterrows()
        ]
        conn.executemany(
            """INSERT OR REPLACE INTO prices
               (ticker, date, open, high, low, close, adj_close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        inserted[ticker] = len(rows)
    return inserted


def _compute_post_event_return(prices: pd.DataFrame, event_date: pd.Timestamp, window: int) -> float | None:
    """Return acumulado adj_close en `window` días de TRADING desde event_date.

    Si event_date cae en un día no-trading, usamos el siguiente trading day
    disponible. Si la ventana se va más allá de nuestros precios, devolvemos
    None (no contamos esa observación).
    """
    after = prices.index[prices.index >= event_date]
    if len(after) == 0:
        return None
    start_pos = prices.index.get_loc(after[0])
    end_pos = start_pos + window
    if end_pos >= len(prices):
        return None
    p0 = prices["adj_close"].iloc[start_pos]
    pN = prices["adj_close"].iloc[end_pos]
    if p0 <= 0:
        return None
    return float((pN - p0) / p0)


def post_p_returns(
    conn: sqlite3.Connection,
    ticker: str,
    windows: Sequence[int] = (5, 10, 30),
) -> pd.DataFrame:
    """Returns post-P comparados con baseline de mismo ticker.

    Para cada P transaction del ticker:
      r_post(w) = adj_close[t+w] / adj_close[t] - 1   (w en días de trading)

    Baseline para horizonte w:
      mean({adj_close[d+w]/adj_close[d] - 1  ∀ d en histórico de precios})

    Columnas: window_days, n, mean_return_after_p, median_return_after_p,
              mean_return_baseline, median_return_baseline, diff_mean, warning
    """
    prices = load_prices(conn, ticker)
    if prices.empty:
        return pd.DataFrame(columns=["window_days", "n", "mean_return_after_p",
                                     "median_return_after_p", "mean_return_baseline",
                                     "median_return_baseline", "diff_mean", "warning"])

    p_tx = pd.read_sql_query(
        """SELECT t.transaction_date
           FROM insider_transactions t
           JOIN filings  f ON f.accession_number = t.accession_number
           JOIN issuers  i ON i.cik = f.issuer_cik
           WHERE i.ticker = ? AND t.transaction_code = 'P'""",
        conn,
        params=(ticker,),
        parse_dates=["transaction_date"],
    )

    rows = []
    for w in windows:
        # Returns post-P
        post = [_compute_post_event_return(prices, d, w) for d in p_tx["transaction_date"]]
        post_clean = pd.Series([r for r in post if r is not None], dtype=float)

        # Baseline: TODAS las ventanas de tamaño w en el histórico.
        baseline = (prices["adj_close"].shift(-w) / prices["adj_close"] - 1).dropna()

        n = len(post_clean)
        mean_post = post_clean.mean() if n else None
        med_post = post_clean.median() if n else None
        rows.append({
            "window_days": w,
            "n": n,
            "mean_return_after_p": mean_post,
            "median_return_after_p": med_post,
            "mean_return_baseline": float(baseline.mean()) if len(baseline) else None,
            "median_return_baseline": float(baseline.median()) if len(baseline) else None,
            "diff_mean": (mean_post - float(baseline.mean())) if (n and len(baseline)) else None,
            "warning": (
                f"n={n}: muestra insuficiente para inferencia estadística"
                if n < 30 else None
            ),
        })
    return pd.DataFrame(rows)
