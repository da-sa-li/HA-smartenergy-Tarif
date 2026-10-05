"""Tests der Repair-Issues für veraltete Tarifdaten und Abruf-Fehler.

Beide Issues sind reine Datums-/Zustandsprüfungen (``is_fixable=False``); die
Sollwerte (Schwellenjahr ``TARIFF_DATA_YEAR``, Severity, Übersetzungsschlüssel)
ergeben sich direkt aus der Spezifikation in Issue #36 und werden hier gegen
die hinterlegten Konstanten geprüft – nicht gegen den Code, der sie erzeugt.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.const import DOMAIN, TARIFF_DATA_YEAR
from custom_components.smartenergy.repairs import (
    ISSUE_FETCH_FAILING,
    ISSUE_TARIFF_DATA_OUTDATED,
    async_check_tariff_data_year,
    async_update_fetch_issue,
    fetch_issue_id,
)
from tests.conftest import VIENNA

# Zeitstempel mit Zeitzone, wie in der ganzen Suite (CLAUDE.md). Die geprüfte
# Funktion liest zwar nur das Kalenderjahr, ihr Vorgabewert ist aber
# ``dt_util.now()`` – ein zeitzonenbewusster Zeitpunkt. Der Test reicht damit
# dieselbe Art von Objekt hinein wie der produktive Pfad.


def _issue(hass: HomeAssistant, issue_id: str) -> ir.IssueEntry | None:
    """Kurzschreibweise: das Issue zur ``DOMAIN`` aus der Registry holen."""
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def test_veraltete_tarifdaten_erzeugen_ein_issue(hass: HomeAssistant):
    """Im Folgejahr des Datenjahrs entsteht das WARNING-Issue (nicht behebbar)."""
    now = datetime(TARIFF_DATA_YEAR + 1, 1, 1, tzinfo=VIENNA)
    async_check_tariff_data_year(hass, now)

    issue = _issue(hass, ISSUE_TARIFF_DATA_OUTDATED)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == ISSUE_TARIFF_DATA_OUTDATED
    assert issue.translation_placeholders == {"data_year": str(TARIFF_DATA_YEAR)}


async def test_im_datenjahr_entsteht_kein_issue(hass: HomeAssistant):
    """Im (oder vor dem) Datenjahr selbst entsteht kein Issue."""
    async_check_tariff_data_year(hass, datetime(TARIFF_DATA_YEAR, 12, 31, tzinfo=VIENNA))
    assert _issue(hass, ISSUE_TARIFF_DATA_OUTDATED) is None


async def test_tarifdaten_issue_schliesst_sich_wieder(hass: HomeAssistant):
    """Ein bereits gemeldetes Issue wird geschlossen, sobald das Jahr wieder passt.

    Praxisfall: Nutzer aktualisiert die Integration auf eine Version mit neuem
    ``TARIFF_DATA_YEAR`` – das alte Issue soll dann automatisch verschwinden.
    """
    async_check_tariff_data_year(hass, datetime(TARIFF_DATA_YEAR + 1, 1, 1, tzinfo=VIENNA))
    assert _issue(hass, ISSUE_TARIFF_DATA_OUTDATED) is not None

    async_check_tariff_data_year(hass, datetime(TARIFF_DATA_YEAR, 6, 1, tzinfo=VIENNA))
    assert _issue(hass, ISSUE_TARIFF_DATA_OUTDATED) is None


@pytest.mark.parametrize("year_offset", [2, 5])
async def test_tarifdaten_issue_gilt_auch_in_spaeteren_jahren(
    hass: HomeAssistant, year_offset: int
):
    """Auch mehrere Jahre nach dem Datenjahr bleibt das Issue aktiv."""
    async_check_tariff_data_year(
        hass, datetime(TARIFF_DATA_YEAR + year_offset, 3, 1, tzinfo=VIENNA)
    )
    assert _issue(hass, ISSUE_TARIFF_DATA_OUTDATED) is not None


def _eintrag(hass: HomeAssistant, titel: str) -> MockConfigEntry:
    """Einen Config-Eintrag mit Titel anlegen – das Abruf-Issue gehört je einem."""
    eintrag = MockConfigEntry(domain=DOMAIN, title=titel)
    eintrag.add_to_hass(hass)
    return eintrag


async def test_dauerhafter_abruf_fehler_erzeugt_ein_issue(hass: HomeAssistant):
    """Ein dauerhafter Abruf-Fehler erzeugt ein WARNING-Issue (nicht behebbar).

    Die ID trägt die entry_id, der Übersetzungsschlüssel bleibt der alte; der
    Eintragstitel steht als Platzhalter ``name`` im Text.
    """
    eintrag = _eintrag(hass, "smartTIMES Strompreishelfer")
    async_update_fetch_issue(hass, eintrag, failing=True)

    issue = _issue(hass, f"fetch_failing_{eintrag.entry_id}")
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == ISSUE_FETCH_FAILING
    assert issue.translation_placeholders == {"name": "smartTIMES Strompreishelfer"}


async def test_abruf_issue_schliesst_sich_bei_erfolg(hass: HomeAssistant):
    """Gelingt der Abruf wieder, wird das Issue automatisch geschlossen."""
    eintrag = _eintrag(hass, "smartTIMES Strompreishelfer")
    async_update_fetch_issue(hass, eintrag, failing=True)
    assert _issue(hass, fetch_issue_id(eintrag.entry_id)) is not None

    async_update_fetch_issue(hass, eintrag, failing=False)
    assert _issue(hass, fetch_issue_id(eintrag.entry_id)) is None


async def test_ohne_stoerung_entsteht_kein_issue(hass: HomeAssistant):
    """Ohne anhaltenden Fehler entsteht erst gar kein Issue."""
    eintrag = _eintrag(hass, "smartTIMES Strompreishelfer")
    async_update_fetch_issue(hass, eintrag, failing=False)
    assert _issue(hass, fetch_issue_id(eintrag.entry_id)) is None


async def test_abruf_issue_einer_instanz_bleibt_bei_erfolg_der_anderen_offen(
    hass: HomeAssistant,
):
    """Gelingt der Abruf des einen Eintrags, bleibt das Issue des anderen offen.

    Mit einem gemeinsamen Issue schlösse der erfolgreiche Eintrag die Meldung
    für den gestörten gleich mit – der Nutzer erführe nie, dass dessen Preise
    veraltet sind.
    """
    gestoert = _eintrag(hass, "smartCONTROL Strompreishelfer")
    intakt = _eintrag(hass, "smartTIMES Strompreishelfer")

    async_update_fetch_issue(hass, gestoert, failing=True)
    async_update_fetch_issue(hass, intakt, failing=False)

    assert _issue(hass, fetch_issue_id(gestoert.entry_id)) is not None
    assert _issue(hass, fetch_issue_id(intakt.entry_id)) is None
