# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden in dieser Datei festgehalten.

Das Format orientiert sich an [Keep a Changelog 1.1.0](https://keepachangelog.com/de/1.1.0/),
und das Projekt hält sich an [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Entfernt

- Breaking: Der Sensor **„Preisrang heute“** (`…_preisrang_heute`) entfällt. Der Rang steht weiter
  als Attribut `rank` am Sensor „Preisquantil heute“; wer den Sensor in Automatisierungen,
  Vorlagen oder Dashboards verwendet, muss auf dieses Attribut oder auf das Quantil umstellen.
  Der Registry-Eintrag des entfallenen Sensors wird beim Start automatisch entfernt.

### Hinzugefügt

- **Winter-Nieder-Arbeitspreis (WiNAP)** nach § 7 Abs. 4 SNE-G-V: Vom 1. Oktober bis 31. März gilt
  jeweils von 23:00 bis 05:00 Uhr des Folgetags ein reduzierter Netz-Arbeitspreis, erstmals ab
  1. Oktober 2027. Neues Attribut `winap_active` am Gesamtpreis-Sensor (und in der Diagnose).
  Die Sätze je Netzgebiet gibt es erst mit den Netzentgelten 2027; bis dahin rechnet die
  Integration auch im WiNAP-Fenster mit dem normalen Arbeitspreis. Beim Tarif smartNIGHT zerfällt
  der Off-Peak im Winter, sobald der Satz hinterlegt ist, in zwei Preisstufen (05–07 Uhr ist teurer als davor).
- **Netzentgelte mit Gültigkeitszeitraum:** Die Sätze eines Netzgebiets lassen sich jetzt in
  datierten Gruppen hinterlegen (`since`/`until`). Ein Wechsel unter dem Jahr – etwa der Übergang
  auf das neue Entgeltsystem der Netzebene 7, der je Netzgebiet zu einem anderen Tag greifen kann –
  braucht damit kein Release zum Stichtag. Die Diagnose nennt mit `grid_rates_since`, welche Gruppe
  gerade gilt. Die bisherigen Sätze und damit alle Preise bleiben unverändert.

### Geändert

- **Zusammenhängender Block über Mitternacht:** Im Modus „Zusammenhängender Block“ wird der Block
  nicht mehr je Kalendertag gewählt, sondern je Zeitraum von 20:00 bis 20:00 Uhr. Er kann damit
  über Mitternacht reichen, wenn dort das günstigste Fenster liegt – bei smartCONTROL in manchen
  Nächten, ab Oktober 2027 im Winter durch den WiNAP (23–05 Uhr) bei allen Tarifen. Das gilt für
  bestehende und neue Sensoren gleichermaßen. Ab 20:00 Uhr beziehen sich die Attribute
  `cheap_intervals`, `cheap_windows` und `threshold_eur_kwh` dieser Sensoren bereits auf den
  nächsten Zeitraum. Fehlen um 20:00 Uhr die Preise für den Folgetag noch, bleibt der Sensor aus,
  bis sie vorliegen (ab Mitternacht ohne aktuellen Preis: `unknown`). Nach einem Neustart von Home Assistant fehlt der Abend vor Mitternacht; bis
  20:00 Uhr kann dann ein zweiter Block am selben Tag gewählt werden (siehe Wiki,
  „Fehlerbehebung“). Der Modus „Günstigste Einzelstunden“ wählt unverändert je Kalendertag.

### Behoben

- **Zeitumstellung im Herbst:** Die smartENERGY-API kennzeichnet in der Nacht der Rückstellung auf
  Winterzeit beide Durchläufe von 02:00–02:59 als Winterzeit. Bisher fehlte dadurch eine Stunde
  lang der aktuelle Preis, und „Günstige Stunde“-Sensoren im Modus „Günstigste Einzelstunden“
  liefen kürzer als eingestellt (etwa 3 statt 4 Stunden). Die Integration ordnet den ersten
  Durchlauf jetzt der Sommerzeit zu. Weiterhin ohne Preis bleibt am Umstellungstag die Stunde
  ab 23:00 Uhr, weil die API sie nicht liefert.

## [4.4.0] - 2026-10-05

### Hinzugefügt

- **Mehrere Zähler:** Die Integration lässt sich jetzt mehrfach einrichten – ein Eintrag je
  Zähler, auch mit unterschiedlichem Tarif, Netzgebiet oder USt.-Anzeige (z. B. Haushalt mit
  smartTIMES, Wärmepumpe mit smartCONTROL). Jeder Eintrag hat eigene Sensoren, Einstellungen und
  „Günstige Stunde“-Untereinträge und ruft die Preise selbst ab.

### Geändert

- Die Reparatur-Meldung „Tarifpreise werden seit längerem nicht aktualisiert“ erscheint jetzt je
  Eintrag und nennt dessen Namen im Titel.

### Behoben

- Keine Veraltet-Warnung mehr im Log ab Home Assistant 2026.9: Geräte werden über die neue
  Schnittstelle der Geräte-Registry nachgeschlagen.

> [!NOTE]
> Bestehende Installationen laufen unverändert weiter; Entitäts-IDs, Attribute und Einstellungen
> bleiben gleich. Teilen sich zwei Einträge denselben Tarif, hängt Home Assistant an die
> Entitäts-IDs des zweiten ein `_2` an (z. B. `sensor.smarttimes_strompreishelfer_gesamtpreis_2`).
> Zur besseren Unterscheidung das Gerät auf seiner Geräteseite umbenennen.

## [4.3.0] - 2026-09-01

### Hinzugefügt

- **smartNIGHT** als dritter Tarif. smartENERGY bietet dafür keine eigene API; die Preisstufen
  werden aus der smartTIMES-API abgeleitet (Off-Peak = günstigster Preis des Tages, 07:00–23:00 Uhr
  Aufschlag von 30 % auf den Arbeitspreis).

## [4.2.1] - 2026-08-29

### Geändert

- Die Grundgebühr bleibt `unbekannt`, wenn die API sie in einer anderen als der hinterlegten
  Einheit meldet, statt einen Jahreswert unter dem Etikett `EUR/month` anzuzeigen.
- Der Einheitenwechsel der Grundgebühr wird auch erkannt, wenn sie zwischenzeitlich entfiel.

### Behoben

- Das Attribut `total_eur_kwh` rechnet wie der Sensorzustand (netto summiert, USt. einmal am
  Ende); zuvor wich es in rund jedem sechsten Fall um 0,0001 ct/kWh ab.
- Die Attribute eines Preissensors stammen aus einer einzigen Uhrzeit und können nicht mehr über
  einen Viertelstundenwechsel hinweg gemischt werden.
- Dokumentation berichtigt: Das günstigste Preisniveau liegt im Preisquantil nicht bei 0 %,
  sondern bei der halben Breite seiner Gleichstandsgruppe (z. B. 16,67 %); der Zeitstempel
  „Nächster günstiger Start“ ist sekundengenau, der Binary-Sensor folgt ihm im Minutentakt.

## [4.2.0] - 2026-08-27

### Hinzugefügt

- Sensoren **„Preisrang heute“** und **„Preisquantil heute“**: ordnen den laufenden Gesamtpreis
  in den heutigen Tag ein (Rang 1 = günstigstes Intervall; Quantil in 0–100 %). Beide tragen die
  Attribute `rank`, `quantile_percent`, `interval_count`, `cheaper_intervals`, `equal_intervals`,
  `quantile_method` und `reference`.
- Wiki: Abschnitt „Preisrang und Preisquantil“ und ein Automatisierungsbeispiel dazu.

### Geändert

- Testsuite von 248 auf 348 Tests erweitert; Marker sind strikt, Warnungen gelten als Fehler.
- Testnamen repository-weit auf Deutsch vereinheitlicht.

## [4.1.0] - 2026-08-26

### Hinzugefügt

- Sensor **„Nächster günstiger Start“** je Untereintrag: der Beginn des nächsten günstigen
  Fensters als Zeitstempel, nutzbar in `time`-Triggern.
- Diagnose-Binary-Sensor **„Preise für morgen verfügbar“** mit den Attributen `price_count` und
  `expected_after`.
- Attribut `prices_tomorrow_valid` an beiden Preissensoren.
- Aussagekräftigere Fehlermeldungen in der Einrichtung (Zeitüberschreitung, abgelehnte Anfrage,
  unerwartete Antwort) und Feldbeschreibungen für Stundenzahl und USt.-Anzeige.

### Geändert

- **Mindestversion ist jetzt Home Assistant 2026.8** (bisher 2026.3).
- Die „Günstige Stunde“-Geräte hängen am Strompreishelfer („Verbunden über“); die Zuordnung wird
  beim ersten Start automatisch nachgetragen.
- Der Options-Flow prüft die Verbindung bei einem Tarifwechsel.

### Behoben

- Ein Tarifwechsel löste zwei Neuladungen statt einer aus.

## [4.0.0] - 2026-08-25

### Hinzugefügt

- Die Tageskennzahlen führen eine Langzeitstatistik.
- Attribute `unit` und `source_unit` an beiden Preissensoren.
- Automatische Schema-Migration bestehender Konfigurationen (`async_migrate_entry`).

### Geändert

- **Breaking:** Alle Preissensoren liefern **EUR/kWh** statt teils ct/kWh. Die Werte sind um
  Faktor 100 kleiner (aus `13,396` wird `0,13396`); Schwellwerte in Automatisierungen und
  Vorlagen müssen angepasst werden. Die Langzeitstatistik des Arbeitspreises passt dadurch nicht
  mehr zur bisherigen Reihe.
- **Breaking:** Der Gesamtpreis-Sensor heißt `…_gesamtpreis` statt `…_gesamtpreis_eur_kwh`. Die
  Umbenennung geschieht beim Update automatisch, die Historie bleibt erhalten; Verweise in
  Automatisierungen, Vorlagen und Dashboards sind anzupassen.
- **Breaking:** Preis-Attribute tragen `eur` statt `ct` im Namen (`working_price_ct_kwh` →
  `working_price_eur_kwh`, `surcharges_ct_kwh`, `surcharges_total_ct_kwh`, `total_ct_kwh`,
  `threshold_ct_kwh`, `current_price_ct_kwh` entsprechend; `unit_ct` → `unit`). Die Kennzahlen
  des Arbeitspreis-Sensors heißen jetzt `average_working_price_today`,
  `lowest_working_price_today`, `highest_working_price_today`, `next_working_price` und
  `next_working_price_start`.
- **Breaking:** Die Einheit der Grundgebühr lautet `EUR/month` statt `EUR/Monat`.
- „Stundenzahl exakt einhalten“ ist jetzt die Vorgabe für neue Sensoren; bestehende behalten per
  Migration ihr bisheriges Verhalten.
- Mindestversion ist Home Assistant 2026.3.0.

### Entfernt

- **Breaking:** Der Grundgebühr-Sensor entfällt bei smartCONTROL, weil die API dort keine meldet.
  Der Eintrag „nicht mehr bereitgestellt“ in der Entitätsregistry kann gelöscht werden.

### Behoben

- Die Recorder-Datenbank wuchs durch die Vorschaulisten der „Günstige Stunde“-Sensoren.
- Die Option „Stundenzahl exakt einhalten“ war außerhalb von Deutsch und Englisch unbeschriftet.
- Der zweite Einrichtungsversuch zeigte einen rohen Schlüsselnamen statt einer Erklärung.

## [3.1.0] - 2026-08-19

### Hinzugefügt

- Option, den Günstige-Stunde-Sensor auf die tatsächlich eingestellte Anzahl Stunden zu
  beschränken.

### Behoben

- Die Last-Glättung (Jitter) reißt an Mitternacht keine Schaltlücke mehr auf.

## [3.0.0] - 2026-08-14

### Entfernt

- **Breaking:** Das Attribut `prices` (vollständige Preisliste) entfällt. Es überschritt bei
  längeren Preisreihen die 16-KiB-Attributgrenze des Recorders. Stattdessen `prices_today` und
  `prices_tomorrow` verwenden.

### Behoben

- Übermäßiges Wachstum der Recorder-Datenbank: `prices_today` und `prices_tomorrow` sind von der
  Historie ausgenommen.

## [2.1.2] - 2026-08-12

### Hinzugefügt

- Mindestabstand von 5 Minuten zwischen zwei API-Aufrufen als Sicherheitsnetz.
- README-Abschnitt dazu, was beim Abruf übertragen wird.

### Geändert

- Wiederholungsversuche mit wachsendem Abstand (30 Minuten, dann verdoppelnd bis 2 Stunden).
- Ein `Retry-After` des Servers hat Vorrang, sofern es länger ist.
- Dauerhafte Fehler (z. B. 404, 403) gehen sofort auf das maximale Wartenintervall.
- Der Zeitpunkt des täglichen Abrufs wechselt täglich, statt dauerhaft auf derselben Minute zu
  liegen.
- Die Log-Meldung bei fehlgeschlagenem Abruf nennt den Zeitpunkt des nächsten Versuchs.

### Behoben

- Einrichtung auf FIPS-gehärteten Systemen: Der Abruf-Versatz wird aus SHA-256 statt MD5
  abgeleitet.
- Die Fehlerbehebung nannte „ca. 14 Uhr“ für die Morgen-Preise; richtig ist 17 Uhr.

## [2.1.1] - 2026-08-11

### Geändert

- Der User-Agent der API-Anfragen enthält Produktname und Version.

## [2.1.0] - 2026-08-04

### Hinzugefügt

- Die Oberfläche ist in mehreren Sprachen verfügbar.

### Geändert

- Lizenzwechsel von AGPL auf MIT.
- README: Installation über das HACS-Default-Repository vereinfacht.

## [2.0.1] - 2026-06-08

### Hinzugefügt

- Diagnose-Plattform für einfacheres Debugging.
- Reparatur-Hinweise für veraltete Tarifdaten und dauerhafte Abruf-Fehler.
- Icons über `icons.json`.
- README: Automatisierungsbeispiele und Fehlerbehebung.

## [2.0.0] - 2026-06-03

### Hinzugefügt

- Unterstützung für den Tarif **smartCONTROL**.

### Geändert

- **Breaking:** Die Domain der Integration lautet jetzt `smartenergy` (Verzeichnis
  `custom_components/smartenergy/`).

## [1.1.1] - 2026-06-03

### Hinzugefügt

- Auswahlmodus „zusammenhängender Block“ für den Günstige-Stunde-Sensor.

## [1.0.0] - 2026-06-01

### Hinzugefügt

- Erste Version für HACS mit Preisen, Netzentgelten und Nebenkosten für 2026.

### Geändert

- Integration in „smartTIMES Strompreishelfer“ umbenannt, Domain angepasst.

[Unreleased]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v4.4.0...HEAD
[4.4.0]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v4.3.0...v4.4.0
[4.3.0]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v4.2.1...v4.3.0
[4.2.1]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v4.2.0...v4.2.1
[4.2.0]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v4.1.0...v4.2.0
[4.1.0]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v4.0.0...v4.1.0
[4.0.0]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v3.1.0...v4.0.0
[3.1.0]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v3.0.0...v3.1.0
[3.0.0]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v2.1.2...v3.0.0
[2.1.2]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v2.1.1...v2.1.2
[2.1.1]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v1.1.1...v2.0.0
[1.1.1]: https://github.com/da-sa-li/HA-smartenergy-Tarif/compare/v1.0.0...v1.1.1
[1.0.0]: https://github.com/da-sa-li/HA-smartenergy-Tarif/releases/tag/v1.0.0
