"""Métricas sobre actividad insider (Bloque A — sin datos externos).

Cada función es pura: recibe un DataFrame plano (típicamente de
`queries.load_transactions`) y devuelve un DataFrame agregado. Cero estado,
cero I/O. Esto hace que sean triviales de testear y reutilizar tanto desde
el CLI como desde la app Streamlit (Fase 5).

Filosofía honesta: **ningún score compuesto con pesos arbitrarios**. Cada
métrica responde una pregunta concreta. Quien interprete combina por sí mismo.
"""

from __future__ import annotations

import pandas as pd


def code_composition(tx: pd.DataFrame) -> pd.DataFrame:
    """Para cada ticker, conteo y % de cada código de transacción.

    columnas: ticker, transaction_code, transaction_category, count, pct
    pct = count / total_transactions_de_ese_ticker
    """
    if tx.empty:
        return pd.DataFrame(columns=["ticker", "transaction_code", "transaction_category", "count", "pct"])

    grouped = (
        tx.groupby(["ticker", "transaction_code", "transaction_category"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )
    totals = grouped.groupby("ticker")["count"].transform("sum")
    grouped["pct"] = grouped["count"] / totals
    return grouped.sort_values(["ticker", "count"], ascending=[True, False]).reset_index(drop=True)


def signal_ratio(tx: pd.DataFrame) -> pd.DataFrame:
    """Ratio de señal: %P sobre el total + %S bajo 10b5-1 sobre todas las S.

    Una P (compra de mercado) es la transacción con más señal (insider pagó
    dinero). Una S bajo plan 10b5-1 está pre-programada con meses de
    antelación, así que es menos informativa que una S no-planificada.

    columnas: ticker, n_total, n_p, p_share, n_s_total, n_s_planned, planned_s_share
    """
    if tx.empty:
        return pd.DataFrame(columns=["ticker", "n_total", "n_p", "p_share",
                                     "n_s_total", "n_s_planned", "planned_s_share"])

    rows = []
    for ticker, grp in tx.groupby("ticker"):
        n_total = len(grp)
        n_p = int((grp["transaction_code"] == "P").sum())
        s_mask = grp["transaction_code"] == "S"
        n_s = int(s_mask.sum())
        n_s_planned = int((s_mask & grp["under_10b5_1_plan"]).sum())
        rows.append({
            "ticker": ticker,
            "n_total": n_total,
            "n_p": n_p,
            "p_share": n_p / n_total if n_total else 0.0,
            "n_s_total": n_s,
            "n_s_planned": n_s_planned,
            "planned_s_share": n_s_planned / n_s if n_s else 0.0,
        })
    return pd.DataFrame(rows).sort_values("ticker").reset_index(drop=True)


def top_insiders_by_p(tx: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Top insiders por nº de compras P. Desempate por notional descendente.

    columnas: ticker, insider_name, n_p, notional_usd, first_p_date, last_p_date
    """
    p_only = tx[tx["transaction_code"] == "P"]
    if p_only.empty:
        return pd.DataFrame(columns=["ticker", "insider_name", "n_p", "notional_usd",
                                     "first_p_date", "last_p_date"])

    agg = (
        p_only.groupby(["ticker", "insider_name"])
        .agg(
            n_p=("transaction_code", "size"),
            notional_usd=("notional_usd", "sum"),
            first_p_date=("transaction_date", "min"),
            last_p_date=("transaction_date", "max"),
        )
        .reset_index()
    )
    # Ordena por count desc, luego notional desc — empates rompen por dinero invertido.
    agg = agg.sort_values(["ticker", "n_p", "notional_usd"], ascending=[True, False, False])
    # top_n por ticker
    return agg.groupby("ticker", group_keys=False).head(top_n).reset_index(drop=True)


def monthly_activity(tx: pd.DataFrame) -> pd.DataFrame:
    """Serie mensual de count(P), S, F, M, A por ticker.

    columnas: ticker, year_month (YYYY-MM), transaction_code, count
    Pivot a "wide" lo hará el caller (CLI / Streamlit) cuando quiera mostrarlo.
    """
    if tx.empty:
        return pd.DataFrame(columns=["ticker", "year_month", "transaction_code", "count"])

    df = tx.copy()
    df["year_month"] = df["transaction_date"].dt.to_period("M").astype(str)
    grouped = (
        df.groupby(["ticker", "year_month", "transaction_code"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )
    return grouped.sort_values(["ticker", "year_month", "transaction_code"]).reset_index(drop=True)


def clustering_days(tx: pd.DataFrame, min_distinct_insiders: int = 2) -> pd.DataFrame:
    """Días en los que ≥N insiders distintos hicieron compras P en el mismo ticker.

    Esto es lo que de verdad merece mirar: una P aislada puede ser ruido, pero
    varios insiders del mismo board comprando el mismo día es una señal mucho
    más sólida (acción coordinada). En nuestro corpus es raro pero significativo
    cuando aparece.

    columnas: ticker, date, n_distinct_insiders, n_transactions, insiders
    """
    p_only = tx[tx["transaction_code"] == "P"]
    if p_only.empty:
        return pd.DataFrame(columns=["ticker", "date", "n_distinct_insiders", "n_transactions", "insiders"])

    agg = (
        p_only.groupby(["ticker", p_only["transaction_date"].dt.date])
        .agg(
            n_distinct_insiders=("insider_cik", "nunique"),
            n_transactions=("id", "size"),
            insiders=("insider_name", lambda s: ", ".join(sorted(set(s)))),
        )
        .reset_index()
        .rename(columns={"transaction_date": "date"})
    )
    return (
        agg[agg["n_distinct_insiders"] >= min_distinct_insiders]
        .sort_values(["ticker", "date"])
        .reset_index(drop=True)
    )


def net_flow_by_category(tx: pd.DataFrame) -> pd.DataFrame:
    """Para cada (ticker, category): acquired, disposed, net en shares y notional.

    A vs D en el campo `acquired_or_disposed` desambigua si la transacción
    suma o resta posición. Notional es NULL en awards/gifts → tratamos
    como 0 para el sumatorio (el conteo `n` lo dice todo).

    columnas: ticker, transaction_category, n, shares_acquired, shares_disposed,
              shares_net, notional_acquired, notional_disposed, notional_net
    """
    if tx.empty:
        return pd.DataFrame(columns=["ticker", "transaction_category", "n",
                                     "shares_acquired", "shares_disposed", "shares_net",
                                     "notional_acquired", "notional_disposed", "notional_net"])

    df = tx.copy()
    df["notional_usd"] = df["notional_usd"].fillna(0.0)
    df["shares_acq"] = df["shares"].where(df["acquired_or_disposed"] == "A", 0.0)
    df["shares_dis"] = df["shares"].where(df["acquired_or_disposed"] == "D", 0.0)
    df["notional_acq"] = df["notional_usd"].where(df["acquired_or_disposed"] == "A", 0.0)
    df["notional_dis"] = df["notional_usd"].where(df["acquired_or_disposed"] == "D", 0.0)

    agg = (
        df.groupby(["ticker", "transaction_category"], as_index=False)
        .agg(
            n=("id", "size"),
            shares_acquired=("shares_acq", "sum"),
            shares_disposed=("shares_dis", "sum"),
            notional_acquired=("notional_acq", "sum"),
            notional_disposed=("notional_dis", "sum"),
        )
    )
    agg["shares_net"] = agg["shares_acquired"] - agg["shares_disposed"]
    agg["notional_net"] = agg["notional_acquired"] - agg["notional_disposed"]
    return agg.sort_values(["ticker", "n"], ascending=[True, False]).reset_index(drop=True)
