"""Diagnose-Plattform für die smartENERGY Integration.

Liefert einen Zustands-Schnappschuss als JSON (über „Diagnose herunterladen"
in der UI abrufbar) – nützlich bei Support-Anfragen, um den exakten Zustand
(Konfiguration, Coordinator-Cache, aktuelles/nächstes Intervall) ohne
Debug-Logging einsehen zu können.

Diagnose-Dateien werden erfahrungsgemäß unverändert an öffentliche Issues
gehängt. Maßstab für den Umfang ist deshalb nicht nur „keine Geheimnisse",
sondern auch „keine personenbezogenen Angaben":

* **Keine Geheimnisse.** Die smartENERGY-API ist öffentlich; es gibt weder
  API-Key noch Zugangsdaten in Konfiguration oder Laufzeitdaten.
* **Keine frei gewählten Namen.** Die Bezeichnung eines „Günstige Stunde"-
  Sensors („Wallbox Garage") benennt in der Praxis Räume oder Personen. Sie
  steht im *Titel* des Untereintrags, nicht in dessen ``data``; aufgenommen
  werden nur Typ und Schaltparameter. Das ist eine zugesagte Eigenschaft und
  wird in ``tests/test_diagnostics.py`` abgesichert.
* **Das Netzgebiet bleibt enthalten.** Es verortet den Anschluss grob nach
  Versorgungsregion, ist für die Nebenkosten-Mathematik aber unverzichtbar –
  ohne es lässt sich ein falscher Gesamtpreis nicht nachvollziehen.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from . import SmartTimesConfigEntry
from .api import MarketPrice
from .grid_fees import is_snap


def _interval_snapshot(price: MarketPrice | None) -> dict[str, Any] | None:
    """Stichprobe eines Preis-Intervalls für die Diagnose (oder ``None``)."""
    if price is None:
        return None
    return {
        "start": price.start,
        "end": price.end,
        "gross_ct_per_kwh": price.gross_ct_per_kwh,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SmartTimesConfigEntry
) -> dict[str, Any]:
    """Baut den Diagnose-Schnappschuss aus Konfiguration und Coordinator-Zustand."""
    coordinator = entry.runtime_data
    data = coordinator.data
    now = dt_util.now()

    grid_zone = data.grid_zone
    current = data.current(now)
    next_price = next((p for p in data.prices if p.start > now), None)

    return {
        "config": {
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "subentries": [
            {"subentry_type": subentry.subentry_type, "data": dict(subentry.data)}
            for subentry in entry.subentries.values()
        ],
        "coordinator": {
            "tariff": data.tariff,
            "interval_minutes": data.interval_minutes,
            "include_vat": data.include_vat,
            "price_count": len(data.prices),
            "grid_zone": (
                {"key": grid_zone.key, "name": grid_zone.name}
                if grid_zone is not None
                else None
            ),
            "snap_active": is_snap(now) if grid_zone is not None else None,
            "handling_fee_net": data.handling_fee_net,
            "last_fetch": coordinator.last_fetch,
            "current_interval": _interval_snapshot(current),
            "next_interval": _interval_snapshot(next_price),
        },
    }
