# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Was das ist

Eine **Home-Assistant-Custom-Integration** (über HACS installierbar) für die dynamischen
österreichischen Stromtarife von smartENERGY: **smartTIMES** (zeitabhängig), **smartCONTROL**
(an den EPEX-Spot-Börsenpreis gekoppelt) und **smartNIGHT** (zwei Preiszonen, Peak 07:00–23:00).
Der Tarif wird bei der Einrichtung gewählt. Sie ruft die öffentliche Tarifpreis-API ab (kein
API-Key) und stellt stündliche/viertelstündliche Preise als Sensoren bereit – inklusive aller
variablen Nebenkosten (Steuern, Abgaben, Netzentgelte; bei smartCONTROL zusätzlich die
Abwicklungsgebühr) und eines Binary-Sensors, der die günstigsten Stunden des Tages markiert.

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
- **Mindestversion für HACS**: `hacs.json` führt `"homeassistant"` – die Version, ab der HACS
  die Integration überhaupt anbietet. Sie folgt **nicht** der Version, die
  `pytest-homeassistant-custom-component` gerade nachzieht: Letztere ist die jeweils
  *neueste* getestete Version, nicht die *niedrigste* lauffähige – als Mindestangabe
  eingetragen schlösse sie alle Nutzer aus, die nicht sofort aktualisieren.

  Maßgeblich ist stattdessen die **niedrigste Version, auf der der Code tatsächlich läuft**.
  Das ist zunächst die oben genannte Zielruntime (2026.3.0, die erste Home-Assistant-Reihe
  auf Python 3.14); beim Anheben der Zielruntime den Wert mitziehen. Nutzt der Code eine
  API, die es erst später gibt, zählt diese – und der Grund gehört hierher, damit der Wert
  nicht später als unbegründet zurückgedreht wird. Aktuell gilt **2026.8.0** wegen
  `DeviceInfo["via_device_id"]`: Der Schlüssel existiert erst ab Home Assistant 2026.8.
  Sein Vorgänger `via_device` ist **seit 2026.8** als veraltet markiert, wird **ab 2026.9**
  zur Laufzeit gemeldet – eine Log-Warnung bei jedem Nutzer, die die Integration namentlich
  nennt – und **2027.8** entfernt. Für Nutzer auf älteren Reihen bricht dadurch nichts: HACS
  bietet ihnen die neue Fassung schlicht nicht an, die installierte läuft weiter.

## Befehle

Es gibt **kein** Build-System. Validiert wird über Home-Assistant-Tooling sowie eine
**pytest-Testsuite** (alles in CI, `.github/workflows/validate.yml`):

- **Hassfest** – prüft `manifest.json`, Übersetzungen, Struktur.
- **HACS validation** – prüft HACS-Tauglichkeit (`hacs.json`).
- **Ruff** – Linter, Konfiguration in `ruff.toml` (siehe unten).
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

# Linter (kommt mit requirements_test.txt; `--fix` behebt das meiste selbst):
ruff check .
```

**Ruff (`ruff.toml`).** Der Linter steht **nicht** wegen der Fehlersuche da – beim
Einführen fand er über den gesamten Code keinen einzigen Bug, nur zwei Dutzend
Kleinigkeiten. Sein Zweck ist, die Haltung des Projekts **maschinenlesbar** zu machen:
Ohne Konfiguration führt jedes Review-Werkzeug Ruff mit den Standardeinstellungen aus
und meldet 284-mal deutsche Typografie (`RUF001/002/003`: Gedankenstrich,
„Anführungszeichen“, Umlaute) als „mehrdeutiges Unicode-Zeichen“. Genau das kam auf
PRs wiederholt auf und musste jedes Mal neu begründet werden. Die drei Regeln sind
deshalb in `ruff.toml` ausdrücklich abgeschaltet – mitsamt Begründung, damit der
Eintrag später nicht als unbegründet zurückgedreht wird.

Zwei weitere Festlegungen dort: `line-length = 100` statt der 88 von
Home-Assistant-Core (bei 88 wären 46 Zeilen zu brechen, bei 100 sind es zwei), und
`D`/pydocstyle ist **nicht** ausgewählt, weil Regeln wie D401 („imperative mood“) auf
englische Docstrings gemünzt sind. Der **Formatter** (`ruff format`) läuft bewusst
nicht: Er würde 28 Dateien umbrechen, ohne dass jemand darum gebeten hätte.

**Testkonvention:** Die erwarteten Werte (Sollergebnisse) werden **von Hand aus der
Spezifikation** abgeleitet und als Kommentar dokumentiert – nie aus dem zu testenden
Code erzeugt, sonst wäre der Test eine Tautologie. Fixtures (echte API-Antworten) liegen
in `tests/fixtures/`. Für smartNIGHT gibt es **keine eigene Fixture**, weil es keine eigene API
gibt: Der Tarif entsteht aus `smarttimes.json`; `make_data(..., smartnight=True)` in
`conftest.py` legt dafür dieselbe Ableitung darüber wie der Client im Betrieb.

**Testnamen sind deutsch – repository-weit.** Eine Testfunktion beschreibt in
deutscher Prosa, was sie zusagt: `test_blockmodus_behaelt_die_laenge_bei_gleichstand`,
nicht `test_consecutive_keeps_the_requested_length_on_tie`. Der Name steht direkt
über einem deutschen Docstring; eine englische Zeile dazwischen liest sich wie ein
Fremdkörper. Umlaute und ß werden umschrieben (`ae`, `oe`, `ue`, `ss`), weil
Bezeichner sonst je nach Editor und Terminal unterschiedlich aussehen.

Die Suite war lange **dateiweise** gemischt – acht Dateien englisch, sechs deutsch,
fünf gemischt. Das ließ jede neue Datei die Frage neu aufwerfen und beantwortete sie
je nachdem, wen man fragte. Deshalb gilt jetzt eine Regel für alle.

**Eine Ausnahme, und nur diese: Bezeichner, die ein konkretes Codeartefakt benennen,
behalten ihre Schreibweise.** Der Name soll auf die geprüfte Sache zeigen; übersetzt
man ihn, zeigt er ins Leere. Dazu zählen HTTP-Header (`retry_after`),
Home-Assistant-Klassen (`update_failed` für `UpdateFailed`), Konfigurations- und
Attributschlüssel (`exact_hours`, `prices_tomorrow_valid`, `expected_after`) sowie
feststehende Fachbegriffe der Domäne (`snap`, `jitter`, `issue`, `user_agent`).
Beispiel: `test_retry_after_mit_verstrichenem_datum_ergibt_null` – deutscher Satz,
englischer Bezeichner am Anfang.

Nicht darunter fallen bloße Anglizismen der Umgangssprache: `lookup` gehört
übersetzt (`test_netzgebiet_nachschlagen`), `retry_after` nicht.

Geprüft wird das **nicht** maschinell – eine Sprachprüfung wäre eine Heuristik mit
falschen Alarmen, und die Ausnahme oben lässt sich ohnehin nicht mechanisch von einem
Anglizismus unterscheiden. Die Regel steht hier, damit sie beim Schreiben gilt.

**Fixtures und Hilfsfunktionen sind bewusst noch nicht umgestellt** (`_FakeResponse`,
`_get_prices_error`, `live_session` neben `netzwerk_freigeben`, `uhr`, `tagesdaten`).
Sie sind kein Teil dieser Regel; wer sie angleicht, tut das als eigene Änderung.

**Zeitzone in Tests: durchgehend `Europe/Vienna`.** Die Integration gibt es nur in Österreich,
und die gesamte handgerechnete Preis-Mathematik hängt an der Ortszeit – SNAP-Fenster
(10–16 Uhr), Tagesgrenzen und „morgen“. Zwei Fixtures in `conftest.py` stellen das sicher:
`_vienna_default_tz` (autouse) für Tests **ohne** HA-Instanz und eine Überschreibung der
`hass`-Fixture für alle übrigen. Letztere ist nötig, weil
`pytest-homeassistant-custom-component` beim Hochfahren fest `US/Pacific` setzt und die
Vorgabe damit wieder überschreibt.

Diese Aufteilung nicht aufweichen und die Zeitzone **nicht je Test von Hand setzen** – genau
so stand derselbe Aufruf vorher fünfmal in einzelnen Testkörpern, und wer ihn vergaß, bekam
still US/Pacific. Sollwerte treffen dann bestenfalls zufällig zu, aus einem anderen Grund als
dem im Kommentar dokumentierten; der Test prüft dann nicht mehr, was er zu prüfen vorgibt.
`test_ha_instanzen_laufen_auf_europe_vienna` wacht darüber.

**Live-Tests** (`tests/test_api_live.py`, Marker `live`) sind die einzigen Tests, die die
echte smartENERGY-API abrufen. Ohne die Option `--live` werden sie übersprungen – der
normale Lauf bleibt offline und unabhängig vom fremden Server. Sie prüfen **Invarianten**
(lückenloses Viertelstundenraster, Zeitzone, Einheit, aktueller Zeitpunkt abgedeckt,
plausible Werte), **nie** konkrete Preise, und vergleichen die **Feldstruktur** der
Live-Antwort mit den Fixtures – schlägt der Vergleich an, hat die API ihr Format geändert
und die Fixtures gehören aktualisiert. Da das HA-Test-Harness Sockets und DNS pro Test
sperrt, hebt die Fixture `netzwerk_freigeben` diese Sperre gezielt nur für diese Tests auf.

smartNIGHT steht **nicht** in `ERWARTUNGEN` – jene Tabelle hängt an Endpunkt und Fixture,
und beide wären dieselben wie bei smartTIMES. Stattdessen prüft ein eigener Live-Test, dass
sich aus der Live-Antwort weiterhin genau zwei Preisstufen je Kalendertag im Verhältnis 1,3
ergeben; auch das ist eine Invariante, kein konkreter Preis.

CI läuft bei jedem Push auf `main`, bei jedem PR und manuell (`validate.yml`); die
Live-Tests laufen getrennt davon nächtlich und manuell (`live-api.yml`). Schlägt ein
Live-Lauf fehl, legt der Workflow ein Issue mit dem Label `live-api-fehler` an bzw.
kommentiert das bereits offene – die E-Mail-Benachrichtigung von GitHub ist bei geplanten
Läufen zu unzuverlässig. Das Issue bleibt offen, bis es jemand von Hand schließt. Ein dritter
Workflow (`wiki-push.yml`) veröffentlicht das Wiki und prüft nichts; er läuft nur bei Pushes
auf `main`, die `wiki/` berühren (siehe „Dokumentation“).

Ein fehlgeschlagener Live-Lauf hängt außerdem die **abgerufenen API-Antworten als Artefakt**
`live-antworten` an und verlinkt es im Issue. Ohne das stirbt die Antwort mit dem Runner –
und mit ihr der Beleg für die wahrscheinlichste Ursache, eine Formatänderung. Geschrieben
werden sie von `lege_antwort_ab` in `tests/test_api_live.py`, gesteuert über die
Umgebungsvariable `LIVE_ANTWORT_DIR`; ohne sie bleibt ein lokaler Lauf ohne Nebenwirkung.
Dateiname und Formatierung entsprechen den Fixtures, damit ein `diff` gegen
`tests/fixtures/` nur echte Unterschiede zeigt. Übernommen wird daraus die **Feldänderung**,
nicht die Datei: Die handgerechneten Sollwerte der übrigen Tests hängen an den eingefrorenen
Tagen und Preisen der Fixture.

**Action-Referenzen in den Workflows:** `actions/checkout`, `actions/setup-python`,
`actions/upload-artifact` und `Andrew-Chen-Wang/github-wiki-action` sind auf einen
**Commit-SHA** gepinnt, mit der genauen Version als Kommentar dahinter (`# v7.0.1`) – daran
verankert Dependabot den Ist-Stand und schreibt beim Update SHA *und* Kommentar um. Bei der
Wiki-Action kommt hinzu, dass sie als einzige Schreibrecht auf das Repository bekommt.
`home-assistant/actions/hassfest` und `hacs/action` bleiben dagegen bewusst auf
`master`/`main`: Beide werden nicht mehr getaggt, und
ein Pin würde ausgerechnet die Validatoren einfrieren, die die jeweils aktuellen
Hassfest-/HACS-Regeln prüfen sollen. Diese Aufteilung beibehalten – gepinnt wird alles, was
regulär getaggt ist.

## Architektur – das große Bild

Datenfluss: **`api.py` (Abruf + Parsing) → `coordinator.py` (Caching, Drosselung, gesamte
Preis-Mathematik) → Entitäten (`sensor.py`, `binary_sensor.py`, gemeinsame Basis in
`entity.py`)**.

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

- **Einheiten – ct/kWh innen, EUR/kWh außen**: `api.py` und `coordinator.py` rechnen
  durchgehend in **ct/kWh**, der Einheit, in der die API liefert; daran hängt die gesamte
  handgerechnete Preis-Mathematik in den Tests. Die **Entitäts-Ebene** (`sensor.py`,
  `binary_sensor.py`) gibt dagegen ausschließlich **EUR/kWh** aus – die Einheit, die das
  Energie-Dashboard erwartet und die alle Preissensoren vergleichbar macht. Umgerechnet wird
  nur über `const.to_eur()` (Rundung auf `EUR_DECIMALS` = 6 Stellen, weil der Coordinator auf
  4 Stellen in ct rundet). Diese Trennung beibehalten: Rechnet man im Coordinator in EUR,
  müssten sämtliche Sollwerte der Mathematik-Tests umgeschrieben werden, ohne dass etwas
  gewonnen wäre. Das Attribut `source_unit` weist den Einheiten-String der API aus
  (smartTIMES meldet `cent/kWh`).

- **`surcharges.py`** – bundeseinheitliche Steuern/Abgaben (Elektrizitätsabgabe,
  Erneuerbaren-Förderbeitrag) als **deklarative, datierte Tabelle** (`DatedRate` mit
  `since`/`until`). Es gilt der erste passende Satz nach Kalendertag → künftige Satzänderungen
  (z. B. Elektrizitätsabgabe ab 2027) greifen **automatisch ohne Code-Änderung**.

- **`grid_fees.py`** – **netzgebietsabhängige** Netzentgelte (Netzebene 7, Viertelstundenmessung,
  Variante „ohne Leistungsmessung“). Enthält die **SNAP**-Logik (Sommer-Nieder-Arbeitspreis:
  1. Apr–30. Sep, tgl. 10–16 Uhr, −20 % auf den Netz-Arbeitspreis). Werte sind **„Stand 2026“**
  und müssen **jährlich** aktualisiert werden (gilt auch für den Förderbeitrag in
  `surcharges.py`).

- **Günstige-Stunde-Sensoren** (`binary_sensor.py`) werden als **Config Subentries** angelegt –
  einer pro Verbraucher, mit eigener Stundenzahl (`cheap_hours`) und Auswahllogik (`cheap_mode`):
  - `individual`: günstigste **Einzel**-Intervalle (dürfen über den Tag verteilt sein).
  - `consecutive`: ein **zusammenhängender Block** „am Stück“.
  `exact_hours` („Stundenzahl exakt einhalten“, `DEFAULT_EXACT_HOURS`) entscheidet, was bei
  **Gleichstand** am Schwellwert passiert. **Vorgabe ist ein** – der Sensor liefert dann exakt
  die eingestellte Stundenzahl. Ausgeschaltet wird die Auswahl in `individual` erweitert (alle
  gleich teuren Intervalle mitmarkiert); betroffene Blöcke sind als `exceeds_cheap_hours`
  markiert. Das verteuert die kWh nie, verlängert aber die Einschaltdauer – und weil smartTIMES
  als Zeittarif nur **drei** Preisstufen kennt, liefert dort jede Stundenzahl zwischen 0,25 h
  und 8 h dieselben 8 Stunden. Genau deshalb wurde die Vorgabe umgedreht: „4 Stunden“ soll
  4 Stunden bedeuten. Ausschalten lohnt für selbstbegrenzende Verbraucher (Boiler mit
  Thermostat, Wallbox mit Ziel-Ladestand), die eine Gelegenheit zum selben Preis mitnehmen
  können. Dass Bestandssensoren ihr Verhalten behalten, sichert **nicht** die Vorgabe, sondern
  `_migriere_exact_hours` (siehe „Schema-Migration“): Es trägt ihnen den alten Wert `False`
  ausdrücklich ein. In `consecutive` wird **nie** erweitert und `exact_hours` ist wirkungslos:
  Eine feste Fensterlänge ist dort der Zweck der Betriebsart (Waschmaschine, Geschirrspüler).

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

- **`entity.py`** – gemeinsame **Geräte-Infos** und die Basisklasse der Untereintrags-
  Entitäten. Es gibt zwei Gerätesorten: ein **Hub-Gerät** je Config-Eintrag (trägt die
  Preissensoren und den Diagnose-Sensor) und **je Untereintrag ein Gerät**, benannt nach dem
  Verbraucher. Letztere hängen über `via_device_id` am Hub. Weil die Registry eine unbekannte
  ID zurückweist und die Entität dann gar nicht erst entsteht, legt `__init__.async_setup_entry`
  das Hub-Gerät **vor** `async_forward_entry_setups` an – die Plattformen werden nebenläufig
  eingerichtet, ein Entstehen als Nebenprodukt des ersten Sensors wäre ein Rennen.
  `CheapHourEntity` liest Stundenzahl, Auswahllogik, `exact_hours` und Jitter-Phase aus dem
  Untereintrag; `CheapHourBinarySensor` und `NextCheapStartSensor` erben davon.
  Typ-Hinweise nutzen dort `ConfigEntry` statt des Alias `SmartTimesConfigEntry` – `__init__.py`
  bezieht `hub_device_info` von hier, ein Rückimport wäre zur Laufzeit ein Zyklus.

- **`smartnight.py`** – die Tarifregeln von **smartNIGHT** und der ableitende API-Client.
  smartNIGHT hat **keinen eigenen Endpunkt**: Sein Off-Peak-Arbeitspreis *ist* der von
  smartTIMES, deshalb wird er aus derselben Antwort **berechnet** – Off-Peak übernimmt den
  günstigsten Preis des jeweiligen Kalendertages, von 07:00 bis 23:00 Uhr Ortszeit kommen
  30 % darauf (`SMARTNIGHT_PEAK_FACTOR`). Der Aufschlag trifft **nur den Arbeitspreis**;
  Abgaben, Netzentgelte und SNAP gelten unverändert, eine Abwicklungsgebühr gibt es nicht.
  Bewusst das **Tagesminimum** statt nachgebauter smartTIMES-Fenster: Verschiebt smartENERGY
  seine Zonen, bleibt die Regel richtig. Der Einstiegspunkt ist `SmartNightApiClient`, ein
  Untertyp von `SmartTimesApiClient`, der allein `async_get_prices` überschreibt – dadurch
  gelten Raster, Grundgebühr, Morgen-Preise, Cache, Drosselung, Retry und Diagnose Wort für
  Wort wie bei smartTIMES, statt in einem zweiten Datenpfad noch einmal geschrieben zu werden.
  Gebaut wird der Client über `__init__.erzeuge_preis_client`, die einzige Stelle, die Tarif
  auf Client abbildet (auch der Config-Flow prüft die Verbindung darüber).

- **`config_flow.py`** – UI-Einrichtung (kein YAML): Haupteintrag (Tarif, USt., Netzgebiet) +
  Options-Flow + Subentry-Flow für die Günstige-Stunde-Sensoren. Der **Tarif** (`CONF_TARIFF`:
  `smarttimes`/`smartcontrol`/`smartnight`) bestimmt API-URL, Client, Anzeigenamen und die
  Abwicklungsgebühr.
  `single_config_entry: true` → nur **eine** Instanz. Schemas müssen frontend-serialisierbar
  bleiben (keine Lambdas/`vol.All` mit Callable; Validierung stattdessen im Flow-Schritt).

- **Schema-Migration** – `CONFIG_ENTRY_VERSION` in `const.py` ist die einzige Quelle für
  `ConfigFlow.VERSION`. Wird sie angehoben, muss `async_migrate_entry` in `__init__.py` den
  Schritt von der Vorgängerversion beschreiben; Home Assistant ruft die Funktion für jeden
  älteren Eintrag auf, bevor `async_setup_entry` läuft. Zwei Muster stehen dort schon:
  **Vorgabewechsel** (`_migriere_exact_hours` schreibt Bestands-Untereinträgen den alten Wert
  ausdrücklich hinein, damit sie eine geänderte Vorgabe nicht erben) und **Umbenennung einer
  Entität** – Letztere in zwei Schritten: `_migriere_gesamtpreis_entitaet` schreibt die
  `unique_id` über die Entity-Registry *an Ort und Stelle* um (die Historie bleibt so erhalten,
  statt dass HA die Entität neu anlegt und die alte verwaist zurückbleibt), und
  `_migriere_gesamtpreis_entity_id` streicht anschließend den Einheitenzusatz aus der
  **Entity-ID** selbst, damit Bestands- und Neuinstallationen dieselbe ID führen und Doku und
  Wiki eine einheitliche nennen können. Kollidiert die Ziel-ID mit einer fremden Entität, bleibt
  die alte stehen – eine fremde zu verschieben wäre das größere Übel.

  Damit lässt sich fast jeder Bruch vermeiden. Was bleibt, ist die Referenz **beim Nutzer**: Wer
  die alte Entity-ID in Automatisierungen, Vorlagen oder Dashboards stehen hat, muss sie
  anpassen. Eine umbenannte Entity-ID gehört deshalb in die Release-Notes, ins README **und ins
  Wiki** – `wiki/` wird von keiner CI geprüft (siehe „Dokumentation“).

## Wichtige Hinweise

- **Zeitzone**: HA sollte auf `Europe/Vienna` stehen. smartTIMES liefert **lokale** Zeitstempel
  **ohne** Offset, smartCONTROL **mit** Offset (`+02:00`); `api.py` (`_parse_date`) übernimmt
  einen vorhandenen Offset und fällt sonst auf `dt_util.DEFAULT_TIME_ZONE` zurück. Zonen-Fenster
  werden durchweg über die **lokale Stunde** bestimmt (`grid_fees.is_snap`,
  `smartnight.ist_peak`) – der Tarif nennt Wanduhrzeiten, also gelten sie auch an den
  Umstellungstagen der Sommerzeit unverändert.
- **Domain** ist `smartenergy` (siehe `const.py`/`manifest.json`); das Integrationsverzeichnis
  heißt entsprechend `custom_components/smartenergy/`. Die Tarif-**Schlüssel** `smarttimes`/
  `smartcontrol`/`smartnight` (Config-Werte) sind davon unabhängig.
- **Docstring-Konvention**: Module, Klassen, Funktionen und Methoden (inkl. `__init__`) tragen
  knappe deutsche Docstrings; verschachtelte lokale Closures brauchen keine.

## Dokumentation

Nutzer-Doku ist zweigeteilt:

- **`README.md`** – kurz und HACS-tauglich: Feature-Pitch, Installation, Einrichtung, knappe
  Sensor-Übersicht. Zielgruppe ist, wer in HACS nach Integrationen sucht.
- **[Github-Wiki](https://github.com/da-sa-li/HA-smartenergy-Tarif/wiki)** – vertiefende
  Inhalte: `Home`, `Datenschutz`, `Netzentgelte-und-Nebenkosten`, `Sensoren-und-Attribute`,
  `Automatisierungsbeispiele`, `Fehlerbehebung`, `API-EVU` (technische Angaben für smartENERGY
  als API-Betreiber; der produktive User-Agent verweist auf diese Seite, siehe `const.py`).

**Das Wiki wird aus dem Repo erzeugt, nicht auf github.com gepflegt.** Die Quelle liegt unter
`wiki/`, `.github/workflows/wiki-push.yml` spiegelt sie bei jedem Push auf `main` (und auf
Zuruf per `workflow_dispatch`) ins GitHub-Wiki. Daraus folgt:

- **Eine Datei = eine Wiki-Seite**, der Dateiname *ist* der Seitenname:
  `wiki/Netzentgelte-und-Nebenkosten.md` → Seite `Netzentgelte-und-Nebenkosten`. Interne Links
  sind deshalb bare Wiki-Links (`[Datenschutz](Datenschutz)`), **keine** `.md`-Pfade.
  `_Sidebar.md` und `_Footer.md` sind die GitHub-Sonderseiten, die auf *jeder* Seite
  eingeblendet werden.
- **Nie direkt im Wiki auf github.com editieren.** Die Action *synchronisiert* das Verzeichnis:
  Sie überschreibt geänderte Seiten und löscht Seiten, deren Datei entfallen ist. Eine Änderung
  am Wiki, die nicht in `wiki/` steht, ist beim nächsten Push auf `main` weg. Wiki-Änderungen
  laufen wie Code über einen PR – und werden dort auch gegen den Code geprüft, was bei einer
  extern gepflegten Wiki-Seite niemand tut.
- Die Action **normalisiert das Markdown** beim Veröffentlichen (`preprocess`, Vorgabe an):
  Aufzählungen `-` → `*`, `> [!NOTE]` → `> \[!NOTE]`, eingezäunte Codeblöcke werden eingerückt.
  Die veröffentlichte Seite ist deshalb **nie byte-identisch** mit `wiki/`. Das ist kosmetisch –
  die Alerts rendern weiterhin –, also nicht dagegen anschreiben und nicht als Fehler
  hinterherjagen.
- Es gibt **keine CI-Prüfung** für das Wiki: keinen Link-Check, keinen Abgleich der dort
  genannten Entity-IDs und Attributnamen mit dem Code. Wer Entity-IDs, Attributnamen oder
  Einheiten ändert, muss `wiki/` von Hand mitziehen – genau das ist bei der 4.0-Umbenennung des
  Gesamtpreis-Sensors unterblieben.

## Release-Prozess

1. Version in **`custom_components/smartenergy/manifest.json`** anheben (SemVer; Minor = neue
   abwärtskompatible Features, Major = Breaking Change wie ein Domain-Wechsel).

   **Eine angehobene HA-Mindestversion in `hacs.json` ist für sich genommen kein Major.**
   Bei Bestandsnutzern bricht dabei nichts: Wer die neue Reihe nicht fährt, dem bietet HACS
   die Fassung gar nicht erst an, die installierte läuft unverändert weiter. Ein Bruch wäre
   es nur, wenn sich zugleich eine Entity-ID, ein Attributname, eine Einheit oder das
   Konfigurationsschema ändert. Der Hinweis gehört aber prominent in die Release-Notes. **Vorher prüfen,
   ob sich der Bruch per Migration vermeiden lässt** (siehe „Schema-Migration“ oben) – geänderte
   Attributnamen, Einheiten und Entity-IDs sind für Nutzer spürbar, eine umgeschriebene
   `unique_id` oder ein nachgetragener Vorgabewert nicht.
2. Mergen nach `main`.
3. Veröffentlichen als **Git-Tag `vX.Y.Z` + GitHub-Release** (HACS zieht Releases darüber). Der
   `version`-Wert im Manifest muss mit dem Release-Tag übereinstimmen.
