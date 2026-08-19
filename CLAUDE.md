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

- **Zielruntime ist Python 3.14** (Home Assistant 2026.3+). `__init__.py` nutzt PEP-695-Syntax
  (`type SmartTimesConfigEntry = ...`), die ältere Interpreter nicht parsen. Für lokale Checks
  immer `python3.14` verwenden – nicht das voreingestellte `python3` (oft 3.11).
- **Wichtig:** Dabei eine **finale** 3.14-Version (≥ 3.14.2, wie von `homeassistant` gefordert)
  verwenden, **keine** Vorabversion (Alpha/Beta/RC, z. B. `3.14.0rc2`). In Vorabversionen waren
  `typing.ByteString`/`collections.abc.ByteString` zeitweise entfernt, worauf `mashumaro`
  zugreift – das führt beim Laden der pytest-Plugins zu `AttributeError: module 'typing' has no
  attribute 'ByteString'`. Die Entfernung wurde für den finalen 3.14.0-Release zurückgenommen
  (jetzt für 3.17 vorgesehen), betrifft finale 3.14.x-Releases also nicht (siehe Issue #41).

## Befehle

Es gibt **kein** Build-System. Validiert wird über Home-Assistant-Tooling sowie eine
**pytest-Testsuite** (alles in CI, `.github/workflows/validate.yml`):

- **Hassfest** – prüft `manifest.json`, Übersetzungen, Struktur.
- **HACS validation** – prüft HACS-Tauglichkeit (`hacs.json`).
- **pytest** – Unit-Tests der Preis-Mathematik, des Parsers und der Auswahllogik
  (Verzeichnis `tests/`).

Lokal:

```bash
# Syntax aller Module prüfen (3.14 wegen PEP 695)
python3.14 -m py_compile custom_components/smartenergy/*.py

# Sicherstellen, dass es eine finale Version >= 3.14.2 ist (kein Alpha/Beta/RC):
python3.14 -c "import sys; v = sys.version_info; assert (v.major, v.minor, v.micro) >= (3, 14, 2) and v.releaselevel == 'final', sys.version"

# Testsuite (braucht das HA-Test-Harness):
python3.14 -m venv .venv-test && . .venv-test/bin/activate
pip install -r requirements_test.txt
pytest

# Zusätzlich die Live-Tests gegen die echte API (braucht Netzzugang):
pytest -m live --live
```

**Testkonvention:** Die erwarteten Werte (Sollergebnisse) werden **von Hand aus der
Spezifikation** abgeleitet und als Kommentar dokumentiert – nie aus dem zu testenden
Code erzeugt, sonst wäre der Test eine Tautologie. Fixtures (echte API-Antworten) liegen
in `tests/fixtures/`.

**Live-Tests** (`tests/test_api_live.py`, Marker `live`) sind die einzigen Tests, die die
echte smartENERGY-API abrufen. Ohne die Option `--live` werden sie übersprungen – der
normale Lauf bleibt offline und unabhängig vom fremden Server. Sie prüfen **Invarianten**
(lückenloses Viertelstundenraster, Zeitzone, Einheit, aktueller Zeitpunkt abgedeckt,
plausible Werte), **nie** konkrete Preise, und vergleichen die **Feldstruktur** der
Live-Antwort mit den Fixtures – schlägt der Vergleich an, hat die API ihr Format geändert
und die Fixtures gehören aktualisiert. Da das HA-Test-Harness Sockets und DNS pro Test
sperrt, hebt die Fixture `netzwerk_freigeben` diese Sperre gezielt nur für diese Tests auf.

CI läuft bei jedem Push auf `main`, bei jedem PR und manuell (`validate.yml`); die
Live-Tests laufen getrennt davon nächtlich und manuell (`live-api.yml`). Schlägt ein
Live-Lauf fehl, legt der Workflow ein Issue mit dem Label `live-api-fehler` an bzw.
kommentiert das bereits offene – die E-Mail-Benachrichtigung von GitHub ist bei geplanten
Läufen zu unzuverlässig. Das Issue bleibt offen, bis es jemand von Hand schließt.

**Action-Referenzen in den Workflows:** `actions/checkout` und `actions/setup-python` sind auf
einen **Commit-SHA** gepinnt, mit der genauen Version als Kommentar dahinter (`# v7.0.1`) –
daran verankert Dependabot den Ist-Stand und schreibt beim Update SHA *und* Kommentar um.
`home-assistant/actions/hassfest` und `hacs/action` bleiben dagegen bewusst auf `master`/`main`:
Beide werden nicht mehr getaggt, und ein Pin würde ausgerechnet die Validatoren einfrieren, die
die jeweils aktuellen Hassfest-/HACS-Regeln prüfen sollen. Diese Aufteilung beibehalten.

## Architektur – das große Bild

Datenfluss: **`api.py` (Abruf + Parsing) → `coordinator.py` (Caching, Drosselung, gesamte
Preis-Mathematik) → Entitäten (`sensor.py`, `binary_sensor.py`)**.

- **`coordinator.py`** ist das Herzstück. `SmartTimesData` (immutable dataclass) kapselt die
  aufbereiteten Daten und **alle Berechnungen** (aktueller Preis, Tageskennzahlen, Gesamtpreis,
  Günstig-Stunden-Auswahl). Der `SmartTimesCoordinator` rechnet **minütlich** neu (damit der
  Preis beim Intervallwechsel sofort stimmt), drosselt echte **API-Aufrufe aber auf ~1/Tag**
  (`_needs_fetch`): einmal beim Start, täglich ab `NEXT_DAY_PRICES_HOUR` + deterministischer
  Jitter für die Morgen-Preise, plus Retry-Logik. Wiederholungsversuche wachsen dabei
  **exponentiell** (`_retry_delay`: 30 min, dann verdoppelnd bis
  `FETCH_RETRY_MAX_INTERVAL_MINUTES`); ein `Retry-After` des Servers hat Vorrang, sofern es
  länger ist, und ein dauerhaft abweisender Status (4xx außer 408/429 →
  `SmartTimesApiPermanentError`) geht sofort auf das Maximal-Intervall. Unabhängig davon
  deckelt `_fetch_allowed` den Abstand zweier Aufrufe auf `MIN_FETCH_INTERVAL_MINUTES` – ein
  Sicherheitsnetz, das im Normalbetrieb nie greift. Bei fehlgeschlagenem Abruf bleiben die
  gecachten Daten erhalten.

- **Rechen-Cache in `SmartTimesData`** – die einzige bewusste Ausnahme von der Immutabilität:
  vier private `*_cache`-Felder (`repr=False`/`compare=False`) für Tagespreise, Gesamtpreise,
  Günstig-Auswahl und -Blöcke. Nötig, weil jeder Günstig-Stunde-Sensor seine Auswahl minütlich
  in den **synchronen** Properties `is_on`/`extra_state_attributes` zieht – im Event-Loop von
  HA. **Keine Invalidierung nötig:** `_async_update_data` erzeugt je Neuberechnung eine frische
  Instanz, der Cache lebt also genau so lange wie die Daten (eine Minute); alle Sensoren lesen
  dieselbe Instanz, gleich konfigurierte teilen sich das Ergebnis. Der Jitter geht bewusst
  **nicht** in den Schlüssel ein (er wirkt erst auf die fertigen Blöcke). Gecacht werden
  ausschließlich **unveränderliche** Container (`tuple`/`frozenset`), damit ein Aufrufer die
  Daten aller Sensoren nicht aus Versehen verfälschen kann; wer eine veränderbare Fassung
  braucht, baut sie sich selbst (so `_cheap_blocks_spanning`, bevor es Randblöcke
  zusammenfasst).

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
  Bei **Gleichstand** am Schwellwert wird die Auswahl in `individual` erweitert (alle gleich
  teuren Intervalle mitmarkiert); betroffene Blöcke sind als `exceeds_cheap_hours` markiert. Das
  verteuert die kWh nie, verlängert aber die Einschaltdauer – und weil smartTIMES als Zeittarif
  nur **drei** Preisstufen kennt, liefert dort jede Stundenzahl zwischen 0,25 h und 8 h dieselben
  8 Stunden. Wer eine echte Laufzeit-Vorgabe braucht, aktiviert `exact_hours` („Stundenzahl exakt
  einhalten", Vorgabe **aus**, damit Bestandssensoren unverändert bleiben). In `consecutive` wird
  **nie** erweitert und `exact_hours` ist wirkungslos: Eine feste Fensterlänge ist dort der Zweck
  der Betriebsart (Waschmaschine, Geschirrspüler).

- **`jitter.py`** – **Last-Glättung**: jeder Günstig-Stunde-Sensor verschiebt seine Schaltflanken
  um einen **deterministischen, aus der Subentry-ID (SHA-256) abgeleiteten** Versatz, damit nicht
  alle Verbraucher gleichzeitig schalten. Deterministisch (nicht zufällig), damit der Sensor bei
  der minütlichen Neuberechnung nicht flackert. **Beide Flanken wandern nach innen** (Einschalten
  verzögert, Ausschalten vorgezogen, je um denselben Betrag aus *einer* Breite
  `JITTER_SPAN_SECONDS`): Das Fenster verlässt den günstigen Block nie, verschiebt sich als Ganzes
  und ist für jeden Sensor gleich lang. Preis dafür ist ein fester Laufzeitverlust von
  `JITTER_SPAN_SECONDS` je Block – bewusst gewählt, um nie zum teureren Preis zu laufen.
  Zusammenhängende Blöcke werden dafür auch **über die Tagesgrenze** hinweg zusammengefasst
  (`_cheap_blocks_spanning`), sonst risse der Jitter an Mitternacht eine Schaltlücke auf.

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

## Dokumentation

Nutzer-Doku ist zweigeteilt:

- **`README.md`** – kurz und HACS-tauglich: Feature-Pitch, Installation, Einrichtung, knappe
  Sensor-Übersicht. Zielgruppe ist, wer in HACS nach Integrationen sucht.
- **[Github-Wiki](https://github.com/da-sa-li/HA-smartenergy-Tarif/wiki)** – vertiefende Inhalte (Datenschutz, Netzentgelte-und-Nebenkosten,
  Sensoren-und-Attribute, Automatisierungsbeispiele, Fehlerbehebung).

## Release-Prozess

1. Version in **`custom_components/smartenergy/manifest.json`** anheben (SemVer; Minor = neue
   abwärtskompatible Features, Major = Breaking Change wie ein Domain-Wechsel).
2. Mergen nach `main`.
3. Veröffentlichen als **Git-Tag `vX.Y.Z` + GitHub-Release** (HACS zieht Releases darüber). Der
   `version`-Wert im Manifest muss mit dem Release-Tag übereinstimmen.
