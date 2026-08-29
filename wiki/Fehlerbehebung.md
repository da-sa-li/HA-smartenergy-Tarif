# Preiszeiten oder SNAP-Fenster verrutschen

Home Assistant muss auf die Zeitzone **`Europe/Vienna`** eingestellt sein (**Einstellungen → System → Allgemein → Zeitzone**). smartTIMES liefert lokale Zeitstempel ohne Offset – steht HA auf einer anderen Zeitzone, verschieben sich die Preisintervalle und das **SNAP-Fenster** (10:00–16:00 Uhr) entsprechend.

# Keine Preise / Sensor zeigt `unknown`

Die Integration ruft die Preis-API nur etwa **einmal täglich** ab (die Morgen-Preise ab 17 Uhr, je nach Instanz bis etwa 17:20 – der Abruf ist bewusst über ein 20-Minuten-Fenster gestreut, damit nicht alle Instanzen gleichzeitig anfragen) und rechnet die Anzeige minütlich aus dem **Cache** neu. Ist die API beim Abruf kurz nicht erreichbar, bleiben die zuletzt gecachten Preise erhalten und es greift eine **Retry-Logik**, die den Abruf automatisch wiederholt – zunächst nach 30 Minuten, danach mit jeweils verdoppeltem Abstand bis höchstens 2 Stunden. So belastet auch eine länger andauernde Störung die API nicht unnötig.

- **Direkt nach der Einrichtung** kann es einen Moment dauern, bis der erste erfolgreiche Abruf erfolgt ist – danach füllt sich der Sensor.
- **Bleibt der Sensor länger `unknown`**, die Internet-Verbindung prüfen und ggf. Home Assistant neu starten. Details stehen im HA-Protokoll (**Einstellungen → System → Protokolle**).
- **Die Sensoren werden dabei nicht `unavailable`.** Solange der Cache Preise
  enthält, gelten sie als verfügbar; erst wenn die gecachten Preise den
  aktuellen Zeitpunkt nicht mehr abdecken, melden sie `unknown`. Das ist
  Absicht – ein Preisplan bleibt brauchbar, solange er reicht. Eine
  Automatisierung, die auf `unavailable` prüft, greift hier also nicht; sie
  muss auf `unknown` prüfen. Hält die Störung an, erscheint nach 36 Stunden
  zusätzlich eine Meldung unter „Reparaturen“.
- **Sofort neu abrufen**, ohne auf den nächsten geplanten Abruf zu warten: beim Eintrag der Integration das **Drei-Punkte-Menü → Neu laden** wählen. Das baut die Integration neu auf und holt die Preise unmittelbar. Ein eigener Dienst dafür fehlt bewusst – er müsste genau die Drosselung umgehen, die die kostenlos bereitgestellte API schont.

# Der Sensor schaltet nicht zur vollen Stunde

Das ist Absicht und kein Fehler. Würden alle Haushalte mit dieser Integration ihre Verbraucher zur selben Sekunde zuschalten, entstünde genau die Lastspitze, die dynamische Tarife eigentlich vermeiden sollen. Jeder „Günstige Stunde“-Sensor verschiebt seine Schaltflanken deshalb um einen kleinen Versatz von **bis zu 10 Minuten**.

Der Versatz wandert dabei **nach innen**: eingeschaltet wird etwas *später* als der günstige Block beginnt, ausgeschaltet entsprechend *früher* als er endet. Das Schaltfenster liegt damit immer vollständig im günstigen Block – der Verbraucher läuft nie in die teurere Zone hinein. Der Preis dafür sind 10 Minuten Laufzeit je Block.

Der Versatz ist aus der ID des Untereintrags abgeleitet und damit **je Sensor konstant** – er wandert nicht von Tag zu Tag. Nachsehen lässt er sich im Attribut `jitter_offset_seconds` des Sensors (**Entwicklerwerkzeuge → Zustände**); der tatsächliche nächste Einschaltzeitpunkt steht in `next_cheap_start`. Mehr dazu unter [Sensoren und Attribute](Sensoren-und-Attribute#binary-sensor-günstige-stunde).

# Falsche Gesamtkosten

Stimmt der Gesamtpreis nicht mit der Abrechnung überein, ist meist das **Netzgebiet** nicht oder falsch gewählt – davon hängen die Netzentgelte ab (siehe [Netzentgelte und Nebenkosten](Netzentgelte-und-Nebenkosten)). Das korrekte Netzgebiet steht im **Netzzugangsvertrag** des Netzbetreibers und lässt sich über **Konfigurieren** jederzeit anpassen. „Kein Netzgebiet“ lässt die Netzentgelte ganz weg, der Gesamtpreis fällt dann zu niedrig aus.

# Preise für morgen fehlen

Der Diagnose-Sensor **Preise für morgen verfügbar** zeigt, ob die Preise des
Folgetags schon eingetroffen sind. Sein Attribut `expected_after` nennt den
Zeitpunkt, ab dem die Integration sie erwartet – 17 Uhr Ortszeit zuzüglich eines
kleinen, je Installation verschiedenen Abruf-Versatzes von bis zu 20 Minuten.

* **Vor dieser Zeit ist `off` der Normalzustand** – die Preise sind schlicht
  noch nicht veröffentlicht, es ist nichts zu tun.
* **Danach anhaltend `off`** deutet auf eine Störung beim Anbieter hin. Die
  Integration versucht es in wachsenden Abständen erneut; hält der Fehler über
  Stunden an, erscheint zusätzlich eine Meldung unter „Reparaturen“.

Das Attribut `price_count` nennt die Zahl der bereits vorliegenden Intervalle –
ein vollständiger Tag sind 96 Viertelstunden.

Der Sensor steht unter **Diagnose** auf der Geräteseite des Strompreishelfers.

# Meldungen unter „Reparaturen“

Die Integration meldet zwei Zustände als Reparatur-Hinweis (**Einstellungen → System → Reparaturen**):

- **Tarifdaten veraltet** – Netzentgelte und Förderbeitrag sind mit Jahresangabe hinterlegt; sobald das laufende Jahr darüber hinausgeht, stimmen die Nebenkosten nicht mehr. Abhilfe schafft ein Update der Integration, siehe [Netzentgelte und Nebenkosten](Netzentgelte-und-Nebenkosten).
- **Abruf dauerhaft fehlgeschlagen** – seit mehr als 36 Stunden kam kein Abruf durch. Die angezeigten Preise stammen dann aus dem Cache und sind vermutlich veraltet.

# Debug-Logging einschalten

Reicht das normale Protokoll nicht, lässt sich für die Integration ausführliches Logging einschalten – in der `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.smartenergy: debug
```

Nach einem Neustart von Home Assistant stehen die Meldungen unter **Einstellungen → System → Protokolle**. Das `custom_components.`-Präfix gehört dazu; ohne es greift die Einstellung nicht.

> [!TIP]
> Für einen Fehlerbericht ist **Diagnose herunterladen** meist der schnellere Weg (Drei-Punkte-Menü beim Eintrag der Integration): Die Datei enthält Konfiguration, Cache-Zustand und das aktuelle Preisintervall, ohne dass Debug-Logging nötig wäre – und ohne die selbst vergebenen Sensornamen (siehe [Datenschutz](Datenschutz)).
