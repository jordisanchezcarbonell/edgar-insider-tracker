"""Tests de la capa de análisis (Fase 4).

Estrategia:
- BBDD synthetic en `tmp_path` poblada vía SQL directo. Más controlable que
  parseando XMLs (queremos casos exactos para verificar agregaciones).
- `price_impact` se testea con precios sintéticos insertados a mano — los
  tests deben funcionar OFFLINE, sin tocar yfinance.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from edgar_insider.analysis.metrics import (
    clustering_days,
    code_composition,
    monthly_activity,
    net_flow_by_category,
    signal_ratio,
    top_insiders_by_p,
)
from edgar_insider.analysis.price_impact import post_p_returns
from edgar_insider.analysis.queries import load_transactions, list_tickers
from edgar_insider.storage.schema import connect, create_tables


# ---------------------------------------------------------------------------
# Fixtures y helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = connect(tmp_path / "test.db")
    create_tables(c)
    yield c
    c.close()


def _ensure_issuer(conn, cik: str, ticker: str, name: str = "") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO issuers (cik, name, ticker) VALUES (?, ?, ?)",
        (cik, name or f"Issuer {ticker}", ticker),
    )


def _ensure_insider(conn, cik: str, name: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO insiders (cik, name) VALUES (?, ?)",
        (cik, name),
    )


def _ensure_filing(
    conn,
    accession: str,
    issuer_cik: str,
    *,
    planned_10b5: bool = False,
    period: str = "2026-01-15",
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO filings
           (accession_number, issuer_cik, schema_version, document_type,
            is_amendment, not_subject_to_section_16, under_10b5_1_plan,
            period_of_report, filing_date)
           VALUES (?, ?, 'X0609', '4', 0, 0, ?, ?, ?)""",
        (accession, issuer_cik, int(planned_10b5), period, period),
    )


def add_tx(
    conn,
    *,
    accession: str,
    issuer_cik: str,
    ticker: str,
    insider_cik: str,
    insider_name: str,
    tx_idx: int = 0,
    date: str = "2026-01-15",
    code: str = "P",
    category: str = "open_market_purchase",
    shares: float = 100.0,
    price: float | None = 50.0,
    ad: str = "A",
    planned_10b5: bool = False,
    is_officer: bool = False,
    is_director: bool = False,
    period: str | None = None,
) -> None:
    """Inserta una transacción completa (con sus dependencias) en una sola llamada.

    Crea issuer/insider/filing si no existían (idempotente). La transacción
    en sí asume tx_idx único dentro de (accession, insider).
    """
    _ensure_issuer(conn, issuer_cik, ticker)
    _ensure_insider(conn, insider_cik, insider_name)
    _ensure_filing(conn, accession, issuer_cik, planned_10b5=planned_10b5, period=period or date)
    conn.execute(
        """INSERT INTO insider_transactions
           (accession_number, insider_cik, tx_index_in_filing,
            is_director, is_officer, is_ten_percent_owner, is_other, officer_title,
            security_title, transaction_date, transaction_code, transaction_category,
            is_derivative, acquired_or_disposed, shares, price_per_share,
            ownership_nature)
           VALUES (?, ?, ?, ?, ?, 0, 0, NULL, 'Common Stock', ?, ?, ?, 0, ?, ?, ?, 'D')""",
        (accession, insider_cik, tx_idx, int(is_director), int(is_officer),
         date, code, category, ad, shares, price),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Bloque A: metrics
# ---------------------------------------------------------------------------


def test_code_composition_percentages_sum_to_one(conn):
    # 3 P + 1 S = 4 transactions; pct debe sumar 1
    for i in range(3):
        add_tx(conn, accession=f"A{i}", issuer_cik="C1", ticker="ACME",
               insider_cik=f"I{i}", insider_name=f"Person {i}", code="P")
    add_tx(conn, accession="A4", issuer_cik="C1", ticker="ACME",
           insider_cik="I9", insider_name="Person 9", code="S", category="open_market_sale", ad="D")

    tx = load_transactions(conn)
    comp = code_composition(tx)
    assert pytest.approx(comp["pct"].sum(), abs=1e-9) == 1.0
    p_row = comp[comp["transaction_code"] == "P"].iloc[0]
    assert p_row["count"] == 3
    assert pytest.approx(p_row["pct"]) == 0.75


def test_signal_ratio_with_known_data(conn):
    # 10 P + 3 S, de las cuales 2 bajo 10b5-1
    for i in range(10):
        add_tx(conn, accession=f"P{i}", issuer_cik="C1", ticker="ACME",
               insider_cik=f"Ip{i}", insider_name=f"Buyer {i}", code="P")
    # 1 S normal
    add_tx(conn, accession="SN1", issuer_cik="C1", ticker="ACME",
           insider_cik="Is1", insider_name="Seller 1",
           code="S", category="open_market_sale", ad="D", planned_10b5=False)
    # 2 S bajo plan 10b5-1 (en filings distintos para que tengan flag distinto)
    add_tx(conn, accession="SP1", issuer_cik="C1", ticker="ACME",
           insider_cik="Is2", insider_name="Seller 2",
           code="S", category="open_market_sale", ad="D", planned_10b5=True)
    add_tx(conn, accession="SP2", issuer_cik="C1", ticker="ACME",
           insider_cik="Is3", insider_name="Seller 3",
           code="S", category="open_market_sale", ad="D", planned_10b5=True)

    tx = load_transactions(conn, ticker="ACME")
    sig = signal_ratio(tx)
    assert len(sig) == 1
    row = sig.iloc[0]
    assert row["n_total"] == 13
    assert row["n_p"] == 10
    assert pytest.approx(row["p_share"]) == 10 / 13
    assert row["n_s_total"] == 3
    assert row["n_s_planned"] == 2
    assert pytest.approx(row["planned_s_share"]) == 2 / 3


def test_top_insiders_orders_by_count_then_notional(conn):
    # Insider A: 2 P x 100 shares x $10 = $2000 notional
    # Insider B: 2 P x 100 shares x $20 = $4000 notional
    # Insider C: 1 P (no entra entre top por count)
    add_tx(conn, accession="X1", issuer_cik="C1", ticker="ACME",
           insider_cik="A", insider_name="Alice", tx_idx=0, code="P", shares=100, price=10)
    add_tx(conn, accession="X2", issuer_cik="C1", ticker="ACME",
           insider_cik="A", insider_name="Alice", tx_idx=0, code="P", shares=100, price=10)
    add_tx(conn, accession="Y1", issuer_cik="C1", ticker="ACME",
           insider_cik="B", insider_name="Bob", tx_idx=0, code="P", shares=100, price=20)
    add_tx(conn, accession="Y2", issuer_cik="C1", ticker="ACME",
           insider_cik="B", insider_name="Bob", tx_idx=0, code="P", shares=100, price=20)
    add_tx(conn, accession="Z1", issuer_cik="C1", ticker="ACME",
           insider_cik="C", insider_name="Carol", tx_idx=0, code="P", shares=100, price=5)

    tx = load_transactions(conn)
    top = top_insiders_by_p(tx, top_n=10)
    # Empatados en count: Bob (n=2, notional=4000) > Alice (n=2, notional=2000) > Carol (n=1)
    assert list(top["insider_name"]) == ["Bob", "Alice", "Carol"]


def test_monthly_activity_groups_by_yyyymm(conn):
    add_tx(conn, accession="M1", issuer_cik="C1", ticker="ACME",
           insider_cik="I1", insider_name="X", date="2026-03-01", code="P")
    add_tx(conn, accession="M2", issuer_cik="C1", ticker="ACME",
           insider_cik="I2", insider_name="Y", date="2026-03-28", code="P")
    add_tx(conn, accession="M3", issuer_cik="C1", ticker="ACME",
           insider_cik="I3", insider_name="Z", date="2026-04-05", code="S",
           category="open_market_sale", ad="D")

    tx = load_transactions(conn)
    monthly = monthly_activity(tx)
    march_p = monthly[(monthly["year_month"] == "2026-03") & (monthly["transaction_code"] == "P")]
    assert march_p.iloc[0]["count"] == 2


def test_clustering_returns_only_days_above_threshold(conn):
    # Día A: 1 insider (no debe aparecer)
    add_tx(conn, accession="D1", issuer_cik="C1", ticker="ACME",
           insider_cik="I1", insider_name="One", date="2026-02-10", code="P")
    # Día B: 3 insiders distintos (debe aparecer)
    add_tx(conn, accession="D2a", issuer_cik="C1", ticker="ACME",
           insider_cik="I2", insider_name="Two", date="2026-02-15", code="P")
    add_tx(conn, accession="D2b", issuer_cik="C1", ticker="ACME",
           insider_cik="I3", insider_name="Three", date="2026-02-15", code="P")
    add_tx(conn, accession="D2c", issuer_cik="C1", ticker="ACME",
           insider_cik="I4", insider_name="Four", date="2026-02-15", code="P")

    tx = load_transactions(conn)
    clust = clustering_days(tx, min_distinct_insiders=2)
    assert len(clust) == 1
    row = clust.iloc[0]
    assert row["n_distinct_insiders"] == 3
    assert set(row["insiders"].split(", ")) == {"Two", "Three", "Four"}


def test_net_flow_signs(conn):
    # P adquiere (A); S y F disponen (D)
    add_tx(conn, accession="NF1", issuer_cik="C1", ticker="ACME",
           insider_cik="I1", insider_name="X", code="P", shares=1000, price=10, ad="A")
    add_tx(conn, accession="NF2", issuer_cik="C1", ticker="ACME",
           insider_cik="I2", insider_name="Y",
           code="S", category="open_market_sale", shares=400, price=10, ad="D")
    add_tx(conn, accession="NF3", issuer_cik="C1", ticker="ACME",
           insider_cik="I3", insider_name="Z",
           code="F", category="tax_withholding", shares=100, price=10, ad="D")

    tx = load_transactions(conn)
    nf = net_flow_by_category(tx)
    p_row = nf[nf["transaction_category"] == "open_market_purchase"].iloc[0]
    s_row = nf[nf["transaction_category"] == "open_market_sale"].iloc[0]
    f_row = nf[nf["transaction_category"] == "tax_withholding"].iloc[0]
    assert p_row["shares_net"] == 1000
    assert s_row["shares_net"] == -400  # acquired=0 - disposed=400
    assert f_row["shares_net"] == -100


def test_load_transactions_filters_by_ticker(conn):
    add_tx(conn, accession="A1", issuer_cik="C1", ticker="ACME",
           insider_cik="I1", insider_name="X", code="P")
    add_tx(conn, accession="B1", issuer_cik="C2", ticker="XYZZ",
           insider_cik="I2", insider_name="Y", code="P")

    only_acme = load_transactions(conn, ticker="ACME")
    assert set(only_acme["ticker"]) == {"ACME"}
    both = load_transactions(conn)
    assert set(both["ticker"]) == {"ACME", "XYZZ"}


def test_list_tickers(conn):
    add_tx(conn, accession="A1", issuer_cik="C1", ticker="AAA",
           insider_cik="I1", insider_name="X", code="P")
    add_tx(conn, accession="B1", issuer_cik="C2", ticker="BBB",
           insider_cik="I2", insider_name="Y", code="P")
    assert list_tickers(conn) == ["AAA", "BBB"]


# ---------------------------------------------------------------------------
# Bloque B: price_impact (con precios sintéticos en BBDD, sin yfinance)
# ---------------------------------------------------------------------------


def _insert_synthetic_prices(conn, ticker: str, start: str, days: int, daily_return: float = 0.001):
    """Inserta `days` precios diarios consecutivos partiendo de adj_close=100,
    creciendo daily_return cada día (default +0.1% diario)."""
    base_date = pd.Timestamp(start)
    price = 100.0
    rows = []
    for i in range(days):
        d = base_date + pd.Timedelta(days=i)
        rows.append((ticker, d.strftime("%Y-%m-%d"), price, price, price, price, price, 1000))
        price *= 1 + daily_return
    conn.executemany(
        """INSERT OR REPLACE INTO prices
           (ticker, date, open, high, low, close, adj_close, volume)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()


def test_post_p_returns_with_synthetic_prices(conn):
    # 200 días de precios subiendo 0.1% diario → return de 5 días ≈ 0.005
    _insert_synthetic_prices(conn, "ACME", start="2026-01-01", days=200)

    # 3 P-transactions en distintos días
    for i, day in enumerate(["2026-02-01", "2026-02-15", "2026-03-01"]):
        add_tx(conn, accession=f"PR{i}", issuer_cik="C1", ticker="ACME",
               insider_cik=f"I{i}", insider_name=f"Buyer {i}",
               date=day, code="P", shares=100, price=50)

    out = post_p_returns(conn, "ACME", windows=(5,))
    assert len(out) == 1
    row = out.iloc[0]
    assert row["n"] == 3
    # Con daily_return=0.001 sostenido, return de 5 días ≈ (1.001)^5 - 1 ≈ 0.005
    assert row["mean_return_after_p"] == pytest.approx(0.005, abs=1e-3)
    # Baseline en serie totalmente uniforme también ≈ 0.005
    assert row["mean_return_baseline"] == pytest.approx(0.005, abs=1e-3)
    # diff casi cero (esperado, porque el patrón es uniforme y los P están "aleatorios")
    assert abs(row["diff_mean"]) < 1e-3
    # n<30 → warning obligatorio
    assert row["warning"] is not None
    assert "n=3" in row["warning"]


def test_post_p_returns_handles_zero_p(conn):
    _insert_synthetic_prices(conn, "ACME", start="2026-01-01", days=100)
    # Insertar SOLO una transacción S (ningún P)
    add_tx(conn, accession="S1", issuer_cik="C1", ticker="ACME",
           insider_cik="I1", insider_name="X",
           code="S", category="open_market_sale", ad="D")

    out = post_p_returns(conn, "ACME", windows=(5, 30))
    # Devuelve 2 filas (una por window), con n=0
    assert list(out["n"]) == [0, 0]
    assert out["mean_return_after_p"].isna().all()
    # Baseline sí existe (los precios sí están), pero diff_mean=NaN porque post=NaN
    assert out["mean_return_baseline"].notna().all()


def test_post_p_returns_returns_empty_when_no_prices(conn):
    # P pero sin precios cargados → devuelve DataFrame vacío
    add_tx(conn, accession="P1", issuer_cik="C1", ticker="ACME",
           insider_cik="I1", insider_name="X", code="P")
    out = post_p_returns(conn, "ACME", windows=(5, 10))
    assert out.empty
