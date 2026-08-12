# Sensoren und Attribute

> Die Entitäts-IDs beginnen mit dem gewählten Tarif – `smarttimes_…` bzw.
> `smartcontrol_…`. Die Beispiele unten zeigen den smartTIMES-Fall.

## Übersicht

| Sensor / Entität | Beschreibung |
|---|---|
| `sensor.smarttimes_strompreishelfer_arbeitspreis` | **Reiner Arbeitspreis** der aktuell gültigen Tarifzone (ct/kWh) |
| `sensor.smarttimes_strompreishelfer_gesamtpreis_eur_kwh` | **Gesamtpreis inkl. aller variablen Nebenkosten** in **EUR/kWh** (fürs Energie-Dashboard) |
| `binary_sensor.<name>_gunstige_stunde` *(je Untereintrag)* | `on` in den günstigsten Stunden des Tages (nach **Gesamtkosten**); ein Sensor je angelegtem Untereintrag |
| `sensor.smarttimes_strompreishelfer_durchschnittlicher_gesamtpreis_heute` | Durchschnittlicher **Gesamtpreis** heute (ct/kWh) |
| `sensor.smarttimes_strompreishelfer_niedrigster_gesamtpreis_heute` | Günstigster **Gesamtpreis** heute (ct/kWh) |
| `sensor.smarttimes_strompreishelfer_hochster_gesamtpreis_heute` | Teuerster **Gesamtpreis** heute (ct/kWh) |
| `sensor.smarttimes_strompreishelfer_grundgebuhr` | Monatliche Grundgebühr (EUR/Monat) |

Der **Arbeitspreis**-Sensor enthält nur den reinen Energiepreis. Der
**Gesamtpreis**-Sensor (EUR/kWh) addiert Steuern, Abgaben und Netzentgelte
(siehe [Netzentgelte und Nebenkosten](Netzentgelte-und-Nebenkosten)) und ist
die richtige Wahl fürs Energie-Dashboard und zum Schalten. Tageskennzahlen
und der Günstige-Stunde-Sensor beziehen sich auf den **Gesamtpreis**.

## Gesamtpreis-Sensor

| Attribut | Beschreibung |
|---|---|
| `working_price_ct_kwh` | Reiner Arbeitspreis (ct/kWh) |
| `surcharges_ct_kwh` | Nebenkosten je Position, z. B. `{electricity_tax: 0.12, renewable_support: 0.44, grid_usage: 4.04, grid_loss: 0.84}`. Bei **smartCONTROL** zusätzlich `handling_fee` (Abwicklungsgebühr, 1,44 ct/kWh brutto) |
| `surcharges_total_ct_kwh` | Summe aller Nebenkosten (ct/kWh) |
| `total_ct_kwh` | Gesamtpreis (ct/kWh) – entspricht dem Sensorwert × 100 |
| `grid_zone` | Gewähltes Netzgebiet (oder `null`) |
| `snap_active` | `true`, wenn gerade der SNAP gilt |
| `average_today` / `lowest_today` / `highest_today` | Tageskennzahlen (Gesamtpreis, ct/kWh) |
| `next_price` / `next_price_start` | Gesamtpreis und Beginn des nächsten Intervalls |
| `prices_today` / `prices_tomorrow` / `prices` | Vollständige **Gesamtpreis**-Vorschau (`start`, `end`, `price`) |
| `vat_included` / `vat_rate` | Ob brutto gerechnet wird und der USt.-Satz |

## Binary-Sensor „Günstige Stunde“

Dieser Sensor ist `on` während der **günstigsten Stunden des Tages nach
Gesamtkosten** (inkl. Netzentgelte und SNAP). Die Stundenanzahl wird je
Untereintrag über `cheap_hours` konfiguriert.

Die **Auswahllogik** (`cheap_mode`) legt fest, *wie* die günstigen Stunden
bestimmt werden:

- **Günstigste Einzelstunden** (`individual`, Standard): die billigsten
  Intervalle des Tages – sie dürfen über den Tag verteilt (zerteilt) sein.
  Teilen sich mehrere Intervalle denselben Grenzpreis, werden alle davon
  markiert.
- **Zusammenhängender Block** (`consecutive`): das günstigste *lückenlose*
  Zeitfenster aus `cheap_hours` „am Stück“ – für Geräte, deren Laufzeit nicht
  unterbrochen werden darf (Waschmaschine, Geschirrspüler). Grenzt direkt vor
  oder nach dem Block ein Intervall mit demselben Grenzpreis an, wird der
  Block bei Gleichstand zusammenhängend verlängert.

**Last-Glättung (Jitter):** Damit nicht alle Verbraucher gleichzeitig
schalten und Lastspitzen erzeugen, verschiebt jeder Sensor seine
Schaltflanken um einen kleinen, je Sensor stabilen Versatz (Einschalten bis
+10 min). An gleichstandsbedingt verlängerten Blockenden wird das
Ausschalten **rückwärts** gelegt ([−600 s, 0 s]), um nicht in die nächste,
teurere Zone auszugreifen; solche Enden sind in `cheap_windows` mit
`soft_end: true` markiert. Den Versatz zeigt das Attribut
`jitter_offset_seconds`.

| Attribut | Beschreibung |
|---|---|
| `cheap_hours` | Konfigurierte Anzahl günstiger Stunden pro Tag |
| `cheap_mode` | Auswahllogik: `individual` (Einzelstunden) oder `consecutive` (Block) |
| `threshold_ct_kwh` | Höchster Gesamtpreis unter den günstigen Intervallen |
| `current_price_ct_kwh` | Aktueller Gesamtpreis (ct/kWh) |
| `jitter_offset_seconds` | Konstanter Einschalt-Versatz dieses Sensors (Sekunden) |
| `next_cheap_start` | Nächster (gejitterter) Einschaltzeitpunkt |
| `cheap_intervals` | Liste der heutigen günstigen Intervalle (`start`, `end`, `price`) |
| `cheap_windows` | Tatsächliche, gejitterte Schaltfenster heute (`on`, `off`, `soft_end`) |
| `vat_included` | `true`, wenn brutto gerechnet wird |

## Arbeitspreis-Sensor

| Attribut | Beschreibung |
|---|---|
| `tariff` | Gewählter Tarif (`smartTIMES` bzw. `smartCONTROL`) |
| `unit` | Einheit der Preise |
| `interval_minutes` | Länge eines Preisintervalls in Minuten |
| `vat_included` | `true`, wenn die Preise brutto (inkl. USt.) sind |
| `current_start` / `current_end` | Beginn/Ende des aktuellen Preisintervalls |
| `next_price` / `next_price_start` | Arbeitspreis und Beginn des nächsten Intervalls |
| `average_today` / `lowest_today` / `highest_today` | Tageskennzahlen |
| `basic_fee` / `basic_fee_unit` | Aktuelle Grundgebühr und deren Einheit |
| `prices_today` / `prices_tomorrow` / `prices` | Heutige, morgige und vollständige Preisliste |
