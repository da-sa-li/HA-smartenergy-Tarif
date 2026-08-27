"""Tests für die Übersetzungsdateien.

``strings.json`` ist die Quelle, gegen die hassfest prüft, und zugleich der
Rückfall für jede Sprache ohne eigene Datei. Fehlt dort ein Schlüssel, den eine
Übersetzung kennt, zeigt die Oberfläche in allen übrigen Sprachen den rohen
Schlüsselnamen. Genau das war für ``exact_hours`` der Fall.

Verglichen werden ausschließlich die Dateien untereinander – nicht Code gegen
sich selbst –, der Test ist also keine Tautologie.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Am Ort dieser Datei verankert, nicht am Arbeitsverzeichnis: Mit einem
# relativen Pfad findet der glob unten aus einem anderen Verzeichnis heraus
# nichts, und die beiden parametrisierten Tests werden dann still zu Skips
# statt zu Fehlschlägen. Dieselbe Verankerung nutzen conftest.py (Fixtures)
# und test_api_live.py (Manifest).
UEBERSETZUNGSWURZEL = (
    Path(__file__).resolve().parents[1] / "custom_components" / "smartenergy"
)
STRINGS = UEBERSETZUNGSWURZEL / "strings.json"
SPRACHDATEIEN = sorted((UEBERSETZUNGSWURZEL / "translations").glob("*.json"))


def _schluesselmenge(wert: object, praefix: str = "") -> set[str]:
    """Alle Pfade eines verschachtelten JSON-Objekts als punktgetrennte Namen."""
    if not isinstance(wert, dict):
        return {praefix}
    schluessel: set[str] = set()
    for name, unterwert in wert.items():
        pfad = f"{praefix}.{name}" if praefix else name
        schluessel |= _schluesselmenge(unterwert, pfad)
    return schluessel


def _lade(pfad: Path) -> dict:
    return json.loads(pfad.read_text(encoding="utf-8"))


def test_sprachdateien_vorhanden():
    """Es gibt überhaupt Übersetzungen zu prüfen (schützt vor einem leeren Test)."""
    assert SPRACHDATEIEN, "Keine Dateien in translations/ gefunden."


@pytest.mark.parametrize("sprachdatei", SPRACHDATEIEN, ids=lambda p: p.name)
def test_schluessel_decken_sich_mit_strings_json(sprachdatei: Path):
    """Jede Sprachdatei führt exakt dieselben Schlüssel wie ``strings.json``."""
    erwartet = _schluesselmenge(_lade(STRINGS))
    tatsaechlich = _schluesselmenge(_lade(sprachdatei))

    fehlend = sorted(erwartet - tatsaechlich)
    ueberzaehlig = sorted(tatsaechlich - erwartet)

    assert not fehlend, f"{sprachdatei.name} fehlen Schlüssel: {fehlend}"
    assert not ueberzaehlig, (
        f"{sprachdatei.name} hat Schlüssel, die strings.json nicht kennt "
        f"(dort ergänzen): {ueberzaehlig}"
    )


@pytest.mark.parametrize("sprachdatei", SPRACHDATEIEN, ids=lambda p: p.name)
def test_keine_leeren_texte(sprachdatei: Path):
    """Kein Schlüssel trägt einen leeren Text (sähe in der UI aus wie ein Fehler)."""
    def pruefe(wert: object, pfad: str = "") -> None:
        if isinstance(wert, dict):
            for name, unterwert in wert.items():
                pruefe(unterwert, f"{pfad}.{name}" if pfad else name)
            return
        assert isinstance(wert, str) and wert.strip(), f"{sprachdatei.name}: {pfad} ist leer."

    pruefe(_lade(sprachdatei))
