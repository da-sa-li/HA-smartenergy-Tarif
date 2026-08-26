> [!NOTE]
> Die Entitäts-IDs der **Preissensoren** beginnen mit dem gewählten Tarif – `smarttimes_…` bzw. `smartcontrol_…`; die Beispiele unten zeigen den smartTIMES-Fall. Die **„Günstige Stunde“-Sensoren** hängen dagegen am Gerät ihres Untereintrags und beginnen deshalb mit dem dort selbst vergebenen Namen.

# Übersicht

| Sensor / Entität | Beschreibung |
|---|---|
| `sensor.smarttimes_strompreishelfer_arbeitspreis` | **Reiner Arbeitspreis** der aktuell gültigen Tarifzone (EUR/kWh) |
| `sensor.smarttimes_strompreishelfer_gesamtpreis` | **Gesamtpreis inkl. aller variablen Nebenkosten** (EUR/kWh) – fürs Energie-Dashboard |
| `binary_sensor.<name>_gunstige_stunde` *(je Untereintrag)* | `on` in den günstigsten Stunden des Tages (nach **Gesamtkosten**); ein Sensor je angelegtem Untereintrag |
| `sensor.<name>_nachster_gunstiger_start` *(je Untereintrag)* | Beginn des nächsten günstigen Fensters als **Zeitstempel** – direkt als `at:` eines `time`-Triggers verwendbar |
| `sensor.smarttimes_strompreishelfer_durchschnittlicher_gesamtpreis_heute` | Durchschnittlicher **Gesamtpreis** heute (EUR/kWh) |
| `sensor.smarttimes_strompreishelfer_niedrigster_gesamtpreis_heute` | Günstigster **Gesamtpreis** heute (EUR/kWh) |
| `sensor.smarttimes_strompreishelfer_hochster_gesamtpreis_heute` | Teuerster **Gesamtpreis** heute (EUR/kWh) |
| `sensor.smarttimes_strompreishelfer_grundgebuhr` | Monatliche Grundgebühr (EUR/month) – wird nur angelegt, wenn die API eine Grundgebühr liefert (derzeit nur **smartTIMES**) |
| `binary_sensor.smarttimes_strompreishelfer_preise_fur_morgen_verfugbar` | `on`, sobald die Preise für den Folgetag vorliegen (Diagnose) |

Der **Arbeitspreis**-Sensor enthält nur den reinen Energiepreis. Der **Gesamtpreis**-Sensor addiert Steuern, Abgaben und Netzentgelte (siehe [Netzentgelte und Nebenkosten](Netzentgelte-und-Nebenkosten)) und ist die richtige Wahl fürs Energie-Dashboard und zum Schalten. Tageskennzahlen und der Günstige-Stunde-Sensor beziehen sich auf den **Gesamtpreis**.

Alle Preissensoren verwenden dieselbe Einheit (**EUR/kWh**) und sind damit unmittelbar vergleichbar – etwa der aktuelle Gesamtpreis gegen den Tagesdurchschnitt, ohne Template-Sensor. Die API liefert die Preise in ct/kWh; umgerechnet wird erst beim Sensor. Der Einheiten-String der API steht im Attribut `source_unit`.

# Gesamtpreis-Sensor

| Attribut | Beschreibung |
|---|---|
| `working_price_eur_kwh` | Reiner Arbeitspreis (EUR/kWh) |
| `surcharges_eur_kwh` | Nebenkosten je Position, z. B. `{electricity_tax: 0.0012, renewable_support: 0.00744, grid_usage: 0.06696, grid_loss: 0.0084}`. Bei **smartCONTROL** zusätzlich `handling_fee` (Abwicklungsgebühr, 0,0144 EUR/kWh brutto) |
| `surcharges_total_eur_kwh` | Summe aller Nebenkosten (EUR/kWh) |
| `total_eur_kwh` | Gesamtpreis (EUR/kWh) – entspricht dem Sensorwert |
| `grid_zone` | Gewähltes Netzgebiet (oder `null`) |
| `snap_active` | `true`, wenn für das **aktuelle Intervall** der SNAP gilt. Ohne gewähltes Netzgebiet immer `false` |
| `average_today` / `lowest_today` / `highest_today` | Tageskennzahlen (Gesamtpreis, EUR/kWh) |
| `next_price` / `next_price_start` | Gesamtpreis und Beginn des nächsten Intervalls |
| `prices_today` / `prices_tomorrow` | Vollständige **Gesamtpreis**-Vorschau für heute und morgen (`start`, `end`, `price`) |
| `prices_tomorrow_valid` | `true`, sobald die Preise für morgen vorliegen. Trennt „noch nicht veröffentlicht“ von „keine Preise“ – `prices_tomorrow` ist in beiden Fällen leer |
| `unit` | Einheit der Preisangaben in diesen Attributen (`EUR/kWh`) |
| `source_unit` | Einheit, in der die API liefert – smartTIMES meldet `cent/kWh`, smartCONTROL `ct/kWh` (gleichbedeutend) |
| `vat_included` / `vat_rate` | Ob brutto gerechnet wird und der USt.-Satz |

> [!NOTE]
> `prices_tomorrow` ist leer, solange die Preise für den nächsten Tag noch nicht veröffentlicht sind – laut API-Zusage ab 17 Uhr. Eine leere Liste bedeutet also nicht zwingend „keine Preise“, sondern meist „noch nicht verfügbar“.
>
> Wer das in einer Automatisierung unterscheiden muss, nimmt das Attribut `prices_tomorrow_valid` oder den Binary-Sensor [Preise für morgen verfügbar](#binary-sensor-preise-für-morgen-verfügbar).

# Binary-Sensor „Günstige Stunde“

Dieser Sensor ist `on` während der **günstigsten Stunden des Tages nach Gesamtkosten** (inkl. Netzentgelte und SNAP). Die Stundenanzahl wird je Untereintrag über `cheap_hours` konfiguriert.

Die **Auswahllogik** (`cheap_mode`) legt fest, *wie* die günstigen Stunden bestimmt werden:

- **Günstigste Einzelstunden** (`individual`, Standard): die billigsten Intervalle des Tages – sie dürfen über den Tag verteilt (zerteilt) sein. Geeignet für Verbraucher ohne feste Laufzeit (Boiler, Wallbox).
- **Zusammenhängender Block** (`consecutive`): das günstigste *lückenlose* Zeitfenster aus `cheap_hours` „am Stück“ – für Geräte, deren Laufzeit nicht unterbrochen werden darf (Waschmaschine, Geschirrspüler). Der Block wird bei Preisgleichstand **nie** verlängert: Die eingestellte Länge gilt hier immer exakt, denn genau dafür gibt es diese Betriebsart.

## Stundenzahl exakt einhalten (`exact_hours`)

Kosten mehrere Intervalle genau so viel wie das teuerste noch ausgewählte, ist die Auswahl unter ihnen willkürlich. Diese Option legt fest, wie damit umgegangen wird – sie wirkt **nur** bei „Günstigste Einzelstunden“.

- **Eingeschaltet (Vorgabe seit 4.0.0):** Der Sensor liefert exakt die eingestellte Stundenzahl.
- **Ausgeschaltet:** Alle preisgleichen Intervalle werden mitmarkiert. Der Sensor ist dann **länger an als eingestellt**, aber nie zu einem höheren Preis – alle zusätzlichen Intervalle liegen exakt auf dem Grenzpreis. Sinnvoll für selbstbegrenzende Verbraucher (Boiler mit Thermostat, Wallbox mit Ziel-Ladestand), die eine zusätzliche Gelegenheit zum selben Preis mitnehmen können.

Wie stark sich das auswirkt, hängt am Tarif: **smartCONTROL** ist börsengekoppelt und hat pro Tag fast durchweg verschiedene Preise – die Erweiterung greift dort kaum. **smartTIMES** kennt als Zeittarif nur drei Preisstufen zu je 8 Stunden; mit ausgeschalteter Option liefert dort jede Einstellung zwischen 0,25 h und 8 h dieselben 8 Stunden, die Stundenzahl ist also praktisch wirkungslos.

## Last-Glättung (Jitter)

Damit nicht alle Verbraucher gleichzeitig schalten und Lastspitzen erzeugen, verschiebt jeder Sensor seine Schaltflanken um einen kleinen, je Sensor stabilen Versatz. Der Versatz ist deterministisch aus der Sensor-ID abgeleitet, also über Neustarts hinweg gleich, und wird im Attribut `jitter_offset_seconds` ausgewiesen.

**Beide Flanken wandern nach innen:** Eingeschaltet wird bis zu 10 min *später*, ausgeschaltet bis zu 10 min *früher*. Das Schaltfenster liegt damit immer vollständig innerhalb des günstigen Blocks – der Verbraucher läuft zu keinem Zeitpunkt in einer teureren Preiszone. Der Preis dafür ist eine feste Verkürzung von 10 min je Block, für jeden Sensor gleich lang. Bei kurzen Günstig-Fenstern fällt das ins Gewicht: Aus einer konfigurierten Stunde werden 50 Minuten Laufzeit.

Läuft ein günstiger Zeitraum über Mitternacht, werden die Blöcke beider Tage für den Jitter zu **einem** zusammengefasst – sonst risse der Versatz am Tageswechsel eine Schaltlücke auf. Ein Fenster in `cheap_windows` kann deshalb vor dem heutigen Tag beginnen oder nach ihm enden.

Wer sich wundert, warum der Sensor nicht zur vollen Stunde schaltet: Das ist genau dieser Versatz und kein Fehler. Der eigene Wert steht in `jitter_offset_seconds`.

## Attribute

| Attribut | Beschreibung |
|---|---|
| `cheap_hours` | Konfigurierte Anzahl günstiger Stunden pro Tag |
| `cheap_mode` | Auswahllogik: `individual` (Einzelstunden) oder `consecutive` (Block) |
| `exact_hours` | `true`, wenn die Stundenzahl exakt eingehalten wird (keine Erweiterung bei Preisgleichstand). Nur bei `individual` wirksam |
| `threshold_eur_kwh` | Höchster Gesamtpreis unter den günstigen Intervallen (EUR/kWh) |
| `current_price_eur_kwh` | Aktueller Gesamtpreis (EUR/kWh) |
| `unit` | Einheit der Preisangaben in diesen Attributen (`EUR/kWh`) |
| `jitter_offset_seconds` | Konstanter **Einschalt**-Versatz dieses Sensors (Sekunden). Ausgeschaltet wird um `600 − jitter_offset_seconds` Sekunden **vor** dem Blockende – beide Flanken wandern nach innen |
| `next_cheap_start` | Nächster (gejitterter) Einschaltzeitpunkt |
| `cheap_intervals` | Liste der heutigen günstigen Intervalle (`start`, `end`, `price` in EUR/kWh) |
| `cheap_windows` | Tatsächliche, gejitterte Schaltfenster (`on`, `off`, `exceeds_cheap_hours`) |
| `vat_included` | `true`, wenn brutto gerechnet wird |

`exceeds_cheap_hours` in `cheap_windows` ist `true`, wenn der Block wegen eines Preis-Gleichstands über die eingestellte Stundenzahl hinausreicht. Die Angabe ist rein informativ – auf das Schaltverhalten wirkt sie sich nicht aus. Bei eingeschaltetem `exact_hours` und im Blockmodus ist sie immer `false`.

# Sensor „Nächster günstiger Start“

Je Untereintrag entsteht neben dem Binary-Sensor ein **Zeitstempel-Sensor** mit dem Beginn des nächsten günstigen Fensters. Er trägt `device_class: timestamp`, und genau darum geht es: Der `time`-Trigger von Home Assistant nimmt unter `at:` nur Entitäten mit dieser Geräteklasse. Ein Attribut – auch `next_cheap_start` am Binary-Sensor – lässt sich dort nicht referenzieren, weshalb „30 Minuten vor dem günstigen Fenster vorheizen“ bislang einen Template-Sensor brauchte. Ein Beispiel steht unter [Automatisierungsbeispiele](Automatisierungsbeispiele).

Der Wert **enthält die Last-Glättung bereits** und stimmt damit sekundengenau mit dem Zeitpunkt überein, zu dem der zugehörige Binary-Sensor auf `on` geht.

> [!NOTE]
> Der Sensor steht auf `unknown`, wenn kein nächstes Fenster bekannt ist – typischerweise spät abends, bevor die Preise für den Folgetag veröffentlicht sind. Das ist Absicht und kein Fehler: Ein `time`-Trigger feuert dann schlicht nicht, statt eine falsche Zeit zu verwenden.

Der Sensor führt keine Einheit und keine Langzeitstatistik; beides gibt es für Zeitstempel nicht.

# Binary-Sensor „Preise für morgen verfügbar“

Ein Diagnose-Sensor am Gerät des Strompreishelfers. Er ist `on`, sobald die Preise für den Folgetag im Zwischenspeicher liegen.

Ohne ihn lässt sich „noch nicht veröffentlicht“ nicht von „keine Preise“ unterscheiden: `prices_tomorrow` ist in beiden Fällen eine leere Liste. Er ist damit der natürliche Auslöser für „Tagesplan neu rechnen, sobald die Morgenpreise da sind“.

| Attribut | Beschreibung |
|---|---|
| `price_count` | Anzahl der bereits vorliegenden Intervalle für morgen (ein voller Tag sind 96 Viertelstunden) |
| `expected_after` | Zeitpunkt, ab dem die Integration die Preise erwartet: 17 Uhr Ortszeit zuzüglich des Abruf-Versatzes dieser Installation (bis zu 20 Minuten, siehe unten). Vor dieser Zeit ist `off` der Normalzustand, danach ein Hinweis auf eine Störung beim Anbieter |

> [!NOTE]
> Die 17 Uhr sind die Zusage der API; die Integration ruft absichtlich erst ein paar Minuten später ab, damit nicht alle Installationen zur selben Sekunde anfragen. Dieser Versatz ist je Installation und Tag verschieden und in `expected_after` bereits eingerechnet.

> [!NOTE]
> Die Einordnung als **Diagnose** blendet den Sensor lediglich aus der Gerätekarte aus (er steht dort unter „Diagnose“). Als Auslöser einer Automatisierung, in Vorlagen und in der Historie ist er uneingeschränkt nutzbar.
>
> Er trägt bewusst **keine** `device_class`: `problem` kehrte die Bedeutung um und wiese den planmäßigen Zustand vor 17 Uhr als Störung aus.

# Arbeitspreis-Sensor

| Attribut | Beschreibung |
|---|---|
| `tariff` | Gewählter Tarif (`smartTIMES` bzw. `smartCONTROL`) |
| `unit` | Einheit der Preise (`EUR/kWh`) |
| `source_unit` | Einheit, in der die API liefert – smartTIMES meldet `cent/kWh`, smartCONTROL `ct/kWh` (gleichbedeutend) |
| `interval_minutes` | Länge eines Preisintervalls in Minuten |
| `vat_included` | `true`, wenn die Preise brutto (inkl. USt.) sind |
| `current_start` / `current_end` | Beginn/Ende des aktuellen Preisintervalls |
| `next_working_price` / `next_working_price_start` | Arbeitspreis und Beginn des nächsten Intervalls |
| `average_working_price_today` / `lowest_working_price_today` / `highest_working_price_today` | Tageskennzahlen des **Arbeitspreises** |
| `basic_fee` / `basic_fee_unit` | Aktuelle Grundgebühr und deren Einheit, direkt aus der API (üblicherweise `EUR/month`). Liefert der Tarif keine Grundgebühr – etwa smartCONTROL –, sind beide `null` |
| `prices_today` / `prices_tomorrow` | **Arbeitspreis**-Vorschau für heute und morgen (`start`, `end`, `price`) |
| `prices_tomorrow_valid` | `true`, sobald die Preise für morgen vorliegen (wie beim Gesamtpreis-Sensor) |
