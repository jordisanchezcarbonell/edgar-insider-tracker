"""Tests de los formatters de presentación.

Los formatters traducen valores SEC crudos a labels humanos al renderizar.
La capa de storage no se toca — la BBDD conserva el ALL-CAPS y los snake_case.
"""

from edgar_insider.parse.codes import TRANSACTION_CODES
from edgar_insider.ui.labels import (
    CATEGORY_LABELS,
    CODE_LEGEND_LABELS,
    ISSUER_DISPLAY_NAMES,
    format_category,
    format_insider_name,
    format_issuer_name,
    format_role,
)


# ---------------------------------------------------------------------------
# format_insider_name — el más delicado por los edge cases
# ---------------------------------------------------------------------------


def test_format_insider_name_all_caps():
    assert format_insider_name("HUANG JEN HSUN") == "Huang Jen Hsun"
    assert format_insider_name("MURDOCH JAMES R") == "Murdoch James R"


def test_format_insider_name_preserves_apostrophe():
    # str.title() debe mantener el apóstrofe correctamente.
    assert format_insider_name("O'BRIEN DEIRDRE") == "O'Brien Deirdre"


def test_format_insider_name_preserves_hyphen():
    # Apellidos compuestos con guión.
    assert format_insider_name("WILSON-THOMPSON KATHLEEN") == "Wilson-Thompson Kathleen"


def test_format_insider_name_already_titlecased_passes_through():
    assert format_insider_name("Borders Ben") == "Borders Ben"
    assert format_insider_name("Musk Elon") == "Musk Elon"


def test_format_insider_name_handles_empty_and_none():
    assert format_insider_name("") == ""
    assert format_insider_name(None) == ""


# ---------------------------------------------------------------------------
# format_issuer_name — mapa per-ticker
# ---------------------------------------------------------------------------


def test_format_issuer_name_known_ticker_uses_curated():
    assert format_issuer_name("MSFT", "MICROSOFT CORP") == "Microsoft Corp."
    assert format_issuer_name("NVDA", "NVIDIA CORP") == "NVIDIA Corp."
    assert format_issuer_name("AAPL", "Apple Inc.") == "Apple Inc."


def test_format_issuer_name_unknown_ticker_returns_raw():
    # Para un ticker que aún no hemos curado, dejamos el nombre tal cual.
    assert format_issuer_name("ZZZZ", "ZZZZ Co") == "ZZZZ Co"


def test_all_target_tickers_have_curated_name():
    # Si alguien añade un ticker a TARGET_CIKS sin curar su display name,
    # este test no falla automáticamente pero documenta los curados actuales.
    from edgar_insider.config import TARGET_CIKS
    missing = set(TARGET_CIKS) - set(ISSUER_DISPLAY_NAMES)
    assert not missing, f"Tickers sin display name curado: {missing}"


# ---------------------------------------------------------------------------
# format_category
# ---------------------------------------------------------------------------


def test_format_category_known():
    assert format_category("open_market_purchase") == "Compra de mercado"
    assert format_category("tax_withholding") == "Retención fiscal"
    assert format_category("award_grant") == "Award/grant"


def test_format_category_unknown_falls_back_to_titlecase():
    # Si introducimos una categoría nueva sin label, no crashea.
    assert format_category("fake_unknown_cat") == "Fake Unknown Cat"


def test_every_known_category_has_label():
    # Regresión: si parse/codes.py añade una categoría nueva, este test
    # falla hasta que añadan también el label en ui/labels.py.
    known_categories = {info.category for info in TRANSACTION_CODES.values()}
    missing = known_categories - set(CATEGORY_LABELS)
    assert not missing, f"Categorías sin label humana: {missing}"


# ---------------------------------------------------------------------------
# CODE_LEGEND_LABELS
# ---------------------------------------------------------------------------


def test_every_sec_code_has_legend_label():
    # Mismo principio: añadir un código SEC sin su label de leyenda
    # debe romper este test.
    missing = set(TRANSACTION_CODES) - set(CODE_LEGEND_LABELS)
    assert not missing, f"Códigos SEC sin entrada en CODE_LEGEND_LABELS: {missing}"


def test_legend_labels_start_with_code():
    # Convención: "P · Compra de mercado" — el código va al principio.
    for code, label in CODE_LEGEND_LABELS.items():
        assert label.startswith(f"{code} · "), f"{code!r} → {label!r} no sigue convención"


# ---------------------------------------------------------------------------
# format_role — derivado de officer_title + flags booleanos
# ---------------------------------------------------------------------------


def test_format_role_officer_title_wins():
    assert format_role("Chief Executive Officer", is_director=True, is_officer=True) == "Chief Executive Officer"


def test_format_role_pure_director_no_title():
    # Caso Andrea Jung (AAPL): director pero no officer; officer_title vacío.
    assert format_role(None, is_director=True) == "Director"
    assert format_role("", is_director=True) == "Director"


def test_format_role_ten_percent_owner():
    assert format_role(None, is_ten_percent_owner=True) == "10% Owner"


def test_format_role_other():
    assert format_role(None, is_other=True) == "Other"


def test_format_role_no_signal_returns_dash():
    assert format_role(None) == "—"
    assert format_role("") == "—"


def test_format_role_precedence():
    # Officer title gana sobre cualquier flag.
    assert format_role("CFO", is_director=True, is_ten_percent_owner=True) == "CFO"
    # Sin título, director gana sobre 10% owner (más específico institucionalmente).
    assert format_role(None, is_director=True, is_ten_percent_owner=True) == "Director"
