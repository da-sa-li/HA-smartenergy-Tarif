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
