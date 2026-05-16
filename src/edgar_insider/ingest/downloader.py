"""Lógica de descarga de Forms 4 desde SEC EDGAR.

Lo escribo como funciones puras (en vez de una clase con estado) porque cada
paso del pipeline es una transformación clara con entrada/salida explícita.
Es más fácil de leer, de testear en el futuro, y refleja mejor cómo pienso
el flujo de datos.

Flujo end-to-end por empresa:

    fetch_submissions(cik)            -> dict JSON crudo
    extract_recent_form4s(submissions, limit)
                                      -> [{accession, filing_date, primary_document, report_date}, ...]
    para cada filing:
        build_filing_url(...)         -> URL del XML
        client.get(url)               -> XML
        save_filing(...)              -> escribe a disco
"""

from __future__ import annotations

import json
from pathlib import Path

from edgar_insider.config import RAW_DATA_DIR
from edgar_insider.ingest.client import SecClient


def fetch_submissions(client: SecClient, cik_padded: str) -> dict:
    """Descarga el índice de filings recientes de una empresa.

    El endpoint /submissions/CIK{padded}.json devuelve metadatos de la empresa
    + un objeto `filings.recent` con los ~1000 filings más recientes en formato
    de "arrays paralelos" (no array de objetos).
    """
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    response = client.get(url)
    return response.json()


def extract_recent_form4s(submissions: dict, limit: int) -> list[dict]:
    """Filtra los Forms 4 más recientes del índice de submissions.

    La SEC devuelve `filings.recent` como arrays paralelos: cada índice i
    representa un filing, con sus campos repartidos en arrays distintos
    (`form[i]`, `accessionNumber[i]`, `filingDate[i]`, …). Hay que recomponer
    los registros uno a uno.

    Asumimos que `filings.recent` ya viene ordenado por fecha descendente
    (es lo que documenta la SEC y lo que devuelve en la práctica).

    Quirk del `primaryDocument`: para Form 4 a veces apunta a una vista
    XSL-transformada (`xslF345X06/form4.xml`) que es HTML estilizado, no XML
    parseable. El XML crudo está en la raíz del filing con el mismo basename.
    Normalizamos aquí para que el resto del pipeline trabaje siempre con la
    ruta al XML real.
    """
    recent = submissions["filings"]["recent"]
    forms = recent["form"]
    accessions = recent["accessionNumber"]
    filing_dates = recent["filingDate"]
    primary_docs = recent["primaryDocument"]
    report_dates = recent["reportDate"]

    form4s: list[dict] = []
    for i, form_type in enumerate(forms):
        if form_type != "4":
            continue
        # Si primaryDocument viene como "xslF345X06/form4.xml", nos quedamos
        # con "form4.xml" — el XML crudo vive en la raíz del filing.
        raw_xml_name = primary_docs[i].rsplit("/", 1)[-1]
        form4s.append(
            {
                "accession_number": accessions[i],
                "filing_date": filing_dates[i],
                "primary_document": raw_xml_name,
                "report_date": report_dates[i],
            }
        )
        if len(form4s) >= limit:
            break
    return form4s


def build_filing_url(cik_padded: str, accession_number: str, primary_document: str) -> str:
    """Construye la URL del documento XML de un filing.

    Dos detalles que confunden la primera vez:
    - En esta URL el CIK va SIN los ceros de padding (`320193`, no `0000320193`).
    - El accession number va SIN los guiones (`0001234567-89-012345` → `000123456789012345`).
    """
    cik_unpadded = str(int(cik_padded))
    accession_no_dashes = accession_number.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_unpadded}/{accession_no_dashes}/{primary_document}"
    )


def filing_dir(cik_padded: str, accession_number: str) -> Path:
    """Carpeta donde guardamos un filing concreto."""
    return RAW_DATA_DIR / cik_padded / accession_number


def already_downloaded(cik_padded: str, accession_number: str) -> bool:
    """Idempotencia: si ya existe el meta del filing, lo saltamos.

    Comprobamos `submission_meta.json` (en vez del XML) porque lo escribimos
    al final del proceso; si está, garantiza que la descarga del XML
    también terminó bien.
    """
    return (filing_dir(cik_padded, accession_number) / "submission_meta.json").exists()


def save_filing(
    cik_padded: str,
    accession_number: str,
    primary_document: str,
    xml_content: bytes,
    meta: dict,
) -> Path:
    """Persiste el XML crudo + un JSON con los metadatos del filing."""
    target_dir = filing_dir(cik_padded, accession_number)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Guardamos el XML con su nombre original para mantener trazabilidad con la SEC.
    xml_path = target_dir / primary_document
    xml_path.write_bytes(xml_content)

    # Metadatos: lo mínimo para poder reconstruir contexto sin volver a llamar
    # a la SEC (qué empresa, qué fechas, qué fichero principal).
    meta_path = target_dir / "submission_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    return target_dir


def download_company(client: SecClient, ticker: str, cik_padded: str, limit: int) -> None:
    """Orquesta la descarga completa para una empresa.

    Imprime progreso por consola (en Fase 1 con `print` está bien; un sistema
    de logging estructurado llegará cuando el código sea más grande).
    """
    print(f"\n=== {ticker} (CIK {cik_padded}) ===")
    submissions = fetch_submissions(client, cik_padded)
    form4s = extract_recent_form4s(submissions, limit)
    print(f"  encontrados {len(form4s)} Forms 4 recientes")

    downloaded = 0
    skipped = 0
    for filing in form4s:
        accession = filing["accession_number"]
        if already_downloaded(cik_padded, accession):
            skipped += 1
            continue

        url = build_filing_url(cik_padded, accession, filing["primary_document"])
        response = client.get(url)

        meta = {
            "ticker": ticker,
            "cik": cik_padded,
            "accession_number": accession,
            "filing_date": filing["filing_date"],
            "report_date": filing["report_date"],
            "primary_document": filing["primary_document"],
            "source_url": url,
        }
        save_filing(cik_padded, accession, filing["primary_document"], response.content, meta)
        downloaded += 1
        print(f"  [{filing['filing_date']}] {accession} OK")

    print(f"  resumen: {downloaded} descargados, {skipped} ya estaban")
