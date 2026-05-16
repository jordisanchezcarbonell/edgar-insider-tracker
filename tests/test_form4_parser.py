"""Tests del parser de Form 4.

Fixtures = XMLs reales copiados desde data/raw/ (en `tests/fixtures/`). Es a
propósito: la documentación oficial de la SEC es ambigua en varios sitios;
los XMLs reales son la única verdad. Si la SEC cambia algo del formato,
queremos que el test se rompa al refrescar las fixtures, no que vivan
mockeadas para siempre con un schema irreal.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from edgar_insider.parse.form4 import (
    parse_form4,
    parse_form4_file,
    to_transaction_rows,
)
from edgar_insider.parse.models import Form4ParseError

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures reales
# ---------------------------------------------------------------------------


def test_apple_simple_sale_x0609():
    filing = parse_form4_file(FIXTURES / "apple_simple_sale.xml")

    assert filing.schema_version == "X0609"
    assert filing.document_type == "4"
    assert not filing.is_amendment
    assert filing.issuer.ticker == "AAPL"
    assert filing.issuer.name == "Apple Inc."
    assert filing.issuer.cik == "0000320193"

    assert len(filing.reporting_owners) == 1
    owner = filing.reporting_owners[0]
    assert owner.name == "Borders Ben"
    assert owner.is_officer is True
    assert owner.is_director is False
    assert owner.officer_title == "Principal Accounting Officer"

    assert len(filing.transactions) == 1
    tx = filing.transactions[0]
    assert tx.transaction_code == "S"
    assert tx.transaction_category == "open_market_sale"
    assert tx.is_derivative is False
    assert tx.shares == Decimal("1274")
    assert tx.price_per_share == Decimal("290")
    assert tx.acquired_or_disposed == "D"
    assert tx.ownership_nature == "D"
    assert tx.footnote_ids == ("F1",)

    assert "F1" in filing.footnotes
    assert "10b5-1" in filing.footnotes["F1"]


def test_tesla_complex_mixed_filing():
    filing = parse_form4_file(FIXTURES / "tesla_complex_mixed.xml")

    assert filing.issuer.ticker == "TSLA"
    assert filing.under_10b5_1_plan is False  # aff10b5One=0
    assert filing.reporting_owners[0].officer_title == "Chief Financial Officer"

    # 3 non-derivative transactions (2M + 1S) + 2 derivative M = 5 total
    assert len(filing.transactions) == 5

    non_deriv = [t for t in filing.transactions if not t.is_derivative]
    deriv = [t for t in filing.transactions if t.is_derivative]
    assert len(non_deriv) == 3
    assert len(deriv) == 2

    # 1 nonDerivativeHolding (GRATs) saltado
    assert filing.skipped_holdings_count == 1

    # 5 footnotes definidas
    assert len(filing.footnotes) == 5

    # La transacción S (la venta de 3000 shares) lleva 2 footnotes (F1 + F2)
    sale = next(t for t in non_deriv if t.transaction_code == "S")
    assert set(sale.footnote_ids) == {"F1", "F2"}

    # Las derivativas tienen los campos extra rellenos
    for d in deriv:
        assert d.conversion_or_exercise_price is not None
        assert d.expiration_date is not None
        assert d.underlying_security_title == "Common Stock"
        assert d.underlying_shares is not None


def test_meta_indirect_ownership():
    filing = parse_form4_file(FIXTURES / "meta_indirect_ownership.xml")

    assert filing.issuer.ticker == "META"
    assert filing.under_10b5_1_plan is True
    assert len(filing.transactions) == 5

    indirect = [t for t in filing.transactions if t.ownership_nature == "I"]
    direct = [t for t in filing.transactions if t.ownership_nature == "D"]
    assert len(indirect) == 4
    assert len(direct) == 1

    # Cada indirecta tiene su explicación distinta del vehículo
    explanations = {t.indirect_owner_explanation for t in indirect}
    assert explanations == {
        "By Olivan D LLC",
        "By Olivan Reinhold D LLC",
        "By Reinhold D LLC",
        "By Olivan Reinhold Family Revocable Trust u/a/d 10/16/12",
    }


def test_nvda_jensen_award_x0508():
    filing = parse_form4_file(FIXTURES / "nvda_jensen_award.xml")

    # Schema viejo (X0508) parsea sin problema
    assert filing.schema_version == "X0508"
    assert filing.issuer.ticker == "NVDA"

    owner = filing.reporting_owners[0]
    # Jensen es Director Y Officer (raro pero ocurre con founders/CEOs)
    assert owner.is_director is True
    assert owner.is_officer is True
    assert owner.officer_title == "President and CEO"

    # Todas las transacciones son grants (A)
    assert {t.transaction_code for t in filing.transactions} == {"A"}
    for t in filing.transactions:
        assert t.transaction_category == "award_grant"


# ---------------------------------------------------------------------------
# to_transaction_rows
# ---------------------------------------------------------------------------


def test_to_transaction_rows_flattens_filing():
    filing = parse_form4_file(FIXTURES / "apple_simple_sale.xml")
    rows = to_transaction_rows(filing, accession="0001140361-26-020871")

    assert len(rows) == 1
    row = rows[0]
    assert row["accession"] == "0001140361-26-020871"
    assert row["ticker"] == "AAPL"
    assert row["insider_name"] == "Borders Ben"
    assert row["transaction_code"] == "S"
    assert row["transaction_category"] == "open_market_sale"
    assert row["shares"] == "1274"
    assert row["price_per_share"] == "290"
    assert "10b5-1" in (row["footnotes_text"] or "")


def test_to_transaction_rows_handles_indirect_explanation():
    filing = parse_form4_file(FIXTURES / "meta_indirect_ownership.xml")
    rows = to_transaction_rows(filing)
    # 1 reporting owner × 5 transacciones = 5 filas
    assert len(rows) == 5
    indirect_rows = [r for r in rows if r["ownership_nature"] == "I"]
    assert all(r["indirect_owner_explanation"] for r in indirect_rows)


# ---------------------------------------------------------------------------
# Casos sintéticos: multi-owner y errores
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


def test_multi_owner_filing_produces_n_times_m_rows():
    filing = parse_form4(MULTI_OWNER_XML)
    assert len(filing.reporting_owners) == 2
    assert len(filing.transactions) == 1

    rows = to_transaction_rows(filing)
    # 2 owners × 1 transacción = 2 filas
    assert len(rows) == 2
    names = {r["insider_name"] for r in rows}
    assert names == {"Owner One", "Owner Two"}


def test_malformed_xml_raises_form4_parse_error():
    with pytest.raises(Form4ParseError, match="malformed"):
        parse_form4(b"<ownershipDocument><unclosed>", accession="X")


def test_wrong_root_element_raises():
    with pytest.raises(Form4ParseError, match="root inesperado"):
        parse_form4(b"<somethingElse/>", accession="X")


def test_wrong_document_type_raises():
    bad = b"""<?xml version="1.0"?>
<ownershipDocument>
    <documentType>10-K</documentType>
</ownershipDocument>"""
    with pytest.raises(Form4ParseError, match="documentType"):
        parse_form4(bad, accession="X")


def test_accession_attached_to_error():
    # El bulk-parse necesita poder identificar qué filing falló.
    with pytest.raises(Form4ParseError) as excinfo:
        parse_form4(b"<wrong/>", accession="0001234-56-789012")
    assert excinfo.value.accession == "0001234-56-789012"
