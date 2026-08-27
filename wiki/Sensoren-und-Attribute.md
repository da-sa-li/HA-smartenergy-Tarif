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
| `sensor.smarttimes_strompreishelfer_preisrang_heute` | Der wievielt-günstigste ist das laufende Intervall unter den heutigen **Gesamtpreisen** (1 = günstigstes) |
| `sensor.smarttimes_strompreishelfer_preisquantil_heute` | Dieselbe Einordnung normiert auf 0–100 % (0 % = günstigstes) |
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

# Preisrang und Preisquantil

Beide Sensoren beantworten dieselbe Frage – *ist der Strom gerade günstig?* – und ersparen die Vorlage, die den aktuellen Preis sonst von Hand gegen Minimum, Maximum und Durchschnitt rechnen müsste. Weil es eigene Entitäten sind, landen sie in der Historie und lassen sich unmittelbar als `numeric_state`-Trigger verwenden.

- **Preisrang** (`…_preisrang_heute`): Der wievielt-günstigste ist das laufende Intervall unter allen Intervallen des heutigen Kalendertages. **1 ist das günstigste.** Dimensionslos.
- **Preisquantil** (`…_preisquantil_heute`): Dieselbe Einordnung normiert auf **0–100 %**, ebenfalls mit **0 % = günstigstes**. Der handlichere der beiden Werte, weil er nicht davon abhängt, ob ein Tag 96 Viertelstunden- oder 24 Stundenwerte hat: „unter 25 %“ heißt immer „im günstigsten Viertel des Tages“.

Bezugsgröße ist der **Gesamtpreis** inklusive aller Nebenkosten – wie bei den Tageskennzahlen und beim Günstige-Stunde-Sensor, und **nicht** der reine Arbeitspreis. Das ist kein Detail: Das SNAP-Fenster verschiebt die Reihenfolge, siehe unten.

Beide stehen auf `unknown`, solange für den aktuellen Zeitpunkt kein Preis vorliegt – etwa kurz nach einem Neustart. Dann fehlen auch die Attribute; ein Attributsatz voller `null` sähe aus wie eine Einordnung, wäre aber keine.

## Preisgleiche Intervalle

Bei **smartTIMES** ist Preisgleichheit der Normalfall, nicht die Ausnahme: Als Zeittarif kennt er nur drei Arbeitspreis-Stufen zu je acht Stunden. Deshalb gilt:

- Der **Rang** folgt der üblichen Wettkampfregel: Alle preisgleichen Intervalle tragen denselben Rang, die nächste Stufe überspringt die verbrauchten Plätze (1, 1, …, 1, 33, …).
- Das **Quantil** teilt eine preisgleiche Gruppe hälftig („Mittelrang“): `(günstigere + gleich teure / 2) / alle`. Dadurch bleibt die Skala symmetrisch – die mittlere von drei gleich großen Stufen liegt auf genau 50 %.

Ohne gewähltes Netzgebiet ergibt ein smartTIMES-Tag damit genau drei Werte:

| Stufe | Intervalle | Rang | Quantil |
|---|---|---|---|
| günstigste | 32 | 1 | 16,67 % |
| mittlere | 32 | 33 | 50,00 % |
| teuerste | 32 | 65 | 83,33 % |

> [!NOTE]
> **Mit** Netzgebiet werden im Sommer mehr Stufen daraus – das ist kein Fehler. Der [SNAP](Netzentgelte-und-Nebenkosten) senkt von April bis September zwischen 10 und 16 Uhr den Netz-Arbeitspreis. Jede der drei Arbeitspreis-Stufen kann innerhalb *und* außerhalb dieses Fensters liegen, es sind also **bis zu sechs** verschiedene Gesamtpreise am Tag möglich. Welche tatsächlich auftreten, hängt am Zonenplan des jeweiligen Tages, den die API liefert – eine feste Zahl gibt es nicht.
>
> Ein Beispiel: Netzgebiet Wien an einem Sommertag, dessen günstigste Arbeitspreis-Stufe die Stunden 02–03 und 10–15 umfasst. Hier fällt das ganze SNAP-Fenster in diese eine Stufe, also entstehen vier Gesamtpreise:
>
> | Gesamtpreis | Intervalle | Rang | Quantil |
> |---|---|---|---|
> | 0,19716 EUR/kWh (10–15 Uhr, SNAP) | 24 | 1 | 12,50 % |
> | 0,21396 EUR/kWh (02–03 Uhr) | 8 | 25 | 29,17 % |
> | 0,23100 EUR/kWh | 32 | 33 | 50,00 % |
> | 0,25932 EUR/kWh | 32 | 65 | 83,33 % |
>
> Nach dem reinen Arbeitspreis wären die ersten beiden Zeilen dieselbe Stufe. Genau darin liegt der Nutzen: Der Rang zeigt, was der Strom *tatsächlich* kostet.

> [!TIP]
> Die Abstände zwischen den Stufen können sehr klein werden, weil sich die SNAP-Ersparnis und der Abstand zweier Arbeitspreis-Stufen fast aufheben können: In Wien liegt „Shoulder im SNAP“ nur 0,00024 EUR/kWh über „Off-Peak außerhalb“ – ein Unterschied in der fünften Nachkommastelle. Rang und Quantil trennen die beiden trotzdem sauber, der Sprung im Rang kann an so einer Stelle also groß sein, obwohl sich am Preis kaum etwas ändert. Wer nach dem Rang schaltet, sollte deshalb im Blick behalten, was ein Rangplatz tatsächlich wert ist; der Gesamtpreis-Sensor sagt das direkt.

Bei **smartCONTROL** stellt sich die Frage kaum – der börsengekoppelte Tarif hat pro Tag fast durchweg verschiedene Preise, üblicherweise vier preisgleiche Viertelstunden je Stunde.

## Attribute

Beide Sensoren tragen **dieselben** Attribute, damit jeder für sich verständlich ist – wer nur das Quantil im Dashboard hat, sieht den Rang trotzdem.

| Attribut | Beschreibung |
|---|---|
| `rank` | Rangplatz des laufenden Intervalls (1 = günstigstes) |
| `quantile_percent` | Quantil in Prozent (0 % = günstigstes) |
| `interval_count` | Nenner der Einordnung: Intervalle des Tages insgesamt (96 an einem vollständigen Viertelstundentag) |
| `cheaper_intervals` | Echt günstigere Intervalle desselben Tages |
| `equal_intervals` | Gleich teure Intervalle, das eigene eingeschlossen – also mindestens 1 |
| `quantile_method` | `midrank`: Ein Preisgleichstand wird hälftig geteilt (siehe oben) |
| `reference` | `total_price`: Verglichen wird der **Gesamtpreis**, nicht der Arbeitspreis |

> [!TIP]
> Ein unvollständiges `interval_count` (unter 96) ist ein Hinweis darauf, dass für den heutigen Tag noch nicht alle Preise vorliegen. Rang und Quantil beziehen sich dann nur auf das, was da ist.

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
