"""Capa de repositorio: traduce dataclasses parseados en filas SQLite.

La función pública estrella es `load_parsed_filing`, que ejecuta todo el
upsert+insert dentro de una transacción SQL atómica: si algo falla a mitad,
no quedan datos parciales en disco.

Idempotencia: las 4 funciones de inserción usan `INSERT OR IGNORE`. La BBDD
es la única autoridad sobre unicidad; no comprobamos con SELECT antes (eso
sería race-condition-prone y más lento).
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from edgar_insider.parse.models import Insider, Issuer, ParsedFiling


def upsert_issuer(conn: sqlite3.Connection, issuer: Issuer) -> None:
    """`INSERT OR IGNORE` — si ya existe la empresa (por CIK), no toca el row."""
    conn.execute(
        "INSERT OR IGNORE INTO issuers (cik, name, ticker) VALUES (?, ?, ?)",
        (issuer.cik, issuer.name, issuer.ticker),
    )


def upsert_insider(conn: sqlite3.Connection, insider: Insider) -> None:
    """Igual: si ya existe la persona (por CIK), conservamos el nombre original.

    Decisión documentada: no actualizamos el nombre aunque cambie entre
    filings. Para Fase 3 es ruido; si en Fase 4 vemos que importa, añadimos
    lógica de "última versión vista".
    """
    conn.execute(
        "INSERT OR IGNORE INTO insiders (cik, name) VALUES (?, ?)",
        (insider.cik, insider.name),
    )


def insert_filing(
    conn: sqlite3.Connection,
    *,
    accession: str,
    filing: ParsedFiling,
    filing_date: str | None,
    source_url: str | None,
) -> bool:
    """Devuelve True si se insertó, False si ya existía (accession choca con PK)."""
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO filings (
            accession_number, issuer_cik, schema_version, document_type,
            is_amendment, not_subject_to_section_16, under_10b5_1_plan,
            period_of_report, filing_date, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            accession,
            filing.issuer.cik,
            filing.schema_version,
            filing.document_type,
            int(filing.is_amendment),
            int(filing.not_subject_to_section_16),
            int(filing.under_10b5_1_plan),
            filing.period_of_report.isoformat(),
            filing_date,
            source_url,
        ),
    )
    # rowcount == 1 si se insertó, 0 si la PK ya existía y se ignoró.
    return cursor.rowcount == 1


def _decimal_to_float(value: Decimal | None) -> float | None:
    """Decimal → REAL para SQLite. None se preserva."""
    return float(value) if value is not None else None


def insert_transactions(
    conn: sqlite3.Connection,
    *,
    accession: str,
    filing: ParsedFiling,
) -> int:
    """Inserta todas las transacciones del filing × cada reporting owner.

    Devuelve cuántas filas se insertaron realmente (puede ser menor que
    len(transactions) × len(owners) si algunas ya existían — gracias a
    INSERT OR IGNORE sobre la UNIQUE compuesta).
    """
    inserted_total = 0
    for owner in filing.reporting_owners:
        for idx, tx in enumerate(filing.transactions):
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO insider_transactions (
                    accession_number, insider_cik, tx_index_in_filing,
                    is_director, is_officer, is_ten_percent_owner, is_other, officer_title,
                    security_title, transaction_date, transaction_code, transaction_category,
                    is_derivative, acquired_or_disposed, shares, price_per_share,
                    shares_owned_following, ownership_nature, indirect_owner_explanation,
                    footnotes_text
                ) VALUES (?, ?, ?,  ?, ?, ?, ?, ?,  ?, ?, ?, ?,  ?, ?, ?, ?,  ?, ?, ?,  ?)
                """,
                (
                    accession,
                    owner.cik,
                    idx,
                    int(owner.is_director),
                    int(owner.is_officer),
                    int(owner.is_ten_percent_owner),
                    int(owner.is_other),
                    owner.officer_title,
                    tx.security_title,
                    tx.transaction_date.isoformat(),
                    tx.transaction_code,
                    tx.transaction_category,
                    int(tx.is_derivative),
                    tx.acquired_or_disposed,
                    _decimal_to_float(tx.shares),
                    _decimal_to_float(tx.price_per_share),
                    _decimal_to_float(tx.shares_owned_following),
                    tx.ownership_nature,
                    tx.indirect_owner_explanation,
                    _footnotes_text(filing, tx.footnote_ids),
                ),
            )
            inserted_total += cursor.rowcount
    return inserted_total


def _footnotes_text(filing: ParsedFiling, footnote_ids: tuple[str, ...]) -> str | None:
    """Misma lógica que `parse.form4.to_transaction_rows` — concatena con ' | '."""
    text = " | ".join(
        filing.footnotes[fid] for fid in footnote_ids if fid in filing.footnotes
    )
    return text or None


def load_parsed_filing(
    conn: sqlite3.Connection,
    *,
    accession: str,
    filing: ParsedFiling,
    filing_date: str | None = None,
    source_url: str | None = None,
) -> dict:
    """Carga atómica de un filing completo.

    `BEGIN`/`COMMIT` envuelven todas las inserciones para que un fallo a
    mitad (ej. una transacción inválida) deje la BBDD como estaba antes,
    sin filings huérfanos.
    """
    try:
        conn.execute("BEGIN")
        upsert_issuer(conn, filing.issuer)
        for owner in filing.reporting_owners:
            upsert_insider(conn, owner)
        filing_inserted = insert_filing(
            conn,
            accession=accession,
            filing=filing,
            filing_date=filing_date,
            source_url=source_url,
        )
        transactions_inserted = insert_transactions(conn, accession=accession, filing=filing)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return {
        "accession": accession,
        "filing_inserted": filing_inserted,
        "transactions_inserted": transactions_inserted,
    }
