Der **Gesamtpreis**-Sensor (`…_gesamtpreis`) addiert zum reinen Arbeitspreis alle in Österreich anfallenden variablen Nebenkosten. Diese Seite erklärt, woraus sich der Gesamtpreis zusammensetzt.

> Alle Nebenkosten werden **netto** verrechnet; die **USt. (20 %)** wird einmal am Ende auf die **Summe** angewendet – nicht auf jede Position einzeln.

# Bundeseinheitliche Steuern und Abgaben

| Position | Satz (netto) | Hinweis |
|---|---|---|
| [Elektrizitätsabgabe](https://www.usp.gv.at/themen/steuern-finanzen/weitere-steuern-und-abgaben/verbrauchsteuern_und_energieabgaben/elektrizitaetsabgabe.html) | 1,5 ct/kWh (:label: **bis 31.12.2026 auf 0,1 ct/kWh gesenkt**, ab 01.01.2027 wieder Regelsatz) | Elektrizitätsabgabegesetz, BGBl. Nr. 201/1996 |
| [Erneuerbaren-Förderbeitrag](https://www.e-control.at/konsumenten/oekostrom-foerdersystem) | 0,62 ct/kWh | Erneuerbaren-Förderbeitragsverordnung 2026, BGBl. II Nr. 301/2025 |

Diese Sätze gelten unabhängig vom Netzgebiet und sind in der Integration als datierte Tabelle hinterlegt – künftige Satzänderungen (z. B. die Elektrizitätsabgabe ab 2027) greifen automatisch, ohne dass ein Integrations-Update nötig ist.

# Netzgebietsabhängige Netzentgelte

Für das bei der Einrichtung gewählte **Netzgebiet** werden die per-kWh-[Netzentgelte](https://www.e-control.at/industrie/strom/strompreis/systemnutzungsentgelte) auf **Netzebene 7** mit **Viertelstundenmessung (IME)** in der Tarifvariante **ohne Leistungsmessung** („nicht gemessene Leistung“) berücksichtigt:

- **Netznutzungsentgelt-Arbeitspreis** (normal bzw. im SNAP-Fenster reduziert)
- **Netzverlustentgelt** (konstant)

„Kein Netzgebiet“ lässt beide Positionen weg. Das korrekte Netzgebiet steht im **Netzzugangsvertrag** des Netzbetreibers.

## :label: Sommer-Nieder-Arbeitspreis (SNAP)

Der **[Sommer-Nieder-Arbeitspreis (SNAP)](https://www.e-control.at/sommer-nieder-arbeitspreis)** senkt den Netz-Arbeitspreis vom **1. April bis 30. September**, täglich von **10:00–16:00 Uhr**, um **20 %**. Das Attribut `snap_active` am Gesamtpreis-Sensor zeigt, ob er gerade gilt.

> Der **Netznutzungs-Leistungspreis** (Kapazitätsentgelt, €/kW nach Spitzenlast) wird **nicht** eingerechnet – er ist keine ct/kWh-Größe.

# smartCONTROL: Abwicklungsgebühr

Bei **smartCONTROL** kommt zusätzlich die **Abwicklungsgebühr** (1,2 ct/kWh netto / 1,44 ct/kWh brutto) hinzu. Sie folgt derselben Netto-Konvention und erscheint als eigene Position `handling_fee`.

# smartNIGHT: Peak-Aufschlag

Bei **smartNIGHT** liegt der Arbeitspreis von **07:00 bis 23:00 Uhr** um **30 %** über dem Off-Peak-Preis; außerhalb dieses Fensters gilt der Off-Peak-Preis von smartTIMES. Der Aufschlag trifft ausschließlich den **Arbeitspreis** – Abgaben und Netzentgelte samt SNAP gelten unverändert und erscheinen daher auch nicht als eigene Position in der Aufschlüsselung. Eine Abwicklungsgebühr gibt es bei smartNIGHT nicht.

> Das SNAP-Fenster (10:00–16:00 Uhr) liegt vollständig innerhalb der Peak-Zeit. In Netzgebieten mit hohem Netz-Arbeitspreis kann die SNAP-Ermäßigung den Peak-Aufschlag daher übersteigen – dann ist der Sommermittag günstiger als die Nacht. Der „Günstige Stunde“-Sensor richtet sich nach dem **Gesamtpreis** und bildet das automatisch ab.

# Aufschlüsselung als Sensor-Attribute

Der Gesamtpreis-Sensor liefert die Zusammensetzung zusätzlich als Attribute (`working_price_eur_kwh`, `surcharges_eur_kwh`, `surcharges_total_eur_kwh`, `total_eur_kwh`, …) – die vollständige Referenz steht unter [Sensoren und Attribute](Sensoren-und-Attribute#gesamtpreis-sensor). Alle Attribute sind in **EUR/kWh** angegeben; die ct/kWh dieser Seite sind die Einheit, in der die Tarifblätter und die API rechnen.

# Jährliche Aktualisierung

Netzentgelte (und der Förderbeitrag) ändern sich **jährlich**. Die in der Integration hinterlegten Werte sind **„Stand 2026“** – bei Änderungen zum Jahreswechsel braucht es ein Integrations-Update.
