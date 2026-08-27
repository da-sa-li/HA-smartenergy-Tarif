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

from custom_components.smartenergy.const import DOMAIN, TARIFF_DATA_YEAR
from custom_components.smartenergy.repairs import (
    ISSUE_FETCH_FAILING,
    ISSUE_TARIFF_DATA_OUTDATED,
    async_check_tariff_data_year,
    async_update_fetch_issue,
)


def _issue(hass: HomeAssistant, issue_id: str) -> ir.IssueEntry | None:
    """Kurzschreibweise: das Issue zur ``DOMAIN`` aus der Registry holen."""
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def test_veraltete_tarifdaten_erzeugen_ein_issue(hass: HomeAssistant):
    """Im Folgejahr des Datenjahrs entsteht das WARNING-Issue (nicht behebbar)."""
    now = datetime(TARIFF_DATA_YEAR + 1, 1, 1)
    async_check_tariff_data_year(hass, now)

    issue = _issue(hass, ISSUE_TARIFF_DATA_OUTDATED)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == ISSUE_TARIFF_DATA_OUTDATED
    assert issue.translation_placeholders == {"data_year": str(TARIFF_DATA_YEAR)}


async def test_im_datenjahr_entsteht_kein_issue(hass: HomeAssistant):
    """Im (oder vor dem) Datenjahr selbst entsteht kein Issue."""
    async_check_tariff_data_year(hass, datetime(TARIFF_DATA_YEAR, 12, 31))
    assert _issue(hass, ISSUE_TARIFF_DATA_OUTDATED) is None


async def test_tarifdaten_issue_schliesst_sich_wieder(hass: HomeAssistant):
    """Ein bereits gemeldetes Issue wird geschlossen, sobald das Jahr wieder passt.

    Praxisfall: Nutzer aktualisiert die Integration auf eine Version mit neuem
    ``TARIFF_DATA_YEAR`` – das alte Issue soll dann automatisch verschwinden.
    """
    async_check_tariff_data_year(hass, datetime(TARIFF_DATA_YEAR + 1, 1, 1))
    assert _issue(hass, ISSUE_TARIFF_DATA_OUTDATED) is not None

    async_check_tariff_data_year(hass, datetime(TARIFF_DATA_YEAR, 6, 1))
    assert _issue(hass, ISSUE_TARIFF_DATA_OUTDATED) is None


@pytest.mark.parametrize("year_offset", [2, 5])
async def test_tarifdaten_issue_gilt_auch_in_spaeteren_jahren(
    hass: HomeAssistant, year_offset: int
):
    """Auch mehrere Jahre nach dem Datenjahr bleibt das Issue aktiv."""
    async_check_tariff_data_year(hass, datetime(TARIFF_DATA_YEAR + year_offset, 3, 1))
    assert _issue(hass, ISSUE_TARIFF_DATA_OUTDATED) is not None


async def test_dauerhafter_abruf_fehler_erzeugt_ein_issue(hass: HomeAssistant):
    """Ein dauerhafter Abruf-Fehler erzeugt ein WARNING-Issue (nicht behebbar)."""
    async_update_fetch_issue(hass, failing=True)

    issue = _issue(hass, ISSUE_FETCH_FAILING)
    assert issue is not None
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == ISSUE_FETCH_FAILING


async def test_abruf_issue_schliesst_sich_bei_erfolg(hass: HomeAssistant):
    """Gelingt der Abruf wieder, wird das Issue automatisch geschlossen."""
    async_update_fetch_issue(hass, failing=True)
    assert _issue(hass, ISSUE_FETCH_FAILING) is not None

    async_update_fetch_issue(hass, failing=False)
    assert _issue(hass, ISSUE_FETCH_FAILING) is None


async def test_ohne_stoerung_entsteht_kein_issue(hass: HomeAssistant):
    """Ohne anhaltenden Fehler entsteht erst gar kein Issue."""
    async_update_fetch_issue(hass, failing=False)
    assert _issue(hass, ISSUE_FETCH_FAILING) is None
