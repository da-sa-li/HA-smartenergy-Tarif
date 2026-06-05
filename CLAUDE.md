# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Was das ist

Eine **Home-Assistant-Custom-Integration** (über HACS installierbar) für die dynamischen
österreichischen Stromtarife von smartENERGY: **smartTIMES** (zeitabhängig) und **smartCONTROL**
(an den EPEX-Spot-Börsenpreis gekoppelt). Der Tarif wird bei der Einrichtung gewählt. Sie ruft
die öffentliche Tarifpreis-API ab (kein API-Key) und stellt stündliche/viertelstündliche Preise
als Sensoren bereit – inklusive aller variablen Nebenkosten (Steuern, Abgaben, Netzentgelte; bei
smartCONTROL zusätzlich die Abwicklungsgebühr) und eines Binary-Sensors, der die günstigsten
Stunden des Tages markiert.

Der gesamte Code, **alle Kommentare, Docstrings und Commit-Messages sind auf Deutsch** – diese
Konvention beibehalten.

## Sprache & Laufzeit

- **Zielruntime ist Python 3.13** (Home Assistant 2025.3+). `__init__.py` nutzt PEP-695-Syntax
  (`type SmartTimesConfigEntry = ...`), die ältere Interpreter nicht parsen. Für lokale Checks
  immer `python3.13` verwenden – nicht das voreingestellte `python3` (oft 3.11).

## Befehle

Es gibt **kein** Build-System. Validiert wird über Home-Assistant-Tooling sowie eine
**pytest-Testsuite** (alles in CI, `.github/workflows/validate.yml`):

- **Hassfest** – prüft `manifest.json`, Übersetzungen, Struktur.
- **HACS validation** – prüft HACS-Tauglichkeit (`hacs.json`).
- **pytest** – Unit-Tests der Preis-Mathematik, des Parsers und der Auswahllogik
  (Verzeichnis `tests/`).

Lokal:

```bash
# Syntax aller Module prüfen (3.13 wegen PEP 695!)
python3.13 -m py_compile custom_components/smartenergy/*.py

# Testsuite (braucht das HA-Test-Harness):
python3.13 -m venv .venv-test && . .venv-test/bin/activate
pip install -r requirements_test.txt
pytest
```

**Testkonvention:** Die erwarteten Werte (Sollergebnisse) werden **von Hand aus der
Spezifikation** abgeleitet und als Kommentar dokumentiert – nie aus dem zu testenden
Code erzeugt, sonst wäre der Test eine Tautologie. Fixtures (echte API-Antworten) liegen
in `tests/fixtures/`.

CI läuft bei jedem Push auf `main`, bei jedem PR, nächtlich und manuell.

## Architektur – das große Bild

Datenfluss: **`api.py` (Abruf + Parsing) → `coordinator.py` (Caching, Drosselung, gesamte
Preis-Mathematik) → Entitäten (`sensor.py`, `binary_sensor.py`)**.

- **`coordinator.py`** ist das Herzstück. `SmartTimesData` (immutable dataclass) kapselt die
  aufbereiteten Daten und **alle Berechnungen** (aktueller Preis, Tageskennzahlen, Gesamtpreis,
  Günstig-Stunden-Auswahl). Der `SmartTimesCoordinator` rechnet **minütlich** neu (damit der
  Preis beim Intervallwechsel sofort stimmt), drosselt echte **API-Aufrufe aber auf ~1/Tag**
  (`_needs_fetch`): einmal beim Start, täglich ab `NEXT_DAY_PRICES_HOUR` + deterministischer
  Jitter für die Morgen-Preise, plus Retry-Logik. Bei fehlgeschlagenem Abruf bleiben die
  gecachten Daten erhalten.

- **Brutto/Netto & USt.**: Preise werden so gespeichert, wie die API sie liefert – **brutto
  (inkl. 20 % USt.)** in ct/kWh; netto wird bei Bedarf berechnet. **Wichtige Konvention:** Der
  **Gesamtpreis** = Arbeitspreis + Nebenkosten, wobei **netto summiert** und die USt. **einmal
  am Ende** auf die Summe angewendet wird (`all_in_value`, `_apply_vat`). Alle Sätze in
  `surcharges.py`/`grid_fees.py` sind daher **netto** hinterlegt. Die **smartCONTROL-
  Abwicklungsgebühr** (`SMARTCONTROL_HANDLING_FEE_NET`, 1,2 ct/kWh netto) folgt derselben
  Konvention: Sie fließt netto in `_surcharges_net` und erscheint als eigene Breakdown-Position
  `handling_fee` (USt. einmal am Ende → 1,44 ct/kWh brutto).

- **`surcharges.py`** – bundeseinheitliche Steuern/Abgaben (Elektrizitätsabgabe,
  Erneuerbaren-Förderbeitrag) als **deklarative, datierte Tabelle** (`DatedRate` mit
  `since`/`until`). Es gilt der erste passende Satz nach Kalendertag → künftige Satzänderungen
  (z. B. Elektrizitätsabgabe ab 2027) greifen **automatisch ohne Code-Änderung**.

- **`grid_fees.py`** – **netzgebietsabhängige** Netzentgelte (Netzebene 7, Viertelstundenmessung,
  Variante „ohne Leistungsmessung"). Enthält die **SNAP**-Logik (Sommer-Nieder-Arbeitspreis:
  1. Apr–30. Sep, tgl. 10–16 Uhr, −20 % auf den Netz-Arbeitspreis). Werte sind **„Stand 2026"**
  und müssen **jährlich** aktualisiert werden (gilt auch für den Förderbeitrag in
  `surcharges.py`).

- **Günstige-Stunde-Sensoren** (`binary_sensor.py`) werden als **Config Subentries** angelegt –
  einer pro Verbraucher, mit eigener Stundenzahl (`cheap_hours`) und Auswahllogik (`cheap_mode`):
  - `individual`: günstigste **Einzel**-Intervalle (dürfen über den Tag verteilt sein).
  - `consecutive`: ein **zusammenhängender Block** „am Stück".
  Bei **Gleichstand** am Schwellwert wird die Auswahl in beiden Modi erweitert; solche
  Überschuss-Enden sind als `soft_end` markiert.

- **`jitter.py`** – **Last-Glättung**: jeder Günstig-Stunde-Sensor verschiebt seine Schaltflanken
  um einen **deterministischen, aus der Subentry-ID (SHA-256) abgeleiteten** Versatz, damit nicht
  alle Verbraucher gleichzeitig schalten. Deterministisch (nicht zufällig), damit der Sensor bei
  der minütlichen Neuberechnung nicht flackert. Bei `soft_end`-Blöcken wird **rückwärts**
  ausgeschaltet, um nicht in die nächste, teurere Preiszone auszugreifen.

- **`config_flow.py`** – UI-Einrichtung (kein YAML): Haupteintrag (Tarif, USt., Netzgebiet) +
  Options-Flow + Subentry-Flow für die Günstige-Stunde-Sensoren. Der **Tarif** (`CONF_TARIFF`:
  `smarttimes`/`smartcontrol`) bestimmt API-URL, Anzeigenamen und die Abwicklungsgebühr.
  `single_config_entry: true` → nur **eine** Instanz. Schemas müssen frontend-serialisierbar
  bleiben (keine Lambdas/`vol.All` mit Callable; Validierung stattdessen im Flow-Schritt).

## Wichtige Hinweise

- **Zeitzone**: HA sollte auf `Europe/Vienna` stehen. smartTIMES liefert **lokale** Zeitstempel
  **ohne** Offset, smartCONTROL **mit** Offset (`+02:00`); `api.py` (`_parse_date`) übernimmt
  einen vorhandenen Offset und fällt sonst auf `dt_util.DEFAULT_TIME_ZONE` zurück.
- **Domain** ist `smartenergy` (siehe `const.py`/`manifest.json`); das Integrationsverzeichnis
  heißt entsprechend `custom_components/smartenergy/`. Die Tarif-**Schlüssel** `smarttimes`/
  `smartcontrol` (Config-Werte) sind davon unabhängig.
- **Docstring-Konvention**: Module, Klassen, Funktionen und Methoden (inkl. `__init__`) tragen
  knappe deutsche Docstrings; verschachtelte lokale Closures brauchen keine.

## Release-Prozess

1. Version in **`custom_components/smartenergy/manifest.json`** anheben (SemVer; Minor = neue
   abwärtskompatible Features, Major = Breaking Change wie ein Domain-Wechsel).
2. Mergen nach `main`.
3. Veröffentlichen als **Git-Tag `vX.Y.Z` + GitHub-Release** (HACS zieht Releases darüber). Der
   `version`-Wert im Manifest muss mit dem Release-Tag übereinstimmen.
