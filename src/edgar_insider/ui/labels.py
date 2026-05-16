"""Formatters de presentación para nombres y códigos.

La capa de storage conserva los valores crudos exactamente como vienen de
SEC (ALL-CAPS, snake_case, etc.) porque ese es el origen de verdad. Este
módulo encapsula la traducción a labels humanas que se aplican al renderizar
en la app y en el CLI.

Decisión de diseño: NO reordenamos `Last First` → `First Last` en los
nombres de insiders. SEC reporta siempre como `Last First [Middle]` y
reordenar romperia con apellidos compuestos (`Van Der Berg`, `De La Cruz`,
`MacGregor`). Solo title-case.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Issuer display names — curado manual.
# Generic title-case rompería marcas como "NVIDIA". Como solo son 5 issuers
# y la SEC mezcla X0508 ALL-CAPS con X0609 title-case, un mapa explícito es
# más limpio y más correcto que cualquier heurística.
# ---------------------------------------------------------------------------

ISSUER_DISPLAY_NAMES: dict[str, str] = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corp.",
    "NVDA": "NVIDIA Corp.",
    "TSLA": "Tesla, Inc.",
    "META": "Meta Platforms, Inc.",
}


def format_issuer_name(ticker: str, raw_name: str) -> str:
    """Devuelve el nombre curado para tickers conocidos; raw_name como fallback."""
    return ISSUER_DISPLAY_NAMES.get(ticker, raw_name)


# ---------------------------------------------------------------------------
# Insider name formatting.
# str.title() de Python maneja correctamente apóstrofes (O'BRIEN → O'Brien)
# y guiones (WILSON-THOMPSON → Wilson-Thompson). Para los pocos casos donde
# falla (siglas, sufijos como "Jr", "II", "III"), aceptamos el resultado
# de title() — es muchísimo mejor que el ALL-CAPS de partida.
# ---------------------------------------------------------------------------


def format_insider_name(raw: str | None) -> str:
    """Title-case manteniendo el orden SEC (Apellido Nombre [Inicial])."""
    if not raw:
        return ""
    return raw.title()


# ---------------------------------------------------------------------------
# Category labels — todas las categorías declaradas en parse/codes.py, no
# solo las que aparecen en el corpus actual. Si mañana añadimos un ticker
# con códigos nuevos, queremos que se muestren bonitos sin tener que tocar.
# ---------------------------------------------------------------------------

CATEGORY_LABELS: dict[str, str] = {
    "open_market_purchase":   "Compra de mercado",
    "open_market_sale":       "Venta de mercado",
    "tax_withholding":        "Retención fiscal",
    "derivative_exercise":    "Ejercicio de derivado",
    "award_grant":            "Award/grant",
    "gift":                   "Donación",
    "disposition_to_issuer":  "Disposición a la empresa",
    "discretionary_plan":     "Plan discrecional",
    "conversion":             "Conversión",
    "derivative_expiration":  "Expiración de derivado",
    "small_acquisition":      "Adquisición pequeña",
    "inheritance":            "Herencia",
    "voting_trust":           "Voting trust",
    "other":                  "Otro",
    "equity_swap":            "Equity swap",
    "tender_offer":           "Tender offer",
    "unknown":                "Desconocido",
}


def format_category(category: str) -> str:
    """Lookup en CATEGORY_LABELS; fallback a title-case del snake_case."""
    if category in CATEGORY_LABELS:
        return CATEGORY_LABELS[category]
    return category.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Code legend labels — combinan el código SEC con su descripción humana.
# Útil en leyendas de gráficos donde solo "P" sin contexto es críptico.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Rol derivado del insider.
#
# La SEC solo rellena officer_title cuando la persona es officer. Para los
# directores puros (Andrea Jung en AAPL, Susan Wagner) este campo viene vacío
# — NO es un dato faltante, es semánticamente correcto (un director no tiene
# "officer title"). Esta función deriva una columna "Rol" que captura el
# papel real de cada insider en el filing, usando los booleanos para los
# casos donde officer_title está vacío.
# ---------------------------------------------------------------------------


def format_role(
    officer_title: str | None,
    *,
    is_director: bool = False,
    is_officer: bool = False,
    is_ten_percent_owner: bool = False,
    is_other: bool = False,
) -> str:
    """Devuelve el rol más específico disponible.

    Precedencia: título de officer (más informativo) > Director > 10% Owner
    > Other > "—". Si la persona es tanto director como officer (caso de
    fundadores tipo Jensen Huang, Musk), priorizamos el título de officer
    porque dice más.
    """
    if officer_title:
        return officer_title
    if is_officer:
        # Defensivo: hay officer pero sin título — raro pero lo etiquetamos.
        return "Officer"
    if is_director:
        return "Director"
    if is_ten_percent_owner:
        return "10% Owner"
    if is_other:
        return "Other"
    return "—"


CODE_LEGEND_LABELS: dict[str, str] = {
    "P": "P · Compra de mercado",
    "S": "S · Venta",
    "F": "F · Retención fiscal",
    "M": "M · Ejercicio de derivado",
    "A": "A · Award/grant",
    "G": "G · Donación",
    "D": "D · Disposición a la empresa",
    "C": "C · Conversión",
    "E": "E · Expiración de derivado (corto)",
    "H": "H · Expiración de derivado (largo)",
    "O": "O · Ejercicio derivado OTM",
    "X": "X · Ejercicio derivado ITM",
    "I": "I · Plan discrecional",
    "J": "J · Otra adquisición/disposición",
    "K": "K · Equity swap",
    "L": "L · Adquisición pequeña",
    "U": "U · Tender en cambio de control",
    "W": "W · Herencia",
    "Z": "Z · Voting trust",
}
