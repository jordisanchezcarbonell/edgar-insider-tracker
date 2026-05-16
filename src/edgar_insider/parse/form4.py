"""Parser de Forms 4 (SEC EDGAR).

Convierte el XML crudo (`ownershipDocument`) en un `ParsedFiling` tipado.
Filosofía: fallar ruidosamente con `Form4ParseError` ante XML inesperado, y
modelar la variabilidad real (X0508 vs X0609, booleanos `0`/`1` vs `true`/
`false`, campos opcionales que sí o no aparecen, footnotes esparcidas por
subcampos) en helpers privados — para que las funciones públicas se lean
casi como una lectura del schema, no como un mar de `.find()`s.

API pública:
    parse_form4(xml_bytes)          -> ParsedFiling
    parse_form4_file(xml_path)      -> ParsedFiling
    to_transaction_rows(filing, ...) -> list[dict]      (aplana para análisis/persistencia)
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable
from xml.etree.ElementTree import Element, ParseError, fromstring

from edgar_insider.parse.codes import categorize
from edgar_insider.parse.models import (
    Form4ParseError,
    Insider,
    Issuer,
    ParsedFiling,
    Transaction,
)


# ---------------------------------------------------------------------------
# Helpers de bajo nivel (extraen y normalizan campos del XML)
# ---------------------------------------------------------------------------


def _text(parent: Element | None, path: str) -> str | None:
    """Devuelve el texto de `parent/path` o None si no existe o está vacío."""
    if parent is None:
        return None
    el = parent.find(path)
    if el is None or el.text is None:
        return None
    stripped = el.text.strip()
    return stripped or None


def _value(parent: Element | None, path: str) -> str | None:
    """La SEC envuelve casi todo en `<X><value>...</value></X>`. Atajo."""
    return _text(parent, f"{path}/value")


def _decimal(parent: Element | None, path: str) -> Decimal | None:
    raw = _value(parent, path)
    if raw is None:
        return None
    try:
        # Decimal(str) evita la contaminación binaria de pasar por float.
        return Decimal(raw)
    except InvalidOperation as exc:
        raise Form4ParseError(f"valor decimal inválido en {path!r}: {raw!r}") from exc


def _date(parent: Element | None, path: str) -> date | None:
    """Lee una fecha envuelta en `<X><value>YYYY-MM-DD</value></X>` (formato
    estándar dentro de transacciones)."""
    return _parse_iso_date(_value(parent, path), path)


def _date_unwrapped(parent: Element | None, path: str) -> date | None:
    """Lee una fecha como texto directo `<X>YYYY-MM-DD</X>` (usado por los
    campos a nivel de filing como `periodOfReport`, que NO están envueltos
    en `<value>`)."""
    return _parse_iso_date(_text(parent, path), path)


def _parse_iso_date(raw: str | None, path: str) -> date | None:
    if raw is None:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise Form4ParseError(f"fecha inválida en {path!r}: {raw!r}") from exc


def _bool(parent: Element | None, path: str, *, default: bool = False) -> bool:
    """La SEC usa indistintamente `0`/`1` y `true`/`false`. Normalizamos."""
    raw = _text(parent, path)
    if raw is None:
        return default
    raw_lower = raw.lower()
    if raw_lower in ("1", "true"):
        return True
    if raw_lower in ("0", "false"):
        return False
    raise Form4ParseError(f"booleano inesperado en {path!r}: {raw!r}")


def _footnote_ids(element: Element) -> tuple[str, ...]:
    """Junta TODOS los `footnoteId/@id` descendientes de un elemento, dedupe.

    Por qué recursivo: los footnoteIds aparecen colgando de subcampos
    distintos dentro de una misma transacción (a veces en transactionCoding,
    a veces en transactionShares, a veces en natureOfOwnership…). Subirlos
    todos a la Transaction simplifica el resto del pipeline.
    """
    seen: list[str] = []
    for el in element.iter("footnoteId"):
        fid = el.attrib.get("id")
        if fid and fid not in seen:
            seen.append(fid)
    return tuple(seen)


# ---------------------------------------------------------------------------
# Parsers de bloques semánticos
# ---------------------------------------------------------------------------


def _parse_issuer(root: Element) -> Issuer:
    issuer_el = root.find("issuer")
    if issuer_el is None:
        raise Form4ParseError("falta el bloque <issuer>")
    cik = _text(issuer_el, "issuerCik")
    name = _text(issuer_el, "issuerName")
    ticker = _text(issuer_el, "issuerTradingSymbol")
    if not (cik and name and ticker):
        raise Form4ParseError("issuer incompleto (cik/name/ticker)")
    return Issuer(cik=cik, name=name, ticker=ticker)


def _parse_reporting_owner(el: Element) -> Insider:
    cik = _text(el, "reportingOwnerId/rptOwnerCik")
    name = _text(el, "reportingOwnerId/rptOwnerName")
    if not (cik and name):
        raise Form4ParseError("reportingOwner sin cik o nombre")
    rel = el.find("reportingOwnerRelationship")
    return Insider(
        cik=cik,
        name=name,
        is_director=_bool(rel, "isDirector"),
        is_officer=_bool(rel, "isOfficer"),
        is_ten_percent_owner=_bool(rel, "isTenPercentOwner"),
        is_other=_bool(rel, "isOther"),
        officer_title=_text(rel, "officerTitle"),
        other_text=_text(rel, "otherText"),
    )


def _parse_footnotes(root: Element) -> dict[str, str]:
    block = root.find("footnotes")
    if block is None:
        return {}
    out: dict[str, str] = {}
    for fn in block.findall("footnote"):
        fid = fn.attrib.get("id")
        if not fid:
            continue
        out[fid] = (fn.text or "").strip()
    return out


def _parse_transaction(el: Element, *, is_derivative: bool) -> Transaction:
    """Parsea un nonDerivativeTransaction o derivativeTransaction.

    Mismo esqueleto en ambos; los campos extra (precio de ejercicio, expiración,
    underlying) solo se rellenan para derivativas.
    """
    security_title = _value(el, "securityTitle")
    transaction_date = _date(el, "transactionDate")
    code = _text(el, "transactionCoding/transactionCode")
    if not (security_title and transaction_date and code):
        raise Form4ParseError(
            "transacción incompleta (securityTitle/transactionDate/transactionCode)"
        )

    shares = _decimal(el, "transactionAmounts/transactionShares")
    if shares is None:
        raise Form4ParseError(f"transacción sin transactionShares (code={code})")

    nature_of_ownership = _value(el, "ownershipNature/natureOfOwnership")

    return Transaction(
        security_title=security_title,
        transaction_date=transaction_date,
        transaction_code=code,
        transaction_category=categorize(code),
        is_derivative=is_derivative,
        shares=shares,
        price_per_share=_decimal(el, "transactionAmounts/transactionPricePerShare"),
        acquired_or_disposed=_value(el, "transactionAmounts/transactionAcquiredDisposedCode") or "",
        shares_owned_following=_decimal(el, "postTransactionAmounts/sharesOwnedFollowingTransaction"),
        ownership_nature=_value(el, "ownershipNature/directOrIndirectOwnership") or "",
        indirect_owner_explanation=nature_of_ownership,
        footnote_ids=_footnote_ids(el),
        # Campos solo derivative — None en non-derivative.
        conversion_or_exercise_price=_decimal(el, "conversionOrExercisePrice") if is_derivative else None,
        expiration_date=_date(el, "expirationDate") if is_derivative else None,
        underlying_security_title=_value(el, "underlyingSecurity/underlyingSecurityTitle") if is_derivative else None,
        underlying_shares=_decimal(el, "underlyingSecurity/underlyingSecurityShares") if is_derivative else None,
    )


def _iter_transactions(root: Element) -> tuple[Iterable[Transaction], int]:
    """Recoge transacciones de ambas tablas y cuenta holdings saltadas."""
    transactions: list[Transaction] = []
    skipped_holdings = 0

    non_deriv = root.find("nonDerivativeTable")
    if non_deriv is not None:
        for tx_el in non_deriv.findall("nonDerivativeTransaction"):
            transactions.append(_parse_transaction(tx_el, is_derivative=False))
        skipped_holdings += len(non_deriv.findall("nonDerivativeHolding"))

    deriv = root.find("derivativeTable")
    if deriv is not None:
        for tx_el in deriv.findall("derivativeTransaction"):
            transactions.append(_parse_transaction(tx_el, is_derivative=True))
        skipped_holdings += len(deriv.findall("derivativeHolding"))

    return transactions, skipped_holdings


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def parse_form4(xml_bytes: bytes, *, accession: str | None = None) -> ParsedFiling:
    """Parsea el XML de un Form 4 a un `ParsedFiling`.

    `accession` es opcional: si se pasa, se incluye en cualquier excepción
    para facilitar el debugging desde el script de bulk-parse.
    """
    try:
        root = fromstring(xml_bytes)
    except ParseError as exc:
        raise Form4ParseError(f"XML malformed: {exc}", accession=accession) from exc

    if root.tag != "ownershipDocument":
        raise Form4ParseError(
            f"root inesperado: {root.tag!r} (esperaba 'ownershipDocument')",
            accession=accession,
        )

    document_type = _text(root, "documentType") or ""
    # Detectamos también amendments ("4/A") aunque no esperamos verlos en corpus.
    is_amendment = document_type.endswith("/A")
    base_doc_type = document_type.rstrip("/A")
    if base_doc_type != "4":
        raise Form4ParseError(
            f"documentType inesperado: {document_type!r}", accession=accession
        )

    schema_version = _text(root, "schemaVersion") or ""
    period_of_report = _date_unwrapped(root, "periodOfReport")
    if period_of_report is None:
        raise Form4ParseError("falta periodOfReport", accession=accession)

    try:
        issuer = _parse_issuer(root)
        owners = tuple(_parse_reporting_owner(el) for el in root.findall("reportingOwner"))
        if not owners:
            raise Form4ParseError("ningún reportingOwner")
        transactions, skipped = _iter_transactions(root)
    except Form4ParseError as exc:
        # Re-emitir con accession adjunto si no lo traía.
        if exc.accession is None and accession is not None:
            raise Form4ParseError(str(exc), accession=accession) from exc
        raise

    return ParsedFiling(
        schema_version=schema_version,
        document_type=document_type,
        period_of_report=period_of_report,
        is_amendment=is_amendment,
        not_subject_to_section_16=_bool(root, "notSubjectToSection16"),
        under_10b5_1_plan=_bool(root, "aff10b5One"),
        issuer=issuer,
        reporting_owners=owners,
        transactions=tuple(transactions),
        footnotes=_parse_footnotes(root),
        skipped_holdings_count=skipped,
    )


def parse_form4_file(xml_path: Path, *, accession: str | None = None) -> ParsedFiling:
    """Conveniencia: lee el fichero y delega en parse_form4."""
    return parse_form4(xml_path.read_bytes(), accession=accession)


def to_transaction_rows(
    filing: ParsedFiling,
    *,
    accession: str | None = None,
) -> list[dict]:
    """Aplana un ParsedFiling a filas — una por (transacción × reporting_owner).

    Cada fila incluye los IDs de footnote ya resueltos a su texto, concatenado
    con ' | ', para que Fase 3 (SQLite) y Fase 4 (pandas) puedan trabajar
    sobre datos planos sin tener que revolver las relaciones.

    Casi todos los Forms 4 tienen 1 reporting_owner; los pocos con N>1
    multiplicarán las filas (cada owner es co-responsable de cada transacción
    del filing). Esto es el comportamiento estándar para análisis: queremos
    una fila por insider afectado.
    """
    rows: list[dict] = []
    for owner in filing.reporting_owners:
        for tx in filing.transactions:
            footnotes_text = " | ".join(
                filing.footnotes[fid] for fid in tx.footnote_ids if fid in filing.footnotes
            )
            rows.append(
                {
                    "accession": accession,
                    "ticker": filing.issuer.ticker,
                    "issuer_cik": filing.issuer.cik,
                    "issuer_name": filing.issuer.name,
                    "insider_cik": owner.cik,
                    "insider_name": owner.name,
                    "is_director": owner.is_director,
                    "is_officer": owner.is_officer,
                    "is_ten_percent_owner": owner.is_ten_percent_owner,
                    "officer_title": owner.officer_title,
                    "period_of_report": filing.period_of_report.isoformat(),
                    "transaction_date": tx.transaction_date.isoformat(),
                    "security_title": tx.security_title,
                    "is_derivative": tx.is_derivative,
                    "transaction_code": tx.transaction_code,
                    "transaction_category": tx.transaction_category,
                    "acquired_or_disposed": tx.acquired_or_disposed,
                    "shares": str(tx.shares),
                    "price_per_share": str(tx.price_per_share) if tx.price_per_share is not None else None,
                    "shares_owned_following": (
                        str(tx.shares_owned_following) if tx.shares_owned_following is not None else None
                    ),
                    "ownership_nature": tx.ownership_nature,
                    "indirect_owner_explanation": tx.indirect_owner_explanation,
                    "under_10b5_1_plan": filing.under_10b5_1_plan,
                    "footnotes_text": footnotes_text or None,
                }
            )
    return rows
