# Automatisierungsbeispiele

## Verbraucher in günstigen Stunden schalten

Den „Günstige Stunde“-Binary-Sensor als Auslöser nutzen, um einen Verbraucher
(z. B. Boiler oder Wallbox) genau dann ein- bzw. auszuschalten, wenn der
Sensor nach `on` bzw. `off` wechselt:

```yaml
automation:
  - trigger:
      - platform: state
        entity_id: binary_sensor.boiler_gunstige_stunde
    action:
      - service: "switch.turn_{{ 'on' if trigger.to_state.state == 'on' else 'off' }}"
        target: { entity_id: switch.boiler }
```

> Den Entitäts-Namen (`binary_sensor.<name>_gunstige_stunde`) an den eigenen
> Untereintrag anpassen. Die Last-Glättung (Jitter) verschiebt die
> Schaltflanken automatisch um einen kleinen, je Sensor stabilen Versatz –
> die Automatisierung muss nichts weiter berücksichtigen. Details dazu unter
> [Sensoren und Attribute](Sensoren-und-Attribute#binary-sensor-günstige-stunde).

## Gesamtpreis im Energie-Dashboard hinterlegen

Der `…_gesamtpreis_eur_kwh`-Sensor liefert den Preis bereits in **EUR/kWh**
inkl. aller variablen Nebenkosten und eignet sich damit direkt als
Preis-Entität fürs Energie-Dashboard:

1. **Einstellungen → Dashboards → Energie** öffnen.
2. Beim **Netzstromverbrauch** die verbrauchsmessende Entität wählen und
   unter **Kosten** die Option **Entität mit aktuellem Preis verwenden**
   aktivieren.
3. Als Preis-Entität `sensor.smarttimes_strompreishelfer_gesamtpreis_eur_kwh`
   (bzw. `smartcontrol_…`) auswählen.

So rechnet Home Assistant die tatsächlichen Stromkosten dynamisch mit dem
jeweils gültigen Gesamtpreis ab.
