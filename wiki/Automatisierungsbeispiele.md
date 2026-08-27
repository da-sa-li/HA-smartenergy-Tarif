# Verbraucher in günstigen Stunden schalten

Den „Günstige Stunde“-Binary-Sensor als Auslöser nutzen, um einen Verbraucher
(z. B. Boiler oder Wallbox) genau dann ein- bzw. auszuschalten, wenn der
Sensor nach `on` bzw. `off` wechselt:

```yaml
automation:
  - triggers:
      - trigger: state
        entity_id: binary_sensor.boiler_gunstige_stunde
        to: ["on", "off"]
    actions:
      - action: "switch.turn_{{ trigger.to_state.state }}"
        target: { entity_id: switch.boiler }
```

> Den Entitäts-Namen (`binary_sensor.<name>_gunstige_stunde`) an den eigenen
> Untereintrag anpassen. Die Last-Glättung (Jitter) verschiebt die
> Schaltflanken automatisch um einen kleinen, je Sensor stabilen Versatz –
> die Automatisierung muss nichts weiter berücksichtigen. Details dazu unter
> [Sensoren und Attribute](Sensoren-und-Attribute#binary-sensor-günstige-stunde).

> [!IMPORTANT]
> Das `to: ["on", "off"]` ist wichtig. Liegt für den aktuellen Zeitpunkt kein
> Preis vor – etwa kurz nach einem Neustart oder wenn ein Abruf ausgefallen
> ist –, meldet der Sensor `unknown`, beim Neuladen kurzzeitig `unavailable`.
> Ohne den Filter feuert die Automatisierung auch auf diese Übergänge und
> schaltet den Verbraucher dann ab, obwohl gar keine Aussage vorliegt.

# Vor dem günstigen Fenster vorheizen

Der Sensor **Nächster günstiger Start** ist ein Zeitstempel und lässt sich
deshalb direkt als `at:` eines `time`-Triggers verwenden – mit `offset` auch
mit Vorlauf. Damit läuft der Boiler nicht erst *ab* dem günstigen Fenster an,
sondern ist dann schon warm:

```yaml
automation:
  - triggers:
      - trigger: time
        at:
          entity_id: sensor.boiler_nachster_gunstiger_start
          offset: "-00:30:00"
    actions:
      - action: switch.turn_on
        target: { entity_id: switch.boiler_vorheizen }
```

> [!NOTE]
> Steht der Sensor auf `unknown` – spät abends, bevor die Preise für den
> Folgetag veröffentlicht sind –, feuert der Trigger einfach nicht. Das ist
> der gewünschte Fall: Lieber gar nicht vorheizen als zur falschen Zeit.
> Ein `to:`-Filter wie beim Zustands-Trigger oben ist hier nicht nötig.

# Tagesplan neu rechnen, sobald die Morgenpreise da sind

Der Diagnose-Sensor **Preise für morgen verfügbar** schaltet auf `on`, sobald
die Preise des Folgetags eingetroffen sind (laut API-Zusage ab 17 Uhr). Das ist
der passende Auslöser für alles, was auf den Preisen von morgen aufbaut – etwa
eine Benachrichtigung mit dem günstigsten Fenster:

```yaml
automation:
  - triggers:
      - trigger: state
        entity_id: binary_sensor.smarttimes_strompreishelfer_preise_fur_morgen_verfugbar
        to: "on"
    actions:
      - action: notify.persistent_notification
        data:
          message: >-
            Günstigstes Fenster morgen ab
            {{ states('sensor.boiler_nachster_gunstiger_start') | as_timestamp
               | timestamp_custom('%H:%M') }}
```

> Ohne diesen Sensor ließe sich „noch nicht veröffentlicht“ nicht von „keine
> Preise“ unterscheiden: Das Attribut `prices_tomorrow` ist in beiden Fällen
> eine leere Liste.

# Verbraucher starten, wenn der Preis im günstigsten Viertel liegt

Das **Preisquantil** ordnet den laufenden Preis in den heutigen Tag ein, mit
0 % für das günstigste Intervall. Damit reicht ein numerischer Trigger, wo
sonst ein Template-Sensor den aktuellen Preis erst gegen die Tageskennzahlen
rechnen müsste:

```yaml
automation:
  - triggers:
      - trigger: numeric_state
        entity_id: sensor.smarttimes_strompreishelfer_preisquantil_heute
        below: 25
    actions:
      - action: switch.turn_on
        target: { entity_id: switch.boiler }
```

> Die Schwelle ist frei wählbar: `below: 25` heißt „im günstigsten Viertel des
> Tages“, `below: 10` entsprechend strenger. Weil das Quantil normiert ist,
> bedeutet derselbe Wert bei jedem Tarif dasselbe – anders als eine Schwelle in
> EUR/kWh, die bei jeder Preisänderung nachgezogen werden müsste.

> [!IMPORTANT]
> Liegt für den aktuellen Zeitpunkt kein Preis vor, steht der Sensor auf
> `unknown`. Ein `numeric_state`-Trigger feuert darauf nicht – anders als ein
> Zustands-Trigger, der ohne `to:`-Filter auch auf `unknown` anspringen würde.
> Wer den Verbraucher am Ende des günstigen Fensters wieder abschalten will,
> nimmt einen zweiten Trigger mit `above: 25`.

> [!NOTE]
> Für einen Verbraucher mit einer festen Laufzeit („vier Stunden am Tag“) ist
> der **Günstige Stunde**-Binary-Sensor die bessere Wahl: Er wählt die Fenster
> vorausschauend für den ganzen Tag und glättet die Last. Das Quantil eignet
> sich für Verbraucher, die jederzeit mitlaufen können, wenn es gerade billig
> ist. Bei **smartTIMES** ist zu bedenken, dass es als Zeittarif nur wenige
> Preisstufen gibt – das Quantil nimmt dort nur drei bis vier verschiedene
> Werte am Tag an, siehe
> [Sensoren und Attribute](Sensoren-und-Attribute#preisrang-und-preisquantil).

# Gesamtpreis im Energie-Dashboard hinterlegen

Der `…_gesamtpreis`-Sensor liefert den Preis bereits in **EUR/kWh**
inkl. aller variablen Nebenkosten und eignet sich damit direkt als
Preis-Entität fürs Energie-Dashboard:

1. **Einstellungen → Dashboards → Energie** öffnen.
2. Beim **Netzstromverbrauch** die verbrauchsmessende Entität wählen und
   unter **Kosten** die Option **Entität mit aktuellem Preis verwenden**
   aktivieren.
3. Als Preis-Entität `sensor.smarttimes_strompreishelfer_gesamtpreis`
   (bzw. `smartcontrol_…`) auswählen.

So rechnet Home Assistant die tatsächlichen Stromkosten dynamisch mit dem
jeweils gültigen Gesamtpreis ab.

> [!NOTE]
> Vor Version 4.0.0 hieß der Sensor `…_gesamtpreis_eur_kwh`. Das Update
> benennt ihn bei bestehenden Installationen um – wer die alte Entity-ID in
> Automatisierungen, Vorlagen oder Dashboards stehen hat, muss sie anpassen.
