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
  `DeviceInfo["via_device_id"]`: Der Schlüssel existiert erst ab Home Assistant 2026.8, und
  sein Vorgänger `via_device` wird ab 2026.9 als veraltet gemeldet (Entfernung 2027.8) –
  eine Log-Warnung bei jedem Nutzer, die die Integration namentlich nennt. Für Nutzer auf
  älteren Reihen bricht dadurch nichts: HACS bietet ihnen die neue Fassung schlicht nicht
  an, die installierte läuft weiter.

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

**Zeitzone in Tests:** Die autouse-Fixture `_vienna_default_tz` greift nur für Tests **ohne**
HA-Instanz. Sobald `hass` beteiligt ist, setzt das Test-Harness `US/Pacific` und überschreibt
sie – SNAP-Fenster, Tagesgrenzen und „morgen" verrutschen dann um neun Stunden. Alles
Ortszeitabhängige nutzt deshalb die Fixture **`hass_wien`** statt `hass`. Sonst können
Sollwerte zufällig zutreffen, aber aus einem anderen Grund als dem dokumentierten – und der
Rechenweg im Kommentar wäre falsch.

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
Läufen zu unzuverlässig. Das Issue bleibt offen, bis es jemand von Hand schließt. Ein dritter
Workflow (`wiki-push.yml`) veröffentlicht das Wiki und prüft nichts; er läuft nur bei Pushes
auf `main`, die `wiki/` berühren (siehe „Dokumentation").

**Action-Referenzen in den Workflows:** `actions/checkout`, `actions/setup-python` und
`Andrew-Chen-Wang/github-wiki-action` sind auf einen **Commit-SHA** gepinnt, mit der genauen
Version als Kommentar dahinter (`# v7.0.1`) – daran verankert Dependabot den Ist-Stand und
schreibt beim Update SHA *und* Kommentar um. Bei der Wiki-Action kommt hinzu, dass sie als
einzige Schreibrecht auf das Repository bekommt. `home-assistant/actions/hassfest` und
`hacs/action` bleiben dagegen bewusst auf `master`/`main`: Beide werden nicht mehr getaggt, und
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
  Variante „ohne Leistungsmessung"). Enthält die **SNAP**-Logik (Sommer-Nieder-Arbeitspreis:
  1. Apr–30. Sep, tgl. 10–16 Uhr, −20 % auf den Netz-Arbeitspreis). Werte sind **„Stand 2026"**
  und müssen **jährlich** aktualisiert werden (gilt auch für den Förderbeitrag in
  `surcharges.py`).

- **Günstige-Stunde-Sensoren** (`binary_sensor.py`) werden als **Config Subentries** angelegt –
  einer pro Verbraucher, mit eigener Stundenzahl (`cheap_hours`) und Auswahllogik (`cheap_mode`):
  - `individual`: günstigste **Einzel**-Intervalle (dürfen über den Tag verteilt sein).
  - `consecutive`: ein **zusammenhängender Block** „am Stück".
  `exact_hours` („Stundenzahl exakt einhalten", `DEFAULT_EXACT_HOURS`) entscheidet, was bei
  **Gleichstand** am Schwellwert passiert. **Vorgabe ist ein** – der Sensor liefert dann exakt
  die eingestellte Stundenzahl. Ausgeschaltet wird die Auswahl in `individual` erweitert (alle
  gleich teuren Intervalle mitmarkiert); betroffene Blöcke sind als `exceeds_cheap_hours`
  markiert. Das verteuert die kWh nie, verlängert aber die Einschaltdauer – und weil smartTIMES
  als Zeittarif nur **drei** Preisstufen kennt, liefert dort jede Stundenzahl zwischen 0,25 h
  und 8 h dieselben 8 Stunden. Genau deshalb wurde die Vorgabe umgedreht: „4 Stunden" soll
  4 Stunden bedeuten. Ausschalten lohnt für selbstbegrenzende Verbraucher (Boiler mit
  Thermostat, Wallbox mit Ziel-Ladestand), die eine Gelegenheit zum selben Preis mitnehmen
  können. Dass Bestandssensoren ihr Verhalten behalten, sichert **nicht** die Vorgabe, sondern
  `_migriere_exact_hours` (siehe „Schema-Migration"): Es trägt ihnen den alten Wert `False`
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
  `SmartTimesConfigEntry` wird dort nur unter `TYPE_CHECKING` importiert – `__init__.py` bezieht
  `hub_device_info` von hier, zur Laufzeit wäre das ein Zyklus.

- **`config_flow.py`** – UI-Einrichtung (kein YAML): Haupteintrag (Tarif, USt., Netzgebiet) +
  Options-Flow + Subentry-Flow für die Günstige-Stunde-Sensoren. Der **Tarif** (`CONF_TARIFF`:
  `smarttimes`/`smartcontrol`) bestimmt API-URL, Anzeigenamen und die Abwicklungsgebühr.
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
  Wiki** – `wiki/` wird von keiner CI geprüft (siehe „Dokumentation").

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
   abwärtskompatible Features, Major = Breaking Change wie ein Domain-Wechsel). **Vorher prüfen,
   ob sich der Bruch per Migration vermeiden lässt** (siehe „Schema-Migration" oben) – geänderte
   Attributnamen, Einheiten und Entity-IDs sind für Nutzer spürbar, eine umgeschriebene
   `unique_id` oder ein nachgetragener Vorgabewert nicht.
2. Mergen nach `main`.
3. Veröffentlichen als **Git-Tag `vX.Y.Z` + GitHub-Release** (HACS zieht Releases darüber). Der
   `version`-Wert im Manifest muss mit dem Release-Tag übereinstimmen.
