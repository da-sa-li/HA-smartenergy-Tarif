"""Repair-Issues für veraltete Tarifdaten und dauerhafte Abruf-Fehler.

Quality-Scale-Regel ``repair-issues`` (Gold): wartungs- bzw. nutzerrelevante
Probleme werden über die ``issue_registry`` gemeldet (sichtbar unter
Einstellungen → System → Reparaturen). Beide hier behandelten Fälle sind nicht
automatisch behebbar (``is_fixable=False``) – sie weisen lediglich auf externen
Handlungsbedarf hin (Integrations-Update bzw. vorübergehende API-Störung) und
schließen sich von selbst, sobald die Ursache entfällt.

Das Issue für veraltete Tarifdaten gilt für alle Einträge gleich und ist daher
einmalig. Das Abruf-Issue dagegen wird **je Config-Eintrag** geführt: Seit
mehrere Einträge (einer je Zähler) möglich sind, kann der Abruf des einen
scheitern, während der des anderen gelingt. Ein gemeinsames Issue schlösse der
erfolgreiche Eintrag dann für den gestörten gleich mit.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import DOMAIN, TARIFF_DATA_YEAR

# Issue-IDs (stabil – dienen zugleich als Übersetzungsschlüssel).
ISSUE_TARIFF_DATA_OUTDATED = "tariff_data_outdated"
ISSUE_FETCH_FAILING = "fetch_failing"


def fetch_issue_id(entry_id: str) -> str:
    """Issue-ID des Abruf-Issues eines Config-Eintrags.

    Bis Version 4.3 gab es nur einen Eintrag und das Issue hieß schlicht
    ``ISSUE_FETCH_FAILING``. Der Übersetzungsschlüssel bleibt dieser Name, nur
    die ID bekommt die entry_id angehängt.
    """
    return f"{ISSUE_FETCH_FAILING}_{entry_id}"


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


def async_update_fetch_issue(
    hass: HomeAssistant, entry: ConfigEntry, *, failing: bool
) -> None:
    """Legt das Abruf-Issue eines Eintrags an oder schließt es wieder.

    Schlägt der Preis-Abruf fehl, behält der Coordinator bewusst die
    zwischengespeicherten Daten (siehe ``coordinator._async_update_data``).
    Hält der Fehler jedoch über ``FETCH_FAILURE_REPAIR_HOURS`` an, sind die
    angezeigten Preise vermutlich veraltet – der Nutzer wird per Repair-Issue
    informiert. Gelingt ein Abruf wieder, wird das Issue automatisch
    geschlossen (``failing=False``). Der Eintragstitel steht im Text, damit bei
    mehreren Einträgen erkennbar ist, welcher betroffen ist.
    """
    issue_id = fetch_issue_id(entry.entry_id)
    if failing:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_FETCH_FAILING,
            translation_placeholders={"name": entry.title},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def async_delete_fetch_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Räumt das Abruf-Issue eines entfernten Eintrags ab.

    Sonst bliebe es nach dem Entfernen stehen: Schließen könnte es nur der
    Coordinator des Eintrags, und der läuft nicht mehr.
    """
    ir.async_delete_issue(hass, DOMAIN, fetch_issue_id(entry.entry_id))


def async_delete_legacy_fetch_issue(hass: HomeAssistant) -> None:
    """Entfernt das einmalige Abruf-Issue ohne entry_id aus Version 4.3 und älter.

    Die Issue-Registry ist persistent. Stand das Issue beim Update offen, bliebe
    es sonst dauerhaft stehen, weil seine ID nach dem Umstellen auf Issues je
    Eintrag niemand mehr schließt.
    """
    ir.async_delete_issue(hass, DOMAIN, ISSUE_FETCH_FAILING)
