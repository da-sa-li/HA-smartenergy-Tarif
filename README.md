# smartENERGY smartTIMES – Home Assistant Integration

Eine [Home Assistant](https://www.home-assistant.io/) Integration für den
dynamischen Stromtarif **smartTIMES** des österreichischen Anbieters
[smartENERGY](https://www.smartenergy.at/). Sie ruft die öffentliche
smartTIMES-Preis-API ab und stellt die viertelstündlichen Tarifpreise als
Sensoren bereit – ideal, um Verbraucher automatisch in günstige Tarifzonen zu
verschieben.

> Diese Integration ist ein inoffizielles Community-Projekt und steht in keiner
> Verbindung zur smartENERGY GmbH.

## Funktionen

- 🔌 **Aktueller Strompreis** der laufenden 15-Minuten-Tarifzone
- 📊 **Tageskennzahlen**: Durchschnitts-, Niedrigst- und Höchstpreis von heute
- 🗓️ **Vollständige Preisvorschau** für heute und morgen als Attribute
  (z. B. für Diagramme oder Automatisierungen)
- 💶 Umschaltbar zwischen **Brutto** (inkl. 20 % USt.) und **Netto**
- ⚙️ Komplette Einrichtung über die **Benutzeroberfläche** (kein YAML, kein API-Schlüssel)

## Datenquelle

Die Integration verwendet die öffentliche smartTIMES-API:

```
https://apis.smartenergy.at/tariffs/v1/Tariffs/smartTIMES/prices
```

Die API liefert pro Zeitintervall (i. d. R. 15 Minuten) den gültigen
Tarifpreis. Laut [Spezifikation](https://www.smartenergy.at/api-schnittstellen-smarttimes):

| Feld         | Bedeutung                                              |
|--------------|--------------------------------------------------------|
| `tariff`     | Tarif (z. B. `smartTIMES`)                             |
| `unit`       | Einheit des Werts von `data:value` (z. B. `ct/kWh`)    |
| `interval`   | Gültigkeit des Preises in Minuten                      |
| `data:date`  | Preis gültig ab (lokales Datum und Uhrzeit)            |
| `data:value` | Preis **inkl. 20 % MwSt.** (dezimal)                   |

> Hinweis: Da die API lokale Zeitstempel liefert, sollte die Zeitzone in Home
> Assistant korrekt auf `Europe/Vienna` eingestellt sein.

## Installation

### Über HACS (empfohlen)

1. HACS öffnen → oben rechts auf die drei Punkte → **Benutzerdefinierte Repositories**.
2. Repository-URL dieses Projekts eintragen, Kategorie **Integration** wählen und hinzufügen.
3. Die Integration **smartENERGY smartTIMES** suchen, herunterladen und Home Assistant neu starten.

### Manuell

1. Den Ordner `custom_components/smartenergy_smarttimes` in das
   `custom_components`-Verzeichnis deiner Home-Assistant-Konfiguration kopieren.
2. Home Assistant neu starten.

## Einrichtung

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen** öffnen.
2. Nach **smartENERGY smartTIMES** suchen.
3. Auswählen, ob die Preise inkl. USt. (brutto) angezeigt werden sollen.

Die Brutto-/Netto-Einstellung lässt sich später jederzeit über
**Konfigurieren** bei der Integration ändern.

## Sensoren

| Sensor                                          | Beschreibung                                |
|-------------------------------------------------|---------------------------------------------|
| `sensor.smartenergy_smarttimes_aktueller_preis` | Preis der aktuell gültigen Tarifzone        |
| `sensor.smartenergy_smarttimes_durchschnittspreis_heute` | Durchschnittspreis des heutigen Tages |
| `sensor.smartenergy_smarttimes_niedrigster_preis_heute`  | Günstigster Preis heute              |
| `sensor.smartenergy_smarttimes_hochster_preis_heute`     | Teuerster Preis heute                |

Alle Sensoren verwenden die Einheit **ct/kWh**.

> Die genauen Entity-IDs können je nach Spracheinstellung abweichen.

### Attribute des Sensors „Aktueller Preis“

Der Sensor `Aktueller Preis` enthält zusätzlich umfangreiche Attribute:

| Attribut            | Beschreibung                                              |
|---------------------|-----------------------------------------------------------|
| `tariff`            | Tarifname laut API                                        |
| `unit`              | Einheit der Preise                                        |
| `interval_minutes`  | Länge einer Tarifzone in Minuten                          |
| `vat_included`      | `true`, wenn die Preise brutto (inkl. USt.) sind          |
| `current_start` / `current_end` | Beginn/Ende der aktuellen Tarifzone           |
| `next_price`        | Preis der nächsten Tarifzone                              |
| `next_price_start`  | Beginn der nächsten Tarifzone                             |
| `average_today` / `lowest_today` / `highest_today` | Tageskennzahlen           |
| `prices_today`      | Liste aller heutigen Preise (`start`, `end`, `price`)     |
| `prices_tomorrow`   | Liste aller morgigen Preise (sofern verfügbar)            |
| `prices`            | Vollständige Preisliste (gut für Diagramme)               |

## Beispiele

### Automatisierung: Gerät bei günstigem Preis einschalten

```yaml
automation:
  - alias: "Boiler bei günstigem Strom einschalten"
    trigger:
      - platform: numeric_state
        entity_id: sensor.smartenergy_smarttimes_aktueller_preis
        below: 10            # ct/kWh
    action:
      - action: switch.turn_on
        target:
          entity_id: switch.boiler
```

### Diagramm mit ApexCharts Card

Mit der [ApexCharts Card](https://github.com/RomRider/apexcharts-card) lässt sich
der Preisverlauf darstellen:

```yaml
type: custom:apexcharts-card
header:
  title: smartTIMES Preise
  show: true
series:
  - entity: sensor.smartenergy_smarttimes_aktueller_preis
    name: Preis
    type: column
    data_generator: |
      return entity.attributes.prices.map(p => {
        return [new Date(p.start).getTime(), p.price];
      });
```

## Hinweise

- Die smartTIMES-API gibt die Preise für den nächsten Tag typischerweise am
  Nachmittag bekannt. Vorher bleibt `prices_tomorrow` leer.
- Die API wird höchstens alle 30 Minuten abgefragt; der Sensorwert für den
  aktuellen Preis wird dennoch minütlich neu berechnet, damit der Wechsel der
  Tarifzone sofort korrekt angezeigt wird.

## Lizenz

Siehe [LICENSE](LICENSE).
