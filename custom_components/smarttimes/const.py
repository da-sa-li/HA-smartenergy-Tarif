"""Konstanten für die smartENERGY smartTIMES Integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "smarttimes"

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
