# smartENERGY Strompreishelfer – Home Assistant Integration

Eine [Home Assistant](https://www.home-assistant.io/) Integration für die
dynamischen Stromtarife **[smartTIMES](https://www.smartenergy.at/smarttimes)**
(zeitabhängig) und **[smartCONTROL](https://www.smartenergy.at/smartcontrol)**
(an den Spot-Börsenpreis gekoppelt) von
[smartENERGY](https://www.smartenergy.at/), die viertelstündliche Tarifpreise als
Sensoren bereitstellt – ideal zum automatischen Schalten von Verbrauchern in
günstige Tarifzonen. Der Tarif wird bei der Einrichtung gewählt.

> Diese Integration ist ein Community-Projekt und steht in keiner Verbindung zu smartENERGY oder der Energie Steiermark Kunden GmbH.

## Funktionen

- ⚡ **Tarifwahl smartTIMES oder smartCONTROL** – bei smartCONTROL wird die
  **Abwicklungsgebühr** (1,2 ct/kWh netto / 1,44 ct/kWh brutto) auf den
  Börsenpreis aufgeschlagen
- 🔌 **Arbeitspreis** der laufenden Tarifzone (ct/kWh)
- 💶 **Gesamtpreis** in EUR/kWh inkl. aller variablen Nebenkosten – fürs Energie-Dashboard
- 🧾 **Variable Nebenkosten** automatisch eingerechnet: Elektrizitätsabgabe,
  Erneuerbaren-Förderbeitrag und netzgebietsabhängige **Netzentgelte** inkl.
  **Sommer-Nieder-Arbeitspreis (SNAP)** für Netzebene 7
- 🟢 **Günstige Stunde** als Binary-Sensor – `on` in den günstigsten Stunden des
  Tages (nach **Gesamtkosten**), ideal zum Schalten von Boiler & Co. Wahlweise
  als **günstigste Einzelstunden** (dürfen über den Tag verteilt sein) oder als
  **zusammenhängender Block „am Stück"** für Geräte mit fester Laufzeit
  (Waschmaschine, Geschirrspüler)
- 📊 **Tageskennzahlen**: Durchschnitts-, Niedrigst- und Höchst-**Gesamtpreis** von heute
- 💰 **Grundgebühr** (Monatspauschale) als eigener Sensor
- 🗓️ **Vollständige Preisvorschau** für heute und morgen als Attribute
- 💶 Umschaltbar zwischen **Brutto** (inkl. 20 % USt.) und **Netto**
- ⚙️ Komplette Einrichtung über die **Benutzeroberfläche** (kein YAML, kein API-Schlüssel)

## Datenquelle

Die Integration verwendet die öffentlichen Preis-APIs von smartENERGY – je nach
gewähltem Tarif (API-Dokumentation:
[smartTIMES](https://www.smartenergy.at/api-schnittstellen-smarttimes),
[smartCONTROL](https://www.smartenergy.at/api-schnittstellen)):

```
smartTIMES:   https://apis.smartenergy.at/tariffs/v1/Tariffs/smartTIMES/prices
smartCONTROL: https://apis.smartenergy.at/market/v1/price
```

> Da die API lokale Zeitstempel liefert, sollte die Zeitzone in Home Assistant auf `Europe/Vienna` eingestellt sein.

## Installation

### Über HACS (empfohlen)

1. HACS öffnen → oben rechts auf die drei Punkte → **Benutzerdefinierte Repositories**.
2. Repository-URL dieses Projekts eintragen, Kategorie **Integration** wählen und hinzufügen.
3. Die Integration **smartENERGY Strompreishelfer** suchen, herunterladen und Home Assistant neu starten.

### Manuell

1. Den Ordner `custom_components/smartenergy` in das
   `custom_components`-Verzeichnis deiner Home-Assistant-Konfiguration kopieren.
2. Home Assistant neu starten.

## Einrichtung

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen** öffnen.
2. Nach **smartENERGY Strompreishelfer** suchen.
3. Das **Tarifmodell** wählen: **smartTIMES** (zeitabhängig) oder **smartCONTROL**
   (an den Börsenpreis gekoppelt, inkl. Abwicklungsgebühr von 1,2 ct/kWh netto /
   1,44 ct/kWh brutto).
4. Auswählen, ob die Preise inkl. USt. (brutto) angezeigt werden sollen.
5. Das **Netzgebiet** wählen (für die Netzentgelte im Gesamtpreis). „Kein
   Netzgebiet“ lässt die Netzentgelte weg. Das Netzgebiet steht im
   Netzzugangsvertrag des Netzbetreibers.

Diese Einstellungen sind über **Konfigurieren** jederzeit änderbar.

### „Günstige Stunde“-Sensoren anlegen

Die Binary-Sensoren „Günstige Stunde“ werden als **Untereinträge** angelegt – so
kannst du pro Verbraucher einen eigenen Sensor mit eigener Stundenzahl erstellen
(z. B. Boiler 4 h, Wallbox 8 h):

1. Bei der Integration unter **smartENERGY Strompreishelfer** auf **Untereintrag
   hinzufügen** (bzw. **Günstige-Stunde-Sensor hinzufügen**) klicken.
2. Einen **Namen** (z. B. „Boiler“) und die **günstigen Stunden pro Tag** angeben.
3. Die **Logik der günstigen Stunden** wählen:
   - **Günstigste Einzelstunden** (Standard): die billigsten Viertelstunden des
     Tages – sie dürfen über den Tag verteilt (zerteilt) sein. Ideal für
     Verbraucher ohne feste Laufzeit (Boiler, Wallbox).
   - **Zusammenhängender Block**: ein einziges günstigstes Zeitfenster „am
     Stück". Wichtig für Geräte mit fester, ununterbrochener Laufzeit
     (Waschmaschine, Geschirrspüler).
4. Beliebig viele weitere Sensoren auf dieselbe Weise hinzufügen.

Jeder Untereintrag erscheint als eigenes Gerät und lässt sich einzeln bearbeiten oder entfernen.

## Entfernen

1. **Einstellungen → Geräte & Dienste** öffnen und die Integration
   **smartENERGY Strompreishelfer** auswählen.
2. Beim Eintrag auf das Drei-Punkte-Menü → **Löschen** klicken. Damit werden die
   Integration, alle Sensoren und die „Günstige Stunde“-Untereinträge (samt
   ihrer Geräte) entfernt.
3. Optional, um auch die Dateien zu entfernen: in **HACS** die Integration
   **smartENERGY Strompreishelfer** öffnen → **Entfernen**. Bei manueller
   Installation stattdessen den Ordner `custom_components/smartenergy` löschen.
   Anschließend Home Assistant neu starten.

Die Integration legt keine Daten außerhalb des Config-Eintrags an; nach dem
Löschen bleiben keine Konfigurationsreste zurück.

## Sensoren

> Die Entitäts-IDs beginnen mit dem gewählten Tarif – `smarttimes_…` bzw.
> `smartcontrol_…`. Die Beispiele unten zeigen den smartTIMES-Fall.

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
| [Erneuerbaren-Förderbeitrag](https://www.e-control.at/konsumenten/oekostrom-foerdersystem) | 0,62 ct/kWh | Verordnung 2026 (Variante ohne Leistungsmessung); 2022–2024 ausgesetzt, seit 2025 wieder aktiv |

Für das gewählte Netzgebiet werden die per-kWh-[Netzentgelte](https://www.e-control.at/industrie/strom/strompreis/systemnutzungsentgelte)
auf **Netzebene 7** mit **Viertelstundenmessung (IME)** in der Tarifvariante
**ohne Leistungsmessung** („nicht gemessene Leistung") berücksichtigt:
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
| `surcharges_ct_kwh`       | Nebenkosten je Position, z. B. `{electricity_tax: 0.12, renewable_support: 0.44, grid_usage: 4.04, grid_loss: 0.84}`. Bei **smartCONTROL** zusätzlich `handling_fee` (Abwicklungsgebühr, 1,44 ct/kWh brutto) |
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
Untereintrag über `cheap_hours` konfiguriert.

Die **Auswahllogik** (`cheap_mode`) legt fest, *wie* die günstigen Stunden
bestimmt werden:

- **Günstigste Einzelstunden** (`individual`, Standard): die billigsten
  Intervalle des Tages – sie dürfen über den Tag verteilt (zerteilt) sein.
  Teilen sich mehrere Intervalle denselben Grenzpreis, werden alle davon
  markiert.
- **Zusammenhängender Block** (`consecutive`): das günstigste *lückenlose*
  Zeitfenster aus `cheap_hours` „am Stück" – für Geräte, deren Laufzeit nicht
  unterbrochen werden darf (Waschmaschine, Geschirrspüler). Grenzt direkt vor
  oder nach dem Block ein Intervall mit demselben Grenzpreis an, wird der Block
  bei Gleichstand zusammenhängend verlängert.

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
| `cheap_mode`         | Auswahllogik: `individual` (Einzelstunden) oder `consecutive` (Block) |
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
| `tariff`            | Gewählter Tarif (`smartTIMES` bzw. `smartCONTROL`)        |
| `unit`              | Einheit der Preise                                        |
| `interval_minutes`  | Länge eines Preisintervalls in Minuten                    |
| `vat_included`      | `true`, wenn die Preise brutto (inkl. USt.) sind          |
| `current_start` / `current_end` | Beginn/Ende des aktuellen Preisintervalls     |
| `next_price` / `next_price_start` | Arbeitspreis und Beginn des nächsten Intervalls |
| `average_today` / `lowest_today` / `highest_today` | Tageskennzahlen           |
| `basic_fee` / `basic_fee_unit` | Aktuelle Grundgebühr und deren Einheit        |
| `prices_today` / `prices_tomorrow` / `prices` | Heutige, morgige und vollständige Preisliste |

## Automatisierungs-Beispiele

### Verbraucher in günstigen Stunden schalten

Den „Günstige Stunde“-Binary-Sensor als Auslöser nutzen, um einen Verbraucher
(z. B. Boiler oder Wallbox) genau dann ein- bzw. auszuschalten, wenn der Sensor
nach `on` bzw. `off` wechselt:

```yaml
automation:
  - trigger:
      - platform: state
        entity_id: binary_sensor.boiler_gunstige_stunde
    action:
      - service: "switch.turn_{{ 'on' if trigger.to_state.state == 'on' else 'off' }}"
        target: { entity_id: switch.boiler }
```

> Den Entitäts-Namen (`binary_sensor.<name>_gunstige_stunde`) an den eigenen
> Untereintrag anpassen. Die Last-Glättung (Jitter) verschiebt die Schaltflanken
> automatisch um einen kleinen, je Sensor stabilen Versatz – die Automatisierung
> muss nichts weiter berücksichtigen.

### Gesamtpreis im Energie-Dashboard hinterlegen

Der `…_gesamtpreis_eur_kwh`-Sensor liefert den Preis bereits in **EUR/kWh** inkl.
aller variablen Nebenkosten und eignet sich damit direkt als Preis-Entität fürs
Energie-Dashboard:

1. **Einstellungen → Dashboards → Energie** öffnen.
2. Beim **Netzstromverbrauch** die verbrauchsmessende Entität wählen und unter
   **Kosten** die Option **Entität mit aktuellem Preis verwenden** aktivieren.
3. Als Preis-Entität `sensor.smarttimes_strompreishelfer_gesamtpreis_eur_kwh`
   (bzw. `smartcontrol_…`) auswählen.

So rechnet Home Assistant die tatsächlichen Stromkosten dynamisch mit dem
jeweils gültigen Gesamtpreis ab.

## Fehlerbehebung

### Preiszeiten oder SNAP-Fenster verrutschen

Home Assistant muss auf die Zeitzone **`Europe/Vienna`** eingestellt sein
(**Einstellungen → System → Allgemein → Zeitzone**). smartTIMES liefert lokale
Zeitstempel ohne Offset – steht HA auf einer anderen Zeitzone, verschieben sich
die Preisintervalle und das **SNAP-Fenster** (10:00–16:00 Uhr) entsprechend.

### Keine Preise / Sensor zeigt `unknown`

Die Integration ruft die Preis-API nur etwa **einmal täglich** ab (die
Morgen-Preise ab ca. 14 Uhr) und rechnet die Anzeige minütlich aus dem **Cache**
neu. Ist die API beim Abruf kurz nicht erreichbar, bleiben die zuletzt
gecachten Preise erhalten und es greift eine **Retry-Logik**, die den Abruf
automatisch wiederholt.

- **Direkt nach der Einrichtung** kann es einen Moment dauern, bis der erste
  erfolgreiche Abruf erfolgt ist – danach füllt sich der Sensor.
- **Bleibt der Sensor länger `unknown`**, die Internet-Verbindung prüfen und ggf.
  Home Assistant neu starten. Details stehen im HA-Protokoll
  (**Einstellungen → System → Protokolle**).

### Falsche Gesamtkosten

Stimmt der Gesamtpreis nicht mit der Abrechnung überein, ist meist das
**Netzgebiet** nicht oder falsch gewählt – davon hängen die Netzentgelte ab. Das
korrekte Netzgebiet steht im **Netzzugangsvertrag** des Netzbetreibers und lässt
sich über **Konfigurieren** jederzeit anpassen. „Kein Netzgebiet“ lässt die
Netzentgelte ganz weg, der Gesamtpreis fällt dann zu niedrig aus.

## Lizenz

Siehe [LICENSE](LICENSE.md).

## Ähnliche Projekte
Inspiriert von [EPEX-Spot](https://github.com/mampfes/ha_epex_spot)
