"""Tests de la capa de almacenamiento SQLite.

Cada test usa una BBDD en disco temporal (tmp_path). NO usamos SQLite
en-memoria (`:memory:`) porque queremos cubrir el comportamiento real con
ficheros — incluyendo cosas como `PRAGMA foreign_keys` en una conexión
nueva.
"""

from pathlib import Path

import pytest

from edgar_insider.parse.form4 import parse_form4, parse_form4_file
from edgar_insider.storage import repository
from edgar_insider.storage.repository import load_parsed_filing
from edgar_insider.storage.schema import connect, create_tables

FIXTURES = Path(__file__).parent / "fixtures"

APPLE_ACCESSION = "0001140361-26-020871"
TESLA_ACCESSION = "0001104659-26-062860"


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    c = connect(db_path)
    create_tables(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_create_tables_is_idempotent(tmp_path):
    db = tmp_path / "x.db"
    c = connect(db)
    create_tables(c)
    create_tables(c)  # segunda vez no rompe
    # Y las 4 tablas existen
    tables = {row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"issuers", "insiders", "filings", "insider_transactions"} <= tables
    c.close()


def test_foreign_keys_pragma_is_active(conn):
    # Si no estuviera activa, este INSERT pasaría silenciosamente.
    with pytest.raises(Exception) as exc:
        conn.execute(
            """INSERT INTO insider_transactions (
                accession_number, insider_cik, tx_index_in_filing,
                security_title, transaction_date, transaction_code, transaction_category,
                is_derivative, acquired_or_disposed, shares, ownership_nature
            ) VALUES ('NOPE', 'NOPE', 0, 'X', '2026-01-01', 'P', 'open_market_purchase',
                      0, 'A', 1, 'D')"""
        )
    assert "FOREIGN KEY" in str(exc.value).upper() or "constraint" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Carga end-to-end de fixtures reales
# ---------------------------------------------------------------------------


def test_load_apple_filing_round_trip(conn):
    filing = parse_form4_file(FIXTURES / "apple_simple_sale.xml")
    result = load_parsed_filing(
        conn,
        accession=APPLE_ACCESSION,
        filing=filing,
        filing_date="2026-05-12",
        source_url="https://example.com/apple",
    )
    assert result["filing_inserted"] is True
    assert result["transactions_inserted"] == 1

    # Issuer cargado
    issuer = conn.execute("SELECT * FROM issuers WHERE cik='0000320193'").fetchone()
    assert issuer["ticker"] == "AAPL"
    assert issuer["name"] == "Apple Inc."

    # Insider cargado
    insider = conn.execute("SELECT * FROM insiders").fetchone()
    assert insider["name"] == "Borders Ben"

    # Filing con sus flags
    f = conn.execute("SELECT * FROM filings WHERE accession_number=?", (APPLE_ACCESSION,)).fetchone()
    assert f["issuer_cik"] == "0000320193"
    assert f["schema_version"] == "X0609"
    assert f["filing_date"] == "2026-05-12"

    # Transacción con los campos esperados
    tx = conn.execute("SELECT * FROM insider_transactions").fetchone()
    assert tx["transaction_code"] == "S"
    assert tx["transaction_category"] == "open_market_sale"
    assert tx["shares"] == 1274.0
    assert tx["price_per_share"] == 290.0
    assert tx["officer_title"] == "Principal Accounting Officer"
    assert tx["is_officer"] == 1
    assert tx["ownership_nature"] == "D"
    assert "10b5-1" in (tx["footnotes_text"] or "")


def test_load_tesla_complex_loads_all_5_transactions(conn):
    filing = parse_form4_file(FIXTURES / "tesla_complex_mixed.xml")
    result = load_parsed_filing(conn, accession=TESLA_ACCESSION, filing=filing)

    assert result["transactions_inserted"] == 5
    count = conn.execute(
        "SELECT COUNT(*) FROM insider_transactions WHERE accession_number=?",
        (TESLA_ACCESSION,),
    ).fetchone()[0]
    assert count == 5

    # 3 non-deriv + 2 deriv
    counts_by_type = dict(
        conn.execute(
            "SELECT is_derivative, COUNT(*) FROM insider_transactions GROUP BY is_derivative"
        ).fetchall()
    )
    assert counts_by_type == {0: 3, 1: 2}


# ---------------------------------------------------------------------------
# Idempotencia
# ---------------------------------------------------------------------------


def test_reinsert_same_filing_does_not_duplicate(conn):
    filing = parse_form4_file(FIXTURES / "apple_simple_sale.xml")

    first = load_parsed_filing(conn, accession=APPLE_ACCESSION, filing=filing)
    assert first["filing_inserted"] is True
    assert first["transactions_inserted"] == 1

    second = load_parsed_filing(conn, accession=APPLE_ACCESSION, filing=filing)
    assert second["filing_inserted"] is False
    assert second["transactions_inserted"] == 0

    # Conteos totales no cambiaron
    assert conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM insider_transactions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM insiders").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM issuers").fetchone()[0] == 1


def test_distinct_filings_share_issuer(conn):
    # Dos filings de Apple → 1 issuer, 2 filings
    filing = parse_form4_file(FIXTURES / "apple_simple_sale.xml")
    load_parsed_filing(conn, accession="A1", filing=filing)
    load_parsed_filing(conn, accession="A2", filing=filing)

    assert conn.execute("SELECT COUNT(*) FROM issuers").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0] == 2
    # 2 filings × 1 transacción cada uno = 2 filas (claves UNIQUE distintas por accession)
    assert conn.execute("SELECT COUNT(*) FROM insider_transactions").fetchone()[0] == 2


# ---------------------------------------------------------------------------
# Atomicidad
# ---------------------------------------------------------------------------


def test_atomicity_rollbacks_partial_load(conn, monkeypatch):
    """Si insert_transactions falla, ni el filing ni el issuer deben quedarse."""
    filing = parse_form4_file(FIXTURES / "apple_simple_sale.xml")

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure mid-load")

    monkeypatch.setattr(repository, "insert_transactions", boom)

    with pytest.raises(RuntimeError, match="simulated failure"):
        load_parsed_filing(conn, accession=APPLE_ACCESSION, filing=filing)

    # Todo rolled back: ni issuer, ni insider, ni filing.
    assert conn.execute("SELECT COUNT(*) FROM issuers").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM insiders").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM insider_transactions").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Multi-owner (mismo XML sintético que en test_form4_parser)
# ---------------------------------------------------------------------------


MULTI_OWNER_XML = b"""<?xml version="1.0"?>
<ownershipDocument>
    <schemaVersion>X0609</schemaVersion>
    <documentType>4</documentType>
    <periodOfReport>2026-01-15</periodOfReport>
    <issuer>
        <issuerCik>0000000001</issuerCik>
        <issuerName>Test Corp</issuerName>
        <issuerTradingSymbol>TEST</issuerTradingSymbol>
    </issuer>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0000000010</rptOwnerCik>
            <rptOwnerName>Owner One</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
            <isDirector>0</isDirector><isOfficer>0</isOfficer>
            <isTenPercentOwner>1</isTenPercentOwner><isOther>0</isOther>
        </reportingOwnerRelationship>
    </reportingOwner>
    <reportingOwner>
        <reportingOwnerId>
            <rptOwnerCik>0000000011</rptOwnerCik>
            <rptOwnerName>Owner Two</rptOwnerName>
        </reportingOwnerId>
        <reportingOwnerRelationship>
            <isDirector>0</isDirector><isOfficer>0</isOfficer>
            <isTenPercentOwner>1</isTenPercentOwner><isOther>0</isOther>
        </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>2026-01-15</value></transactionDate>
            <transactionCoding>
                <transactionFormType>4</transactionFormType>
                <transactionCode>P</transactionCode>
                <equitySwapInvolved>0</equitySwapInvolved>
            </transactionCoding>
            <transactionAmounts>
                <transactionShares><value>1000</value></transactionShares>
                <transactionPricePerShare><value>50</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
            <ownershipNature>
                <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
            </ownershipNature>
        </nonDerivativeTransaction>
    </nonDerivativeTable>
</ownershipDocument>
"""


def test_multi_owner_filing_produces_n_rows_per_transaction(conn):
    filing = parse_form4(MULTI_OWNER_XML)
    result = load_parsed_filing(conn, accession="MULTI-1", filing=filing)
    # 2 owners × 1 transacción = 2 filas
    assert result["transactions_inserted"] == 2
    assert conn.execute("SELECT COUNT(*) FROM insiders").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM insider_transactions").fetchone()[0] == 2
