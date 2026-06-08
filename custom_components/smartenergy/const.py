"""Konstanten für die smartENERGY smartTIMES Integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "smartenergy"

# Öffentliche smartTIMES-Tarifpreis-API von smartENERGY (kein API-Key nötig).
# Doku: https://www.smartenergy.at/api-schnittstellen-smarttimes
API_URL: Final = "https://apis.smartenergy.at/tariffs/v1/Tariffs/smartTIMES/prices"
API_TIMEOUT: Final = 30

# smartCONTROL koppelt an den EPEX-Spot-Börsenpreis und nutzt eine andere API.
# Sie liefert das Preisarray flach (data/date/value) mit Zeitzonen-Offset; der
# Parser in api.py verarbeitet beide Formate ohne Sonderfall.
MARKET_API_URL: Final = "https://apis.smartenergy.at/market/v1/price"

# Auswahl des Tarifmodells (UI, kein YAML).
CONF_TARIFF: Final = "tariff"
TARIFF_SMARTTIMES: Final = "smarttimes"
TARIFF_SMARTCONTROL: Final = "smartcontrol"
DEFAULT_TARIFF: Final = TARIFF_SMARTTIMES

# Anzeigename je Tarif (Gerätename, Modell, Titel). Stammt aus der Nutzer-Auswahl,
# NICHT aus der API – smartCONTROL liefert dort den Börsen-Tarif "EPEXSPOTAT".
TARIFF_DISPLAY_NAMES: Final[dict[str, str]] = {
    TARIFF_SMARTTIMES: "smartTIMES",
    TARIFF_SMARTCONTROL: "smartCONTROL",
}

# API-URL je Tarif.
TARIFF_API_URLS: Final[dict[str, str]] = {
    TARIFF_SMARTTIMES: API_URL,
    TARIFF_SMARTCONTROL: MARKET_API_URL,
}

# Abwicklungsgebühr bei smartCONTROL: 1,2 ct/kWh NETTO (= 1,44 ct/kWh brutto inkl.
# 20 % USt.). Wird wie alle Nebenkosten netto hinterlegt; die USt. wird erst am
# Ende auf die Summe angewendet (siehe coordinator.py). Nur bei smartCONTROL > 0.
SMARTCONTROL_HANDLING_FEE_NET: Final = 1.2

# API-Doku-Seiten von smartENERGY (Geräte-Link „configuration_url").
SMARTTIMES_DOC_URL: Final = "https://www.smartenergy.at/api-schnittstellen-smarttimes"
SMARTENERGY_DOC_URL: Final = "https://www.smartenergy.at/api-schnittstellen"

# Die API liefert Bruttopreise inkl. 20 % österreichischer Umsatzsteuer.
VAT_RATE: Final = 0.20

# Anzeige-Einheiten.
UNIT_CT_PER_KWH: Final = "ct/kWh"
UNIT_EUR_PER_KWH: Final = "EUR/kWh"
UNIT_EUR_PER_MONTH: Final = "EUR/Monat"

# Konfigurationsoptionen
CONF_INCLUDE_VAT: Final = "include_vat"
DEFAULT_INCLUDE_VAT: Final = True

# Auswahl des Netzgebiets für die Netzentgelte. "none" = nicht einrechnen.
CONF_GRID_ZONE: Final = "grid_zone"
GRID_ZONE_NONE: Final = "none"
DEFAULT_GRID_ZONE: Final = GRID_ZONE_NONE

# Anzahl der günstigsten Stunden pro Tag (nach Gesamtkosten), die ein
# Binary-Sensor "Günstige Stunde" als günstig markiert. Wird je Untereintrag
# (Subentry) konfiguriert – pro Verbraucher ein eigener Sensor mit eigener
# Stundenzahl.
CONF_CHEAP_HOURS: Final = "cheap_hours"
DEFAULT_CHEAP_HOURS: Final = 4.0

# Auswahllogik der günstigen Stunden je "Günstige Stunde"-Sensor.
#
# - "individual" (Standard): die günstigsten *Einzel*-Intervalle des Tages.
#   Sie dürfen über den Tag verteilt (zerteilt) sein – ideal für Verbraucher
#   ohne feste Laufzeit (z. B. Boiler, Wallbox).
# - "consecutive": ein einziger *zusammenhängender* Block "am Stück" – wichtig
#   für Geräte mit fester Laufzeit, die nicht unterbrochen werden dürfen
#   (z. B. Waschmaschine, Geschirrspüler).
CONF_CHEAP_MODE: Final = "cheap_mode"
CHEAP_MODE_INDIVIDUAL: Final = "individual"
CHEAP_MODE_CONSECUTIVE: Final = "consecutive"
DEFAULT_CHEAP_MODE: Final = CHEAP_MODE_INDIVIDUAL

# Untereintrag-Typ (Config Subentry) für einen "Günstige Stunde"-Sensor.
SUBENTRY_TYPE_CHEAP_HOUR: Final = "cheap_hour"

# Last-Glättung ("Jitter") für die "Günstige Stunde"-Sensoren.
#
# Würden hunderte Verbraucher exakt zur selben Sekunde (z. B. 10:00:00) eine
# große Last schalten, entstünde eine Lastspitze, die das Stromnetz belastet.
# Jeder Sensor verschiebt seine Schaltflanken deshalb um einen kleinen,
# deterministisch aus der Subentry-ID abgeleiteten Versatz (siehe jitter.py).
#
# - Einschalten: Verzögerung gleichverteilt in [0, JITTER_ON_MAX_SECONDS]; es
#   wird nie *vor* Beginn des günstigen Blocks eingeschaltet.
# - Ausschalten: symmetrischer Versatz in [-JITTER_OFF_SPAN_SECONDS/2,
#   +JITTER_OFF_SPAN_SECONDS/2] um die Blockgrenze – der Erwartungswert fällt
#   damit genau auf die volle (Block-)Grenze.
JITTER_ON_MAX_SECONDS: Final = 600
JITTER_OFF_SPAN_SECONDS: Final = 600

# Wie oft der Koordinator die Entitäten neu berechnet (aktueller Preis).
# Die eigentlichen API-Aufrufe werden intern stark gedrosselt (siehe unten),
# damit die API nicht unnötig belastet wird.
RECALC_INTERVAL_MINUTES: Final = 1

# Ab dieser Stunde (Lokalzeit) enthält die API-Antwort auch Preise für den
# nächsten Tag.
NEXT_DAY_PRICES_HOUR: Final = 17

# Wartezeit zwischen Wiederholungsversuchen: greift, wenn der Abruf ab
# NEXT_DAY_PRICES_HOUR noch keine Morgen-Preise liefert oder ein Abruf
# fehlgeschlagen ist (und bereits Daten vorhanden sind).
FETCH_RETRY_INTERVAL_MINUTES: Final = 30

# Maximaler Jitter für den täglichen Abruf (Gleichverteilung
# 0 .. FETCH_JITTER_MINUTES-1 Minuten, deterministisch aus der
# Config-Entry-ID).  Verteilt die Abrufe verschiedener HA-Instanzen auf ein
# 20-Minuten-Fenster nach NEXT_DAY_PRICES_HOUR.
FETCH_JITTER_MINUTES: Final = 20

# Kalenderjahr, für das die in `grid_fees.py` (Netzentgelte) und
# `surcharges.py` (Erneuerbaren-Förderbeitrag) hinterlegten "Stand <Jahr>"-
# Werte gelten. Muss zusammen mit diesen Werten jährlich aktualisiert werden;
# `repairs.py` meldet andernfalls ein Repair-Issue, sobald das laufende Jahr
# diesen Wert überschreitet (siehe `async_check_tariff_data_year`).
TARIFF_DATA_YEAR: Final = 2026

# Ab dieser Dauer ohne erfolgreichen Preis-Abruf meldet `repairs.py` ein
# Repair-Issue ("dauerhafter Abruf-Fehler"): Der Coordinator behält den Cache
# bewusst (siehe `_async_update_data`), aber Nutzer sollen erfahren, dass die
# angezeigten Preise inzwischen veraltet sein könnten. Schließt sich
# automatisch, sobald wieder ein Abruf gelingt.
FETCH_FAILURE_REPAIR_HOURS: Final = 36


def documentation_url(tariff_display_name: str) -> str:
    """Doku-Link je Tarif (smartTIMES hat eine eigene API-Doku-Seite)."""
    if tariff_display_name == TARIFF_DISPLAY_NAMES[TARIFF_SMARTTIMES]:
        return SMARTTIMES_DOC_URL
    return SMARTENERGY_DOC_URL
