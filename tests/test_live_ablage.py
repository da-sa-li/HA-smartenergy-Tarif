"""Prüft die Ablage der Live-Antworten (``lege_antwort_ab``) – ohne Netzzugang.

Die Funktion selbst lebt in ``test_api_live.py``, dessen Tests ohne ``--live``
übersprungen werden. Sie braucht aber kein Netz, und die Zusage, die sie gibt,
ist prüfenswert: Die abgelegte Datei muss sich gegen ``tests/fixtures/`` diffen
lassen, sonst nützt das Artefakt im Fehler-Issue nichts.

Sollwert für die Formatierung ist deshalb die eingecheckte Fixture selbst und
keine Nachbildung von ``json.dumps`` – geprüft wird die Eigenschaft, auf die es
ankommt, nicht die Implementierung, die sie herstellt.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_api_live import ANTWORT_ABLAGE_ENV, lege_antwort_ab

from custom_components.smartenergy.const import (
    TARIFF_SMARTCONTROL,
    TARIFF_SMARTTIMES,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_ablage_ohne_zielverzeichnis_schreibt_nichts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ohne die Umgebungsvariable hinterlässt ein Lauf nichts auf der Platte.

    Lokal ruft man ``pytest -m live --live`` ohne sie auf; dort soll der Test
    keine Dateien im Arbeitsverzeichnis zurücklassen.
    """
    monkeypatch.delenv(ANTWORT_ABLAGE_ENV, raising=False)
    monkeypatch.chdir(tmp_path)

    lege_antwort_ab(TARIFF_SMARTTIMES, '{"wert": 1}')

    assert list(tmp_path.iterdir()) == [], (
        f"Ohne {ANTWORT_ABLAGE_ENV} darf nichts geschrieben werden."
    )


@pytest.mark.parametrize("tarif", [TARIFF_SMARTTIMES, TARIFF_SMARTCONTROL])
def test_abgelegte_antwort_ist_byte_gleich_zur_fixture(
    tarif: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die Ablage formatiert wie die Fixture – nur so ist der Diff aussagekräftig.

    Der Text der Fixture wird minifiziert übergeben, so wie die API liefert.
    Entsteht daraus byte-genau wieder die Fixture-Datei, zeigt ein ``diff``
    gegen ``tests/fixtures/`` ausschließlich echte Unterschiede. Zugleich belegt
    der Test, dass der Dateiname dem Tarif-Schlüssel folgt und ein noch nicht
    vorhandenes Zielverzeichnis angelegt wird.
    """
    fixture = FIXTURES / f"{tarif}.json"
    ablage = tmp_path / "noch-nicht-da"
    monkeypatch.setenv(ANTWORT_ABLAGE_ENV, str(ablage))

    lege_antwort_ab(tarif, json.dumps(json.loads(fixture.read_text(encoding="utf-8"))))

    assert (ablage / f"{tarif}.json").read_bytes() == fixture.read_bytes()


def test_nicht_json_antwort_wird_roh_als_txt_abgelegt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eine Fehlerseite landet unverändert als ``.txt``.

    Sie lässt sich nicht wie JSON formatieren, ist aber selbst die Auskunft
    darüber, was schiefging – und darf deshalb nicht verlorengehen.
    """
    monkeypatch.setenv(ANTWORT_ABLAGE_ENV, str(tmp_path))
    seite = "<html><body>503 Service Unavailable</body></html>"

    lege_antwort_ab(TARIFF_SMARTTIMES, seite)

    assert (tmp_path / f"{TARIFF_SMARTTIMES}.txt").read_text(encoding="utf-8") == seite
    assert not (tmp_path / f"{TARIFF_SMARTTIMES}.json").exists()
