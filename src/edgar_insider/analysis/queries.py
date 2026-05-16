"""Lectura de SQLite a pandas para la capa de análisis.

Una sola función concentra el JOIN completo (transactions × filings × issuers
× insiders) en un DataFrame plano. Las funciones de `metrics.py` operan
sobre ese DataFrame ya enriquecido — así nadie tiene que repetir el JOIN.

Devolvemos pandas (no listas de Row) porque toda Fase 4 vive en pandas: el
ahorro de conversiones intermedias y la disponibilidad de groupby/pivot
justifican que la frontera SQL→pandas esté justo aquí.
"""

from __future__ import annotations

import sqlite3

import pandas as pd


def load_transactions(conn: sqlite3.Connection, ticker: str | None = None) -> pd.DataFrame:
    """Devuelve todas las transacciones enriquecidas con info de filing/issuer/insider.

    Si `ticker` se pasa, filtra al hacer la query (más rápido que en pandas).
    `notional_usd = shares * price_per_share` se calcula aquí; es NULL cuando
    no hay precio (awards, gifts).
    """
    query = """
    SELECT
        t.id, t.accession_number, t.tx_index_in_filing,
        t.transaction_date, t.transaction_code, t.transaction_category,
        t.is_derivative, t.acquired_or_disposed,
        t.shares, t.price_per_share,
        (t.shares * t.price_per_share) AS notional_usd,
        t.shares_owned_following,
        t.ownership_nature, t.indirect_owner_explanation,
        t.is_director, t.is_officer, t.is_ten_percent_owner, t.is_other, t.officer_title,
        t.footnotes_text,
        f.period_of_report, f.filing_date, f.schema_version,
        f.under_10b5_1_plan, f.not_subject_to_section_16,
        i.cik AS issuer_cik, i.name AS issuer_name, i.ticker,
        ins.cik AS insider_cik, ins.name AS insider_name
    FROM insider_transactions t
    JOIN filings  f   ON f.accession_number = t.accession_number
    JOIN issuers  i   ON i.cik = f.issuer_cik
    JOIN insiders ins ON ins.cik = t.insider_cik
    """
    params: tuple = ()
    if ticker is not None:
        query += " WHERE i.ticker = ?"
        params = (ticker,)
    query += " ORDER BY t.transaction_date, t.id"

    df = pd.read_sql_query(query, conn, params=params, parse_dates=["transaction_date", "period_of_report", "filing_date"])
    # Booleanos a bool (vienen como int 0/1 desde SQLite).
    for col in ("is_derivative", "is_director", "is_officer", "is_ten_percent_owner", "is_other",
                "under_10b5_1_plan", "not_subject_to_section_16"):
        df[col] = df[col].astype(bool)
    return df


def load_prices(conn: sqlite3.Connection, ticker: str) -> pd.DataFrame:
    """Devuelve la serie diaria de precios de un ticker, indexada por fecha."""
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, adj_close, volume "
        "FROM prices WHERE ticker = ? ORDER BY date",
        conn,
        params=(ticker,),
        parse_dates=["date"],
    )
    df = df.set_index("date").sort_index()
    return df


def list_tickers(conn: sqlite3.Connection) -> list[str]:
    """Tickers con datos en BBDD (los que tienen al menos un filing cargado)."""
    rows = conn.execute(
        "SELECT DISTINCT i.ticker FROM issuers i "
        "JOIN filings f ON f.issuer_cik = i.cik ORDER BY i.ticker"
    ).fetchall()
    return [r[0] for r in rows]
