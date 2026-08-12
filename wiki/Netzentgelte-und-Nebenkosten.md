# Netzentgelte und Nebenkosten

Der **Gesamtpreis**-Sensor (`…_gesamtpreis_eur_kwh`) addiert zum reinen
Arbeitspreis alle in Österreich anfallenden variablen Nebenkosten. Diese
Seite erklärt, woraus sich der Gesamtpreis zusammensetzt.

> Alle Nebenkosten werden **netto** verrechnet; die **USt. (20 %)** wird
> einmal am Ende auf die **Summe** angewendet – nicht auf jede Position
> einzeln.

## Bundeseinheitliche Steuern und Abgaben

| Position | Satz (netto) | Hinweis |
|---|---|---|
| [Elektrizitätsabgabe](https://www.usp.gv.at/themen/steuern-finanzen/weitere-steuern-und-abgaben/verbrauchsteuern_und_energieabgaben/elektrizitaetsabgabe.html) | 1,5 ct/kWh | **bis 31.12.2026 auf 0,1 ct/kWh gesenkt**, ab 01.01.2027 wieder Regelsatz |
| [Erneuerbaren-Förderbeitrag](https://www.e-control.at/konsumenten/oekostrom-foerdersystem) | 0,62 ct/kWh | Verordnung 2026 (Variante ohne Leistungsmessung); 2022–2024 ausgesetzt, seit 2025 wieder aktiv |

Diese Sätze gelten unabhängig vom Netzgebiet und sind in der Integration als
datierte Tabelle hinterlegt – künftige Satzänderungen (z. B. die
Elektrizitätsabgabe ab 2027) greifen automatisch, ohne dass ein
Integrations-Update nötig ist.

## Netzgebietsabhängige Netzentgelte

Für das bei der Einrichtung gewählte **Netzgebiet** werden die
per-kWh-[Netzentgelte](https://www.e-control.at/industrie/strom/strompreis/systemnutzungsentgelte)
auf **Netzebene 7** mit **Viertelstundenmessung (IME)** in der Tarifvariante
**ohne Leistungsmessung** („nicht gemessene Leistung“) berücksichtigt:

- **Netznutzungsentgelt-Arbeitspreis** (normal bzw. im SNAP-Fenster reduziert)
- **Netzverlustentgelt** (konstant)

„Kein Netzgebiet“ lässt beide Positionen weg – der Gesamtpreis fällt dann zu
niedrig aus. Das korrekte Netzgebiet steht im **Netzzugangsvertrag** des
Netzbetreibers.

### Sommer-Nieder-Arbeitspreis (SNAP)

Der **[Sommer-Nieder-Arbeitspreis
(SNAP)](https://www.e-control.at/sommer-nieder-arbeitspreis)** senkt den
Netz-Arbeitspreis vom **1. April bis 30. September**, täglich von
**10:00–16:00 Uhr**, um **20 %**. Das Attribut `snap_active` am
Gesamtpreis-Sensor zeigt, ob er gerade gilt.

> Der **Netznutzungs-Leistungspreis** (Kapazitätsentgelt, €/kW nach
> Spitzenlast) wird **nicht** eingerechnet – er ist keine ct/kWh-Größe.

## smartCONTROL: Abwicklungsgebühr

Bei **smartCONTROL** kommt zusätzlich die **Abwicklungsgebühr** (1,2 ct/kWh
netto / 1,44 ct/kWh brutto) hinzu. Sie folgt derselben Netto-Konvention und
erscheint als eigene Position `handling_fee`.

## Aufschlüsselung als Sensor-Attribute

Der Gesamtpreis-Sensor liefert die Zusammensetzung zusätzlich als Attribute
(`working_price_ct_kwh`, `surcharges_ct_kwh`, `surcharges_total_ct_kwh`, …) –
die vollständige Referenz steht unter [Sensoren und
Attribute](Sensoren-und-Attribute#gesamtpreis-sensor).

## Jährliche Aktualisierung

Netzentgelte (und der Förderbeitrag) ändern sich **jährlich**. Die in der
Integration hinterlegten Werte sind **„Stand 2026“** – bei Änderungen zum
Jahreswechsel braucht es ein Integrations-Update.
