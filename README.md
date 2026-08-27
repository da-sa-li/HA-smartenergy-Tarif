# smartENERGY Strompreishelfer – Home Assistant Integration

Eine [Home Assistant](https://www.home-assistant.io/) Integration für die
dynamischen Stromtarife **[smartTIMES](https://www.smartenergy.at/smarttimes)**
(drei Preiszonen mit monatlicher Preisanpassung) und **[smartCONTROL](https://www.smartenergy.at/smartcontrol)**
(an den Spot-Börsenpreis gekoppelt) von
[smartENERGY](https://www.smartenergy.at/), die viertelstündliche Tarifpreise als
Sensoren bereitstellt – ideal zum automatischen Schalten von Verbrauchern in
günstige Tarifzonen. Der Tarif wird bei der Einrichtung gewählt.

> [!NOTE]
> Diese Integration ist ein Community-Projekt und steht in keiner Verbindung zu smartENERGY oder der Energie Steiermark Kunden GmbH.

## Funktionen

- ⚡ **Tarifwahl smartTIMES oder smartCONTROL** – bei smartCONTROL wird die
  **Abwicklungsgebühr** (1,2 ct/kWh netto / 1,44 ct/kWh brutto) auf den
  Börsenpreis aufgeschlagen
- 🔌 **Arbeitspreis** der laufenden Tarifzone (EUR/kWh)
- 💶 **Gesamtpreis** in EUR/kWh inkl. aller variablen Nebenkosten – fürs Energie-Dashboard
- 📐 **Einheitlich EUR/kWh** für alle Preissensoren – direkt vergleichbar,
  ohne Template-Sensor
- 🧾 **Variable Nebenkosten** automatisch eingerechnet: Elektrizitätsabgabe,
  Erneuerbaren-Förderbeitrag und netzgebietsabhängige **Netzentgelte** inkl.
  **Sommer-Nieder-Arbeitspreis (SNAP)** für Netzebene 7
- 🟢 **Günstige Stunde** als Binary-Sensor – `on` in den günstigsten Stunden des
  Tages (nach **Gesamtkosten**), ideal zum Schalten von Boiler & Co. Wahlweise
  als **günstigste Einzelstunden** (dürfen über den Tag verteilt sein) oder als
  **zusammenhängender Block „am Stück“** für Geräte mit fester Laufzeit
  (Waschmaschine, Geschirrspüler)
- 📊 **Tageskennzahlen**: Durchschnitts-, Niedrigst- und Höchst-**Gesamtpreis** von heute
- 💰 **Grundgebühr** (Monatspauschale) als eigener Sensor
- 🗓️ **Vollständige Preisvorschau** für heute und morgen als Attribute
- 💶 Umschaltbar zwischen **Brutto** (inkl. 20 % USt.) und **Netto**
- ⚙️ Komplette Einrichtung über die **Benutzeroberfläche** (kein YAML, kein API-Schlüssel)

> [!TIP]
> 📖 Ausführliche Dokumentation (Datenschutz, Netzentgelte, vollständige
> Sensor-Attribute, Automatisierungsbeispiele, Fehlerbehebung) steht im
> **[Wiki](https://github.com/da-sa-li/HA-smartenergy-Tarif/wiki)**.

## Datenquelle

Die Integration verwendet die öffentlichen Preis-APIs von smartENERGY – je nach
gewähltem Tarif (API-Dokumentation:
[smartTIMES](https://www.smartenergy.at/api-schnittstellen-smarttimes),
[smartCONTROL](https://www.smartenergy.at/api-schnittstellen)):

```
smartTIMES:   https://apis.smartenergy.at/tariffs/v1/Tariffs/smartTIMES/prices
smartCONTROL: https://apis.smartenergy.at/market/v1/price
```

> [!WARNING]
> Da die API lokale Zeitstempel liefert, sollte die Zeitzone in Home Assistant auf `Europe/Vienna` eingestellt sein.

## Installation

> [!IMPORTANT]
> Ab Version 4.1.0 wird **Home Assistant 2026.8** oder neuer vorausgesetzt. Wer
> eine ältere Reihe fährt, bekommt die neue Fassung über HACS nicht angeboten;
> die installierte läuft unverändert weiter.

### Über HACS (empfohlen)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=da-sa-li&repository=HA-smartenergy-Tarif)

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=smartenergy)

1. HACS öffnen → **Integrationen**.
2. Nach **smartENERGY Strompreishelfer** suchen, herunterladen und Home Assistant neu starten.

### Manuell

1. Den Ordner `custom_components/smartenergy` in das
   `custom_components`-Verzeichnis deiner Home-Assistant-Konfiguration kopieren.
2. Home Assistant neu starten.

## Einrichtung

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen** öffnen.
2. Nach **smartENERGY Strompreishelfer** suchen.
3. Das **Tarifmodell** wählen: **smartTIMES** (zeitabhängig) oder **smartCONTROL**.
4. Auswählen, ob die Preise inkl. USt. (brutto) angezeigt werden sollen.
5. Das **Netzgebiet** wählen (für die Netzentgelte im Gesamtpreis). „Kein
   Netzgebiet“ lässt die Netzentgelte weg. Das Netzgebiet steht im
   Netzzugangsvertrag des Netzbetreibers.

Diese Einstellungen sind über **Konfigurieren** jederzeit änderbar.

> [!TIP]
> Die Preise werden bewusst nur etwa **einmal täglich** abgerufen und minütlich
> aus dem Cache neu berechnet. Wer einen sofortigen Abruf braucht, wählt beim
> Eintrag im **Drei-Punkte-Menü → Neu laden**: Das baut die Integration neu auf
> und holt die Preise unmittelbar. Einen Dienst dafür gibt es absichtlich nicht –
> er müsste genau die Drosselung umgehen, die die kostenlos bereitgestellte API
> schont.

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
     Stück“. Wichtig für Geräte mit fester, ununterbrochener Laufzeit
     (Waschmaschine, Geschirrspüler).
4. **Stundenzahl exakt einhalten** (Vorgabe: **ein**) entscheidet, was bei
   Preisgleichstand passiert. Eingeschaltet liefert der Sensor exakt die
   eingestellte Stundenzahl. Ausgeschaltet werden alle Zeiten mitmarkiert, die
   genau so viel kosten wie die teuerste ausgewählte – der Sensor ist dann
   **länger an als eingestellt**, aber nie zu einem höheren Preis. Ausschalten
   lohnt für selbstbegrenzende Verbraucher (Boiler mit Thermostat, Wallbox mit
   Ziel-Ladestand), die eine Gelegenheit zum selben Preis mitnehmen können.
   Bei **smartTIMES** ist der Unterschied groß: Der Tarif kennt nur drei
   Preisstufen zu je 8 Stunden, ausgeschaltet liefert dort jede Einstellung
   zwischen 0,25 h und 8 h dieselben 8 Stunden. Die Option wirkt nur bei
   „Günstigste Einzelstunden“; beim zusammenhängenden Block gilt die
   eingestellte Länge ohnehin immer exakt.
5. Beliebig viele weitere Sensoren auf dieselbe Weise hinzufügen.

Jeder Untereintrag erscheint als eigenes Gerät und lässt sich einzeln bearbeiten oder entfernen.

> [!NOTE]
> **Der Sensor schaltet absichtlich nicht auf die Sekunde genau.** Damit nicht
> alle Haushalte gleichzeitig eine große Last zuschalten, verschiebt jeder
> Sensor seine Schaltflanken um bis zu 10 Minuten – **nach innen**: eingeschaltet
> wird etwas später, ausgeschaltet entsprechend früher. Der Versatz ist aus der
> ID des Untereintrags abgeleitet, also je Sensor konstant, und steht im Attribut
> `jitter_offset_seconds`. Das Fenster verlässt den günstigen Block dadurch nie –
> der Verbraucher läuft nie zum teureren Preis. Preis dafür sind 10 Minuten
> Laufzeit je Block.

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

> Entitäts-IDs beginnen mit dem gewählten Tarif (`smarttimes_…` bzw. `smartcontrol_…`), unten verkürzt als `…`.

| Sensor                                   | Beschreibung                                        |
|-------------------------------------------|------------------------------------------------------|
| `…_arbeitspreis`                          | Arbeitspreis der aktuellen Tarifzone (EUR/kWh)       |
| `…_gesamtpreis`                           | Gesamtpreis inkl. Nebenkosten (EUR/kWh) – fürs Energie-Dashboard |
| `binary_sensor.<name>_gunstige_stunde`    | Günstige Stunden; ein Sensor je Untereintrag         |
| `sensor.<name>_nachster_gunstiger_start`  | Beginn des nächsten günstigen Fensters; ein Sensor je Untereintrag |
| `…_durchschnittlicher_gesamtpreis_heute`  | Ø-Gesamtpreis heute (EUR/kWh)                        |
| `…_niedrigster_gesamtpreis_heute`         | Niedrigster Gesamtpreis heute (EUR/kWh)              |
| `…_hochster_gesamtpreis_heute`            | Höchster Gesamtpreis heute (EUR/kWh)                 |
| `…_preisrang_heute`                       | Der wievielt-günstigste ist das laufende Intervall heute (1 = günstigstes) |
| `…_preisquantil_heute`                    | Dasselbe normiert auf 0–100 % (0 % = günstigstes)    |
| `…_grundgebuhr`                           | Grundgebühr (EUR/month)                              |
| `binary_sensor.…_preise_fur_morgen_verfugbar` | Ob die Preise für den Folgetag vorliegen (Diagnose) |

Der **Gesamtpreis**-Sensor enthält alle Nebenkosten (Steuern, Abgaben,
Netzentgelte inkl. SNAP) und ist die richtige Wahl fürs Energie-Dashboard und
zum Schalten; Tageskennzahlen und der Günstige-Stunde-Sensor beziehen sich
ebenfalls darauf.

**Preisrang** und **Preisquantil** ordnen den laufenden Preis in den heutigen
Tag ein – die Frage „ist es gerade günstig?“ beantwortet sich damit ohne eigene
Vorlage. Beide zeigen in dieselbe Richtung: Rang 1 und 0 % gehören zum
günstigsten Intervall des Tages. Das Quantil ist der handlichere Wert, weil es
unabhängig davon ist, ob ein Tag 24 oder 96 Werte hat – „unter 25 %“ heißt
immer „im günstigsten Viertel“. Näheres im
[Wiki](https://github.com/da-sa-li/HA-smartenergy-Tarif/wiki/Sensoren-und-Attribute).

> [!NOTE]
> Alle Preissensoren liefern **EUR/kWh**. Die API rechnet in ct/kWh; umgerechnet
> wird erst beim Sensor. Der Einheiten-String der API steht im Attribut
> `source_unit`.
>
> Beim Update von einer Version vor 4.0 wird der Gesamtpreis-Sensor von
> `…_gesamtpreis_eur_kwh` auf `…_gesamtpreis` umbenannt, damit alle
> Installationen dieselbe Entity-ID tragen. **Automatisierungen, Vorlagen und
> Dashboards, die die alte ID verwenden, müssen angepasst werden.**

> [!TIP]
> **Nächster günstiger Start** ist ein Zeitstempel-Sensor und lässt sich damit
> direkt als `at:` eines `time`-Triggers verwenden – auch mit Vorlauf, etwa
> „30 Minuten vorher vorheizen“. Als Attribut allein ginge das nicht.
> **Preise für morgen verfügbar** schaltet auf `on`, sobald die Preise des
> Folgetags eingetroffen sind, und ist der passende Auslöser, um den Tagesplan
> neu zu rechnen. Beispiele stehen im Wiki unter
> [Automatisierungsbeispiele](https://github.com/da-sa-li/HA-smartenergy-Tarif/wiki/Automatisierungsbeispiele).

Details zu den Nebenkosten und die vollständige Attribut-Referenz stehen im
**[Wiki](https://github.com/da-sa-li/HA-smartenergy-Tarif/wiki)**.

## Lizenz

Siehe [LICENSE](LICENSE.md).

## Ähnliche Projekte
Inspiriert von [EPEX-Spot](https://github.com/mampfes/ha_epex_spot)
