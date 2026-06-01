# smartTIMES Strompreishelfer – Home Assistant Integration

Eine [Home Assistant](https://www.home-assistant.io/) Integration für den
dynamischen Stromtarif **[smartTIMES](https://www.smartenergy.at/smarttimes)**
von [smartENERGY](https://www.smartenergy.at/), die stündliche Tarifpreise als
Sensoren bereitstellt – ideal zum automatischen Schalten von Verbrauchern in
günstige Tarifzonen.

> Diese Integration ist ein Community-Projekt und steht in keiner Verbindung zu smartENERGY oder der Energie Steiermark Kunden GmbH.

## Funktionen

- 🔌 **Arbeitspreis** der laufenden Tarifzone (ct/kWh)
- 💶 **Gesamtpreis** in EUR/kWh inkl. aller variablen Nebenkosten – fürs Energie-Dashboard
- 🧾 **Variable Nebenkosten** automatisch eingerechnet: Elektrizitätsabgabe,
  Erneuerbaren-Förderbeitrag und netzgebietsabhängige **Netzentgelte** inkl.
  **Sommer-Nieder-Arbeitspreis (SNAP)** für Netzebene 7
- 🟢 **Günstige Stunde** als Binary-Sensor – `on` in den günstigsten Stunden des
  Tages (nach **Gesamtkosten**), ideal zum Schalten von Boiler & Co.
- 📊 **Tageskennzahlen**: Durchschnitts-, Niedrigst- und Höchst-**Gesamtpreis** von heute
- 💰 **Grundgebühr** (Monatspauschale) als eigener Sensor
- 🗓️ **Vollständige Preisvorschau** für heute und morgen als Attribute
- 💶 Umschaltbar zwischen **Brutto** (inkl. 20 % USt.) und **Netto**
- ⚙️ Komplette Einrichtung über die **Benutzeroberfläche** (kein YAML, kein API-Schlüssel)

## Datenquelle

Die Integration verwendet die öffentliche smartTIMES-API
([API-Dokumentation von smartENERGY](https://www.smartenergy.at/api-schnittstellen-smarttimes)):

```
https://apis.smartenergy.at/tariffs/v1/Tariffs/smartTIMES/prices
```

> Da die API lokale Zeitstempel liefert, sollte die Zeitzone in Home Assistant auf `Europe/Vienna` eingestellt sein.

## Installation

### Über HACS (empfohlen)

1. HACS öffnen → oben rechts auf die drei Punkte → **Benutzerdefinierte Repositories**.
2. Repository-URL dieses Projekts eintragen, Kategorie **Integration** wählen und hinzufügen.
3. Die Integration **smartTIMES Strompreishelfer** suchen, herunterladen und Home Assistant neu starten.

### Manuell

1. Den Ordner `custom_components/smarttimes` in das
   `custom_components`-Verzeichnis deiner Home-Assistant-Konfiguration kopieren.
2. Home Assistant neu starten.

## Einrichtung

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen** öffnen.
2. Nach **smartTIMES Strompreishelfer** suchen.
3. Auswählen, ob die Preise inkl. USt. (brutto) angezeigt werden sollen.
4. Das **Netzgebiet** wählen (für die Netzentgelte im Gesamtpreis). „Kein
   Netzgebiet“ lässt die Netzentgelte weg. Das Netzgebiet steht im
   Netzzugangsvertrag des Netzbetreibers.

Diese Einstellungen sind über **Konfigurieren** jederzeit änderbar.

### „Günstige Stunde“-Sensoren anlegen

Die Binary-Sensoren „Günstige Stunde“ werden als **Untereinträge** angelegt – so
kannst du pro Verbraucher einen eigenen Sensor mit eigener Stundenzahl erstellen
(z. B. Boiler 4 h, Wallbox 8 h):

1. Bei der Integration unter **smartTIMES Strompreishelfer** auf **Untereintrag
   hinzufügen** (bzw. **Günstige-Stunde-Sensor hinzufügen**) klicken.
2. Einen **Namen** (z. B. „Boiler“) und die **günstigen Stunden pro Tag** angeben.
3. Beliebig viele weitere Sensoren auf dieselbe Weise hinzufügen.

Jeder Untereintrag erscheint als eigenes Gerät und lässt sich einzeln bearbeiten oder entfernen.

## Sensoren

| Sensor / Entität                                | Beschreibung                                |
|-------------------------------------------------|---------------------------------------------|
| `sensor.smarttimes_strompreishelfer_arbeitspreis`    | **Reiner Arbeitspreis** der aktuell gültigen Tarifzone (ct/kWh) |
| `sensor.smarttimes_strompreishelfer_gesamtpreis_eur_kwh` | **Gesamtpreis inkl. aller variablen Nebenkosten** in **EUR/kWh** (fürs Energie-Dashboard) |
| `binary_sensor.<name>_gunstige_stunde` *(je Untereintrag)* | `on` in den günstigsten Stunden des Tages (nach **Gesamtkosten**); ein Sensor je angelegtem Untereintrag |
| `sensor.smarttimes_strompreishelfer_durchschnittlicher_gesamtpreis_heute` | Durchschnittlicher **Gesamtpreis** heute (ct/kWh) |
| `sensor.smarttimes_strompreishelfer_niedrigster_gesamtpreis_heute`  | Günstigster **Gesamtpreis** heute (ct/kWh) |
| `sensor.smarttimes_strompreishelfer_hochster_gesamtpreis_heute`     | Teuerster **Gesamtpreis** heute (ct/kWh) |
| `sensor.smarttimes_strompreishelfer_grundgebuhr`              | Monatliche Grundgebühr (EUR/Monat)   |

Der **Arbeitspreis**-Sensor enthält nur den reinen Energiepreis. Der
**Gesamtpreis**-Sensor (EUR/kWh) addiert Steuern, Abgaben und Netzentgelte und
ist die richtige Wahl fürs Energie-Dashboard und zum Schalten. Tageskennzahlen
und Günstige-Stunde-Sensor beziehen sich auf den **Gesamtpreis**.

### Nebenkosten (Steuern, Abgaben und Netzentgelte)

Der **Gesamtpreis**-Sensor addiert zum Arbeitspreis die in Österreich
anfallenden Steuern/Abgaben (bundeseinheitlich, in `surcharges.py`) und die
netzgebietsabhängigen Netzentgelte (in `grid_fees.py`, Stand 2026):

| Position                   | Satz (NE 7) | Hinweis                                              |
|----------------------------|-------------|------------------------------------------------------|
| [Elektrizitätsabgabe](https://www.usp.gv.at/themen/steuern-finanzen/weitere-steuern-und-abgaben/verbrauchsteuern_und_energieabgaben/elektrizitaetsabgabe.html) | 1,5 ct/kWh | **bis 31.12.2026 auf 0,1 ct/kWh gesenkt**, ab 01.01.2027 wieder Regelsatz |
| [Erneuerbaren-Förderbeitrag](https://www.e-control.at/konsumenten/oekostrom-foerdersystem) | 0,364 ct/kWh | Verordnung 2026; 2022–2024 ausgesetzt, seit 2025 wieder aktiv |

Für das gewählte Netzgebiet werden die per-kWh-[Netzentgelte](https://www.e-control.at/industrie/strom/strompreis/systemnutzungsentgelte)
auf **Netzebene 7** mit **Viertelstundenmessung (IME)** berücksichtigt:
**Netznutzungsentgelt-Arbeitspreis** (normal bzw. im SNAP-Fenster reduziert) und
konstantes **Netzverlustentgelt**.

Der **[Sommer-Nieder-Arbeitspreis (SNAP)](https://www.e-control.at/sommer-nieder-arbeitspreis)**
senkt den Netz-Arbeitspreis vom **1. April bis 30. September täglich von
10:00–16:00 Uhr** um 20 % (Attribut `snap_active` zeigt, ob er gerade gilt).

> Hinweise: Der **Netznutzungs-Leistungspreis** (Kapazitätsentgelt, €/kW nach
> Spitzenlast) wird **nicht** eingerechnet – er ist keine ct/kWh-Größe. Die
> Netzentgelte ändern sich jährlich (hinterlegt: Stand 2026) und sollten zum
> Jahreswechsel aktualisiert werden. Alle Nebenkosten werden netto verrechnet;
> die USt. (20 %) wird auf die **Summe** angewendet.

Der Gesamtpreis-Sensor liefert die Aufschlüsselung zusätzlich als Attribute:

| Attribut                  | Beschreibung                                          |
|---------------------------|-------------------------------------------------------|
| `working_price_ct_kwh`    | Reiner Arbeitspreis (ct/kWh)                          |
| `surcharges_ct_kwh`       | Nebenkosten je Position, z. B. `{electricity_tax: 0.12, renewable_support: 0.44, grid_usage: 4.04, grid_loss: 0.84}` |
| `surcharges_total_ct_kwh` | Summe aller Nebenkosten (ct/kWh)                      |
| `total_ct_kwh`            | Gesamtpreis (ct/kWh) – entspricht dem Sensorwert × 100 |
| `grid_zone`               | Gewähltes Netzgebiet (oder `null`)                    |
| `snap_active`             | `true`, wenn gerade der SNAP gilt                     |
| `average_today` / `lowest_today` / `highest_today` | Tageskennzahlen (Gesamtpreis, ct/kWh) |
| `next_price` / `next_price_start` | Gesamtpreis und Beginn des nächsten Intervalls |
| `prices_today` / `prices_tomorrow` / `prices` | Vollständige **Gesamtpreis**-Vorschau (`start`, `end`, `price`) |
| `vat_included` / `vat_rate` | Ob brutto gerechnet wird und der USt.-Satz          |

### Binary-Sensor „Günstige Stunde“

Dieser Sensor ist `on` während der **günstigsten Stunden des Tages nach
Gesamtkosten** (inkl. Netzentgelte und SNAP). Die Stundenanzahl wird je
Untereintrag über `cheap_hours` konfiguriert. Teilen sich mehrere Intervalle
denselben Grenzpreis, werden alle davon markiert.

**Last-Glättung (Jitter):** Damit nicht alle Verbraucher gleichzeitig schalten
und Lastspitzen erzeugen, verschiebt jeder Sensor seine Schaltflanken um einen
kleinen, je Sensor stabilen Versatz (Einschalten bis +10 min). An
gleichstandsbedingt verlängerten Blockenden wird das Ausschalten **rückwärts**
gelegt ([−600 s, 0 s]), um nicht in die nächste, teurere Zone auszugreifen;
solche Enden sind in `cheap_windows` mit `soft_end: true` markiert. Den Versatz
zeigt das Attribut `jitter_offset_seconds`.

| Attribut             | Beschreibung                                              |
|----------------------|-----------------------------------------------------------|
| `cheap_hours`        | Konfigurierte Anzahl günstiger Stunden pro Tag           |
| `threshold_ct_kwh`   | Höchster Gesamtpreis unter den günstigen Intervallen     |
| `current_price_ct_kwh` | Aktueller Gesamtpreis (ct/kWh)                         |
| `jitter_offset_seconds` | Konstanter Einschalt-Versatz dieses Sensors (Sekunden) |
| `next_cheap_start`   | Nächster (gejitterter) Einschaltzeitpunkt                |
| `cheap_intervals`    | Liste der heutigen günstigen Intervalle (`start`, `end`, `price`) |
| `cheap_windows`      | Tatsächliche, gejitterte Schaltfenster heute (`on`, `off`, `soft_end`) |
| `vat_included`       | `true`, wenn brutto gerechnet wird                       |

### Attribute des Sensors „Arbeitspreis“

| Attribut            | Beschreibung                                              |
|---------------------|-----------------------------------------------------------|
| `tariff`            | Tarifname laut API                                        |
| `unit`              | Einheit der Preise                                        |
| `interval_minutes`  | Länge eines Preisintervalls in Minuten                    |
| `vat_included`      | `true`, wenn die Preise brutto (inkl. USt.) sind          |
| `current_start` / `current_end` | Beginn/Ende des aktuellen Preisintervalls     |
| `next_price` / `next_price_start` | Arbeitspreis und Beginn des nächsten Intervalls |
| `average_today` / `lowest_today` / `highest_today` | Tageskennzahlen           |
| `basic_fee` / `basic_fee_unit` | Aktuelle Grundgebühr und deren Einheit        |
| `prices_today` / `prices_tomorrow` / `prices` | Heutige, morgige und vollständige Preisliste |

## Lizenz

Siehe [LICENSE](LICENSE).
