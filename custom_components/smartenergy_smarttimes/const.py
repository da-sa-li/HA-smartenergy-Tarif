"""Konstanten für die smartENERGY smartTIMES Integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "smartenergy_smarttimes"

# Öffentliche smartTIMES-Tarifpreis-API von smartENERGY (kein API-Key nötig).
# Doku: https://www.smartenergy.at/api-schnittstellen-smarttimes
API_URL: Final = "https://apis.smartenergy.at/tariffs/v1/Tariffs/smartTIMES/prices"
API_TIMEOUT: Final = 30

# Die API liefert Bruttopreise inkl. 20 % österreichischer Umsatzsteuer.
VAT_RATE: Final = 0.20

# Anzeige-Einheiten.
UNIT_CT_PER_KWH: Final = "ct/kWh"
UNIT_EUR_PER_KWH: Final = "EUR/kWh"
UNIT_EUR_PER_MONTH: Final = "EUR/Monat"

# Tarifzonen-Status (stabile Werte für Automatisierungen).
STATUS_OFF_PEAK: Final = "off_peak"
STATUS_SHOULDER: Final = "shoulder"
STATUS_PEAK: Final = "peak"
TARIFF_STATUSES: Final = [STATUS_OFF_PEAK, STATUS_SHOULDER, STATUS_PEAK]

# Konfigurationsoptionen
CONF_INCLUDE_VAT: Final = "include_vat"
DEFAULT_INCLUDE_VAT: Final = True

# Auswahl des Netzgebiets für die Netzentgelte. "none" = nicht einrechnen.
CONF_GRID_ZONE: Final = "grid_zone"
GRID_ZONE_NONE: Final = "none"
DEFAULT_GRID_ZONE: Final = GRID_ZONE_NONE

# Wie oft der Koordinator die Entitäten neu berechnet (aktueller Preis).
# Die eigentlichen API-Aufrufe werden intern stärker gedrosselt
# (siehe MIN_FETCH_INTERVAL), damit die API nicht unnötig belastet wird.
RECALC_INTERVAL_MINUTES: Final = 1
MIN_FETCH_INTERVAL_MINUTES: Final = 30
