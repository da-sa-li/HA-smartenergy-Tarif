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
- 🌐 **Oberfläche in 11 Sprachen** – Deutsch, Englisch, Bosnisch, Kroatisch,
  Polnisch, Serbisch (kyrillisch & lateinisch), Slowakisch, Slowenisch,
  Tschechisch, Türkisch und Ungarisch

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

### Über HACS (empfohlen)

1. HACS öffnen → **Integrationen**.
2. Nach **smartENERGY Strompreishelfer** suchen, herunterladen und Home Assistant neu starten.

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

> Entitäts-IDs beginnen mit dem gewählten Tarif (`smarttimes_…` bzw. `smartcontrol_…`), unten verkürzt als `…`.

| Sensor                                   | Beschreibung                                        |
|-------------------------------------------|------------------------------------------------------|
| `…_arbeitspreis`                          | Arbeitspreis der aktuellen Tarifzone (ct/kWh)        |
| `…_gesamtpreis_eur_kwh`                   | Gesamtpreis inkl. Nebenkosten (EUR/kWh) – fürs Energie-Dashboard |
| `binary_sensor.<name>_gunstige_stunde`    | Günstige Stunden; ein Sensor je Untereintrag         |
| `…_durchschnittlicher_gesamtpreis_heute`  | Ø-Gesamtpreis heute (ct/kWh)                         |
| `…_niedrigster_gesamtpreis_heute`         | Niedrigster Gesamtpreis heute (ct/kWh)               |
| `…_hochster_gesamtpreis_heute`            | Höchster Gesamtpreis heute (ct/kWh)                  |
| `…_grundgebuhr`                           | Grundgebühr (EUR/Monat)                              |

Der **Gesamtpreis**-Sensor (EUR/kWh) enthält alle Nebenkosten (Steuern,
Abgaben, Netzentgelte inkl. SNAP) und ist die richtige Wahl fürs
Energie-Dashboard und zum Schalten; Tageskennzahlen und der
Günstige-Stunde-Sensor beziehen sich ebenfalls darauf. Details zu den
Nebenkosten und die vollständige Attribut-Referenz stehen im
**[Wiki](https://github.com/da-sa-li/HA-smartenergy-Tarif/wiki)**.

## Lizenz

Siehe [LICENSE](LICENSE.md).

## Ähnliche Projekte
Inspiriert von [EPEX-Spot](https://github.com/mampfes/ha_epex_spot)
