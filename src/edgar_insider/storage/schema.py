"""Esquema SQLite y gestión de conexión.

Mantengo el DDL como constantes en este módulo (en vez de un .sql externo)
porque viven al lado del código que las usa. Cuando el esquema crezca y
necesitemos migrations versionadas, esto se moverá a una carpeta `migrations/`
con herramienta dedicada — pero hoy es complejidad injustificada.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# DDL — ver doc del plan para razonamiento de cada decisión
# ---------------------------------------------------------------------------

# Empresas. CIK padded a 10 dígitos es la PK natural (la asigna la SEC).
CREATE_ISSUERS = """
CREATE TABLE IF NOT EXISTS issuers (
    cik    TEXT PRIMARY KEY,
    name   TEXT NOT NULL,
    ticker TEXT NOT NULL
)
"""

# Insiders (personas físicas que reportan). CIK propio del insider.
# El rol (officer/director) NO va aquí — es point-in-time del filing.
CREATE_INSIDERS = """
CREATE TABLE IF NOT EXISTS insiders (
    cik  TEXT PRIMARY KEY,
    name TEXT NOT NULL
)
"""

# Filings. accession_number es PK natural y única globalmente en SEC EDGAR.
CREATE_FILINGS = """
CREATE TABLE IF NOT EXISTS filings (
    accession_number          TEXT PRIMARY KEY,
    issuer_cik                TEXT NOT NULL REFERENCES issuers(cik),
    schema_version            TEXT NOT NULL,
    document_type             TEXT NOT NULL,
    is_amendment              INTEGER NOT NULL DEFAULT 0,
    not_subject_to_section_16 INTEGER NOT NULL DEFAULT 0,
    under_10b5_1_plan         INTEGER NOT NULL DEFAULT 0,
    period_of_report          TEXT NOT NULL,
    filing_date               TEXT,
    source_url                TEXT,
    inserted_at               TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

# Transacciones individuales. id sintético + UNIQUE compuesto.
# tx_index_in_filing desambigua transacciones repetidas por la misma persona
# en el mismo día (común en ventas por tramos a precios distintos).
CREATE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS insider_transactions (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    accession_number            TEXT NOT NULL REFERENCES filings(accession_number),
    insider_cik                 TEXT NOT NULL REFERENCES insiders(cik),
    tx_index_in_filing          INTEGER NOT NULL,

    is_director                 INTEGER NOT NULL DEFAULT 0,
    is_officer                  INTEGER NOT NULL DEFAULT 0,
    is_ten_percent_owner        INTEGER NOT NULL DEFAULT 0,
    is_other                    INTEGER NOT NULL DEFAULT 0,
    officer_title               TEXT,

    security_title              TEXT NOT NULL,
    transaction_date            TEXT NOT NULL,
    transaction_code            TEXT NOT NULL,
    transaction_category        TEXT NOT NULL,
    is_derivative               INTEGER NOT NULL,
    acquired_or_disposed        TEXT NOT NULL,
    shares                      REAL NOT NULL,
    price_per_share             REAL,
    shares_owned_following      REAL,
    ownership_nature            TEXT NOT NULL,
    indirect_owner_explanation  TEXT,
    footnotes_text              TEXT,

    UNIQUE (accession_number, insider_cik, tx_index_in_filing)
)
"""

# Precios diarios ajustados, cacheados desde yfinance (Fase 4).
# A diferencia de filings/transactions, aquí usamos INSERT OR REPLACE en el
# loader porque ajustes por split/dividendo modifican retroactivamente el
# histórico — un re-fetch debe actualizar todo, no preservar valores viejos.
CREATE_PRICES = """
CREATE TABLE IF NOT EXISTS prices (
    ticker     TEXT NOT NULL,
    date       TEXT NOT NULL,
    open       REAL NOT NULL,
    high       REAL NOT NULL,
    low        REAL NOT NULL,
    close      REAL NOT NULL,
    adj_close  REAL NOT NULL,
    volume     INTEGER NOT NULL,
    PRIMARY KEY (ticker, date)
)
"""

# Índices para los filtros típicos de Fase 4. La UNIQUE de transactions
# ya da índice sobre (accession_number, insider_cik, tx_index_in_filing).
CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_tx_insider     ON insider_transactions(insider_cik)",
    "CREATE INDEX IF NOT EXISTS idx_tx_date        ON insider_transactions(transaction_date)",
    "CREATE INDEX IF NOT EXISTS idx_tx_code        ON insider_transactions(transaction_code)",
    "CREATE INDEX IF NOT EXISTS idx_filings_issuer ON filings(issuer_cik)",
    "CREATE INDEX IF NOT EXISTS idx_filings_date   ON filings(filing_date)",
    "CREATE INDEX IF NOT EXISTS idx_prices_ticker  ON prices(ticker, date)",
]


# ---------------------------------------------------------------------------
# Conexión y creación del esquema
# ---------------------------------------------------------------------------


def connect(db_path: Path) -> sqlite3.Connection:
    """Abre una conexión y activa FK + row_factory.

    Dos cosas no obvias:
    1. `PRAGMA foreign_keys = ON` debe ejecutarse en cada conexión (SQLite las
       tiene OFF por defecto). Sin esto, las cláusulas REFERENCES son
       decorativas y los INSERTs inválidos pasan silenciosamente.
    2. `row_factory = sqlite3.Row` permite acceso por nombre de columna
       (`row['cik']`) además del posicional. Más legible al leer resultados.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    """Crea esquema completo. Idempotente: todos los CREATE usan IF NOT EXISTS."""
    conn.execute(CREATE_ISSUERS)
    conn.execute(CREATE_INSIDERS)
    conn.execute(CREATE_FILINGS)
    conn.execute(CREATE_TRANSACTIONS)
    conn.execute(CREATE_PRICES)
    for stmt in CREATE_INDEXES:
        conn.execute(stmt)
    conn.commit()
