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

# Anzeige-Einheit der Preise.
UNIT_CT_PER_KWH: Final = "ct/kWh"

# Konfigurationsoptionen
CONF_INCLUDE_VAT: Final = "include_vat"
DEFAULT_INCLUDE_VAT: Final = True

# Wie oft der Koordinator die Entitäten neu berechnet (aktueller Preis).
# Die eigentlichen API-Aufrufe werden intern stärker gedrosselt
# (siehe MIN_FETCH_INTERVAL), damit die API nicht unnötig belastet wird.
RECALC_INTERVAL_MINUTES: Final = 1
MIN_FETCH_INTERVAL_MINUTES: Final = 30
