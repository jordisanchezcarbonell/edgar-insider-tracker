"""Carga todos los Forms 4 descargados a SQLite.

Idempotente: re-ejecutarlo no duplica datos ni rompe (gracias a INSERT OR
IGNORE sobre claves UNIQUE). Imprime un resumen al final con conteos por
tabla para que puedas validar a ojo.

Uso:
    python scripts/load_all.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from edgar_insider.config import DB_PATH, RAW_DATA_DIR  # noqa: E402
from edgar_insider.parse.form4 import parse_form4_file  # noqa: E402
from edgar_insider.parse.models import Form4ParseError  # noqa: E402
from edgar_insider.storage.repository import load_parsed_filing  # noqa: E402
from edgar_insider.storage.schema import connect, create_tables  # noqa: E402


def iter_filing_dirs(root: Path):
    for cik_dir in sorted(root.iterdir()):
        if not cik_dir.is_dir():
            continue
        for accession_dir in sorted(cik_dir.iterdir()):
            if accession_dir.is_dir():
                yield accession_dir


def main() -> int:
    conn = connect(DB_PATH)
    create_tables(conn)

    if not RAW_DATA_DIR.exists():
        print(f"No existe {RAW_DATA_DIR}. Ejecuta scripts/download_initial_batch.py primero.")
        return 1

    new_filings = 0
    skipped_filings = 0
    new_transactions = 0
    failed: list[tuple[str, str]] = []

    for filing_dir in iter_filing_dirs(RAW_DATA_DIR):
        accession = filing_dir.name
        meta_path = filing_dir / "submission_meta.json"
        if not meta_path.exists():
            failed.append((accession, "submission_meta.json ausente"))
            continue

        meta = json.loads(meta_path.read_text())
        xml_path = filing_dir / meta["primary_document"]
        if not xml_path.exists():
            failed.append((accession, f"XML ausente: {meta['primary_document']}"))
            continue

        try:
            filing = parse_form4_file(xml_path, accession=accession)
            result = load_parsed_filing(
                conn,
                accession=accession,
                filing=filing,
                filing_date=meta.get("filing_date"),
                source_url=meta.get("source_url"),
            )
        except Form4ParseError as exc:
            failed.append((accession, f"parse: {exc}"))
            continue
        except Exception as exc:
            failed.append((accession, f"db: {exc}"))
            continue

        if result["filing_inserted"]:
            new_filings += 1
        else:
            skipped_filings += 1
        new_transactions += result["transactions_inserted"]

    # Totales en la BBDD tras la carga
    counts = {
        "issuers": conn.execute("SELECT COUNT(*) FROM issuers").fetchone()[0],
        "insiders": conn.execute("SELECT COUNT(*) FROM insiders").fetchone()[0],
        "filings": conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0],
        "insider_transactions": conn.execute("SELECT COUNT(*) FROM insider_transactions").fetchone()[0],
    }

    print(f"\n=== Carga ===")
    print(f"  Filings nuevos:           {new_filings}")
    print(f"  Filings ya existentes:    {skipped_filings}")
    print(f"  Transacciones nuevas:     {new_transactions}")
    print(f"  Filings fallidos:         {len(failed)}")

    print(f"\n=== Totales en {DB_PATH.relative_to(REPO_ROOT)} ===")
    for table, n in counts.items():
        print(f"  {table:22s} {n}")

    if failed:
        print(f"\n=== Filings fallidos ({len(failed)}) ===")
        for acc, reason in failed:
            print(f"  {acc}: {reason}")

    conn.close()
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
