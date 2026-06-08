"""Repair-Issues für veraltete Tarifdaten und dauerhafte Abruf-Fehler.

Quality-Scale-Regel ``repair-issues`` (Gold): wartungs- bzw. nutzerrelevante
Probleme werden über die ``issue_registry`` gemeldet (sichtbar unter
Einstellungen → System → Reparaturen). Beide hier behandelten Fälle sind nicht
automatisch behebbar (``is_fixable=False``) – sie weisen lediglich auf externen
Handlungsbedarf hin (Integrations-Update bzw. vorübergehende API-Störung) und
schließen sich von selbst, sobald die Ursache entfällt.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import DOMAIN, TARIFF_DATA_YEAR

# Issue-IDs (stabil – dienen zugleich als Übersetzungsschlüssel).
ISSUE_TARIFF_DATA_OUTDATED = "tariff_data_outdated"
ISSUE_FETCH_FAILING = "fetch_failing"


def async_check_tariff_data_year(
    hass: HomeAssistant, now: datetime | None = None
) -> None:
    """Meldet bzw. schließt das Issue für veraltete Netzentgelte/Förderbeitrag.

    ``grid_fees.py`` und ``surcharges.py`` enthalten jährlich zu
    aktualisierende Sätze ("Stand ``TARIFF_DATA_YEAR``"). Ist das aktuelle
    Kalenderjahr bereits weiter fortgeschritten, würde die Integration sonst
    still mit veralteten Werten weiterrechnen, ohne dass es jemand bemerkt.
    """
    now = now or dt_util.now()
    if now.year > TARIFF_DATA_YEAR:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_TARIFF_DATA_OUTDATED,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_TARIFF_DATA_OUTDATED,
            translation_placeholders={"data_year": str(TARIFF_DATA_YEAR)},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_TARIFF_DATA_OUTDATED)


def async_update_fetch_issue(hass: HomeAssistant, *, failing: bool) -> None:
    """Legt das Issue für dauerhafte Abruf-Fehler an oder schließt es wieder.

    Schlägt der Preis-Abruf fehl, behält der Coordinator bewusst die
    zwischengespeicherten Daten (siehe ``coordinator._async_update_data``).
    Hält der Fehler jedoch über ``FETCH_FAILURE_REPAIR_HOURS`` an, sind die
    angezeigten Preise vermutlich veraltet – der Nutzer wird per Repair-Issue
    informiert. Gelingt ein Abruf wieder, wird das Issue automatisch
    geschlossen (``failing=False``).
    """
    if failing:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_FETCH_FAILING,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_FETCH_FAILING,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_FETCH_FAILING)
