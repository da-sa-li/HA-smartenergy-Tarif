# smartENERGY smartTIMES – Home Assistant Integration

Eine [Home Assistant](https://www.home-assistant.io/) Integration für den
dynamischen Stromtarif **smartTIMES** des österreichischen Anbieters
[smartENERGY](https://www.smartenergy.at/). Sie ruft die öffentliche
smartTIMES-Preis-API ab und stellt die viertelstündlichen Tarifpreise als
Sensoren bereit – ideal, um Verbraucher automatisch in günstige Tarifzonen zu
verschieben.

> Diese Integration ist ein Community-Projekt und steht in keiner Verbindung zu smartENERGY oder der Energie Steiermark Kunden GmbH.

## Funktionen

- 🔌 **Arbeitspreis** der laufenden 15-Minuten-Tarifzone (ct/kWh)
- 💶 **Gesamtpreis** in EUR/kWh inkl. Nebenkosten – fürs Energie-Dashboard
- 🧾 **Variable Nebenkosten** automatisch eingerechnet: Elektrizitätsabgabe (mit
  befristeter Senkung bis Ende 2026), Erneuerbaren-Förderbeitrag und
  netzgebietsabhängige **Netzentgelte** inkl. **Sommer-Nieder-Arbeitspreis
  (SNAP)** für Netzebene 7
- 🚦 **Tarifzone** (Off-Peak / Shoulder / Peak) als eigener Status-Sensor
- 📊 **Tageskennzahlen**: Durchschnitts-, Niedrigst- und Höchstpreis von heute
- 💰 **Grundgebühr** (Monatspauschale) als eigener Sensor
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
Tarifpreis sowie die monatliche Grundgebühr. Die Antwort ist wie folgt
aufgebaut:

```json
{
  "energyPrice": {
    "interval": 15,
    "unit": "cent/kWh",
    "values": [
      { "dateTimeFrom": "2026-05-29T00:00:00+02:00", "value": 11.244 },
      { "dateTimeFrom": "2026-05-29T00:15:00+02:00", "value": 11.244 }
    ]
  },
  "basicFee": {
    "unit": "EUR/month",
    "values": [
      { "dateTimeFrom": "2026-05-29T00:00:00+02:00", "value": 2.988 }
    ]
  }
}
```

| Feld                       | Bedeutung                                          |
|----------------------------|----------------------------------------------------|
| `energyPrice.unit`         | Einheit des Energiepreises (z. B. `cent/kWh`)      |
| `energyPrice.interval`     | Gültigkeit des Preises in Minuten                  |
| `…values[].dateTimeFrom`   | Preis gültig ab (lokale Datum/Uhrzeit, mit Offset) |
| `…values[].value`          | Preis **inkl. 20 % MwSt.** (dezimal)               |
| `basicFee`                 | Monatliche Grundgebühr (z. B. `EUR/month`)         |

> Hinweis: Die Integration unterstützt zusätzlich das ältere, in der
> Dokumentation gezeigte Format (`data` / `date`) als Fallback. Da die API
> lokale Zeitstempel liefert, sollte die Zeitzone in Home Assistant korrekt
> auf `Europe/Vienna` eingestellt sein.

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
4. Das **Netzgebiet** wählen (für die Netzentgelte im Gesamtpreis). „Kein
   Netzgebiet“ lässt die Netzentgelte weg.

Beide Einstellungen lassen sich später jederzeit über **Konfigurieren** bei der
Integration ändern.

## Sensoren

| Sensor                                          | Beschreibung                                |
|-------------------------------------------------|---------------------------------------------|
| `sensor.smartenergy_smarttimes_arbeitspreis`    | **Reiner Arbeitspreis** der aktuell gültigen Tarifzone (ct/kWh) |
| `sensor.smartenergy_smarttimes_gesamtpreis_eur_kwh` | **Gesamtpreis inkl. Nebenkosten** in **EUR/kWh** (fürs Energie-Dashboard) |
| `sensor.smartenergy_smarttimes_durchschnittspreis_heute` | Durchschnittlicher Arbeitspreis des heutigen Tages |
| `sensor.smartenergy_smarttimes_niedrigster_preis_heute`  | Günstigster Arbeitspreis heute       |
| `sensor.smartenergy_smarttimes_hochster_preis_heute`     | Teuerster Arbeitspreis heute         |
| `sensor.smartenergy_smarttimes_grundgebuhr`              | Monatliche Grundgebühr (EUR/Monat)   |
| `sensor.smartenergy_smarttimes_tarifzone`               | Aktuelle Tarifzone (Off-Peak/Shoulder/Peak) |

Der **Arbeitspreis**-Sensor (ct/kWh) enthält ausschließlich den Energiepreis und
dient der gut lesbaren Anzeige bzw. dem Vergleich der Tarifzonen. Der
**Gesamtpreis**-Sensor (EUR/kWh) rechnet zusätzlich die Nebenkosten (Steuern und
Abgaben) ein und eignet sich daher fürs Energie-Dashboard. Der
Grundgebühr-Sensor verwendet **EUR/Monat**.

> ℹ️ **Hinweis für Updates von einer älteren Version:** Der frühere Sensor
> `…_aktueller_preis` heißt jetzt `…_arbeitspreis`. Bestehende Installationen
> behalten ihre einmal vergebene Entity-ID für den EUR/kWh-Sensor
> (`…_aktueller_preis_eur_kwh`); inhaltlich enthält dieser nun den Gesamtpreis.
> Passe ggf. Dashboards und Automatisierungen an.

### Energie-Dashboard

> ⚠️ Home Assistant rechnet `ct/kWh` **nicht** automatisch in EUR um – die
> Einheit ist nur ein Anzeige-Text. Das Energie-Dashboard nimmt den Zahlenwert
> des Preissensors direkt als **EUR/kWh**.

Verwende daher fürs Energie-Dashboard den Sensor
`sensor.smartenergy_smarttimes_gesamtpreis_eur_kwh` (Einheit **EUR/kWh**):

Einstellungen → Dashboards → Energie → Netzverbrauch → *Entität mit aktuellem
Preis verwenden* → diesen Sensor auswählen.

Dieser Sensor enthält den Gesamtpreis inkl. Nebenkosten (siehe Abschnitt
[Nebenkosten](#nebenkosten-steuern-und-abgaben)). Damit die Kosten dem
entsprechen, was du tatsächlich zahlst, sollte die Brutto-Einstellung
(inkl. USt.) aktiv sein – das ist die Voreinstellung.

### Nebenkosten (Steuern, Abgaben und Netzentgelte)

In Österreich ist ein großer Teil des Strompreises *nicht* der Arbeitspreis,
sondern Steuern/Abgaben und Netzentgelte. Der **Gesamtpreis**-Sensor
(`…_gesamtpreis_eur_kwh`) rechnet diese Nebenkosten ein.

**Steuern/Abgaben** (bundeseinheitlich, in `surcharges.py`):

| Position                   | Satz (NE 7) | Hinweis                                              |
|----------------------------|-------------|------------------------------------------------------|
| Elektrizitätsabgabe        | 1,5 ct/kWh  | **bis 31.12.2026 auf 0,1 ct/kWh gesenkt** |
| Erneuerbaren-Förderbeitrag | 0,364 ct/kWh | Verordnung 2026; 2022–2024 ausgesetzt, seit 2025 wieder aktiv |

Die Sätze sind als **datierte Tabelle** hinterlegt – jeder Eintrag kennt seinen
Gültigkeitszeitraum. Dadurch greift z. B. ab dem 01.01.2027 automatisch wieder
der Regelsatz der Elektrizitätsabgabe, ohne dass ein Update nötig ist. Der
Erneuerbaren-Förderbeitrag wird jährlich neu festgelegt (Wert Stand 2026).

**Netzentgelte** (netzgebietsabhängig, in `grid_fees.py`, Stand 2026):

Für das gewählte Netzgebiet werden die per-kWh-Netzentgelte auf **Netzebene 7**
mit **Viertelstundenmessung (IME)** berücksichtigt:

- **Netznutzungsentgelt-Arbeitspreis** – normal bzw. reduziert im SNAP-Fenster,
- **Netzverlustentgelt** – konstant.

Der **Sommer-Nieder-Arbeitspreis (SNAP)** senkt den Netz-Arbeitspreis vom
**1. April bis 30. September täglich von 10:00–16:00 Uhr** um 20 %. Voraussetzung
ist die für smartTIMES ohnehin nötige Viertelstundenmessung. Das Attribut
`snap_active` zeigt, ob das Fenster gerade gilt.

> Der **Netznutzungs-Leistungspreis** (Kapazitätsentgelt, €/kW nach Spitzenlast)
> wird **nicht** eingerechnet – er ist keine ct/kWh-Größe und hängt nicht davon
> ab, *wann* eine kWh bezogen wird.

> Hinweis: Die Netzentgelte ändern sich jährlich. Die hinterlegten Werte sind
> Stand 2026 und sollten zum Jahreswechsel aktualisiert werden.

> Alle Nebenkosten werden netto verrechnet; die USt. (20 %) wird – wie in
> Österreich üblich – auf die **Summe** aus Arbeitspreis, Abgaben und
> Netzentgelten angewendet. Sie erscheinen daher nur dann brutto, wenn die
> Brutto-Einstellung aktiv ist.

Der Gesamtpreis-Sensor liefert die Aufschlüsselung zusätzlich als Attribute:

| Attribut                  | Beschreibung                                          |
|---------------------------|-------------------------------------------------------|
| `working_price_ct_kwh`    | Reiner Arbeitspreis (ct/kWh)                          |
| `surcharges_ct_kwh`       | Nebenkosten je Position, z. B. `{electricity_tax: 0.12, renewable_support: 0.44, grid_usage: 4.04, grid_loss: 0.84}` |
| `surcharges_total_ct_kwh` | Summe aller Nebenkosten (ct/kWh)                      |
| `total_ct_kwh`            | Gesamtpreis (ct/kWh) – entspricht dem Sensorwert × 100 |
| `grid_zone`               | Gewähltes Netzgebiet (oder `null`)                    |
| `snap_active`             | `true`, wenn gerade der SNAP gilt                     |
| `vat_included` / `vat_rate` | Ob brutto gerechnet wird und der USt.-Satz          |

### Sensor „Tarifzone"

smartTIMES teilt den Tag in feste Preisstufen ein. Der Sensor leitet die
aktuelle Zone direkt aus den Preisen ab: der **niedrigste** Preis ist
`off_peak`, der **höchste** `peak`, dazwischenliegende Preise `shoulder`.

Als Zustand liefert der Sensor die stabilen Werte `off_peak`, `shoulder` bzw.
`peak` (gut für Automatisierungen); in der Oberfläche werden sie als
*Off-Peak*, *Shoulder* und *Peak* angezeigt. Zusätzliche Attribute:

| Attribut            | Beschreibung                                              |
|---------------------|-----------------------------------------------------------|
| `level_prices`      | Preis je Zone, z. B. `{off_peak: 9.77, shoulder: 11.24, peak: 13.68}` |
| `next_status`       | Nächste abweichende Tarifzone                             |
| `next_status_start` | Zeitpunkt, ab dem die nächste Zone gilt                   |
| `vat_included`      | `true`, wenn die Preise brutto sind                       |

```yaml
automation:
  - alias: "Waschmaschine nur in Off-Peak starten"
    trigger:
      - platform: state
        entity_id: sensor.smartenergy_smarttimes_tarifzone
        to: "off_peak"
    action:
      - action: switch.turn_on
        target:
          entity_id: switch.waschmaschine
```

> Die genauen Entity-IDs können je nach Spracheinstellung abweichen.

### Attribute des Sensors „Arbeitspreis“

Der Sensor `Arbeitspreis` enthält zusätzlich umfangreiche Attribute:

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
| `basic_fee` / `basic_fee_unit` | Aktuelle Grundgebühr und deren Einheit        |
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
        entity_id: sensor.smartenergy_smarttimes_arbeitspreis
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
  - entity: sensor.smartenergy_smarttimes_arbeitspreis
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
