# Preiszeiten oder SNAP-Fenster verrutschen

Home Assistant muss auf die Zeitzone **`Europe/Vienna`** eingestellt sein (**Einstellungen → System → Allgemein → Zeitzone**). smartTIMES liefert lokale Zeitstempel ohne Offset – steht HA auf einer anderen Zeitzone, verschieben sich die Preisintervalle und das **SNAP-Fenster** (10:00–16:00 Uhr) entsprechend.

# Keine Preise / Sensor zeigt `unknown`

Die Integration ruft die Preis-API nur etwa **einmal täglich** ab (die Morgen-Preise ab 17 Uhr, je nach Instanz bis etwa 17:20 – der Abruf ist bewusst über ein 20-Minuten-Fenster gestreut, damit nicht alle Instanzen gleichzeitig anfragen) und rechnet die Anzeige minütlich aus dem **Cache** neu. Ist die API beim Abruf kurz nicht erreichbar, bleiben die zuletzt gecachten Preise erhalten und es greift eine **Retry-Logik**, die den Abruf automatisch wiederholt – zunächst nach 30 Minuten, danach mit jeweils verdoppeltem Abstand bis höchstens 2 Stunden. So belastet auch eine länger andauernde Störung die API nicht unnötig.

- **Direkt nach der Einrichtung** kann es einen Moment dauern, bis der erste erfolgreiche Abruf erfolgt ist – danach füllt sich der Sensor.
- **Bleibt der Sensor länger `unknown`**, die Internet-Verbindung prüfen und ggf. Home Assistant neu starten. Details stehen im HA-Protokoll (**Einstellungen → System → Protokolle**).

# Falsche Gesamtkosten

Stimmt der Gesamtpreis nicht mit der Abrechnung überein, ist meist das **Netzgebiet** nicht oder falsch gewählt – davon hängen die Netzentgelte ab (siehe [Netzentgelte und Nebenkosten](Netzentgelte-und-Nebenkosten)). Das korrekte Netzgebiet steht im **Netzzugangsvertrag** des Netzbetreibers und lässt sich über **Konfigurieren** jederzeit anpassen. „Kein Netzgebiet“ lässt die Netzentgelte ganz weg, der Gesamtpreis fällt dann zu niedrig aus.
