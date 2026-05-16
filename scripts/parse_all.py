"""Validación end-to-end de Fase 2.

Itera todos los Forms 4 descargados en data/raw/form4/, los parsea, y muestra
estadísticas agregadas para que puedas comprobar a ojo que el parser entendió
los XMLs como esperábamos. No persiste nada — eso es Fase 3.

Uso:
    python scripts/parse_all.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from edgar_insider.config import RAW_DATA_DIR  # noqa: E402
from edgar_insider.parse.form4 import parse_form4_file, to_transaction_rows  # noqa: E402
from edgar_insider.parse.models import Form4ParseError  # noqa: E402


def iter_filing_dirs(root: Path):
    """Yields (cik_dir, accession_dir) para cada filing descargado."""
    for cik_dir in sorted(root.iterdir()):
        if not cik_dir.is_dir():
            continue
        for accession_dir in sorted(cik_dir.iterdir()):
            if accession_dir.is_dir():
                yield cik_dir, accession_dir


def locate_xml(filing_dir: Path) -> Path | None:
    """Encuentra el XML del filing leyendo el meta.json (filename varía por filer).

    Por qué no `next(filing_dir.glob("*.xml"))`: ser explícitos y poder fallar
    con un mensaje claro si el meta no existe (caso roto), en vez de coger
    silenciosamente cualquier XML.
    """
    meta_path = filing_dir / "submission_meta.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    return filing_dir / meta["primary_document"]


def main() -> int:
    if not RAW_DATA_DIR.exists():
        print(f"No existe {RAW_DATA_DIR}. Ejecuta scripts/download_initial_batch.py primero.")
        return 1

    parsed_count = 0
    failed: list[tuple[str, str]] = []   # (accession, reason)
    total_transactions = 0
    total_rows = 0
    skipped_holdings_total = 0
    code_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    insider_counts: Counter[str] = Counter()
    ticker_counts: Counter[str] = Counter()
    derivatives_count = 0

    for _, filing_dir in iter_filing_dirs(RAW_DATA_DIR):
        accession = filing_dir.name
        xml_path = locate_xml(filing_dir)
        if xml_path is None or not xml_path.exists():
            failed.append((accession, "XML no encontrado"))
            continue
        try:
            filing = parse_form4_file(xml_path, accession=accession)
        except Form4ParseError as exc:
            failed.append((accession, str(exc)))
            continue

        parsed_count += 1
        total_transactions += len(filing.transactions)
        skipped_holdings_total += filing.skipped_holdings_count
        ticker_counts[filing.issuer.ticker] += 1

        for tx in filing.transactions:
            code_counts[tx.transaction_code] += 1
            category_counts[tx.transaction_category] += 1
            if tx.is_derivative:
                derivatives_count += 1

        for owner in filing.reporting_owners:
            insider_counts[f"{owner.name} ({filing.issuer.ticker})"] += len(filing.transactions)

        total_rows += len(to_transaction_rows(filing, accession=accession))

    print(f"\n=== Resumen ===")
    print(f"  Filings parseados:        {parsed_count}")
    print(f"  Filings fallidos:         {len(failed)}")
    print(f"  Transacciones totales:    {total_transactions}")
    print(f"    de las cuales derivadas: {derivatives_count}")
    print(f"  Filas tras flatten:       {total_rows}")
    print(f"  Holdings saltadas:        {skipped_holdings_total}")

    print(f"\n=== Por empresa ===")
    for ticker, n in ticker_counts.most_common():
        print(f"  {ticker:6s}  {n} filings")

    print(f"\n=== Distribución por código de transacción ===")
    for code, n in code_counts.most_common():
        print(f"  {code}  {n:4d}")

    print(f"\n=== Distribución por categoría analítica ===")
    for cat, n in category_counts.most_common():
        print(f"  {cat:25s} {n:4d}")

    print(f"\n=== Top 10 insiders por nº de transacciones reportadas ===")
    for insider, n in insider_counts.most_common(10):
        print(f"  {n:3d}  {insider}")

    if failed:
        print(f"\n=== Filings fallidos ({len(failed)}) ===")
        for acc, reason in failed:
            print(f"  {acc}: {reason}")

    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
