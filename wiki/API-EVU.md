> [!TIP]
> Diese Seite richtet sich an **smartENERGY** als EVU sowie Betreiber der Strompreis-API und nicht an Endanwender der Integration.

# Was ist Home Assistant?

[Home Assistant](https://www.home-assistant.io/) ist eine quelloffene Heimautomatisierungsplattform. Anders als bei einem klassischen Cloud-Dienst betreibt jede Nutzerin und jeder Nutzer eine **eigene, lokale Instanz** – typischerweise auf einem Raspberry Pi oder Mini-PC im eigenen Haushalt. Es gibt keine zentrale Instanz eines Anbieters, die stellvertretend für alle Installationen Daten abruft: Jede Installation ruft die Tarifpreis-API unabhängig und eigenständig auf.

# Was diese Integration tut

**smartENERGY Strompreishelfer** ist eine Community-Integration (installiert über [HACS](https://hacs.xyz/)). Sie bildet je nach Wahl der Nutzerin/des Nutzers **smartTIMES** oder **smartCONTROL** in Home Assistant als Preis-Sensoren ab – inklusive der üblichen variablen Nebenkosten (Steuern, Abgaben, Netzentgelte). Zusätzlich stellt sie je Verbraucher einen „Günstige Stunde“-Sensor bereit, den Nutzerinnen und Nutzer typischerweise per Automatisierung nutzen, um Lasten wie Boiler oder Wallbox gezielt in günstige Preisfenster zu schalten.

## Lastglättung der „Günstige Stunde“-Sensoren

Viele unabhängige Home-Assistant-Instanzen folgen demselben öffentlichen Preissignal. Um eine synchronisierte Lastspitze zu vermeiden, wirkt die Integration clientseitig entgegen (`custom_components/smartenergy/jitter.py`):

- Jeder „Günstige Stunde“-Sensor verschiebt seine Schaltflanken um einen **deterministischen, aus der (nutzerseitig nicht editierbaren) Subentry-ID abgeleiteten Versatz** (SHA-256-Hash, Funktion `cheap_phase`). Der Versatz wirkt pseudozufällig, ist aber stabil – kein Flackern bei der minütlichen Neuberechnung – und über viele Sensoren hinweg gleichverteilt.
- **Einschalten**: gleichverteilte Verzögerung von 0–10 Minuten (Konstante `JITTER_ON_MAX_SECONDS`) nach Beginn des günstigen Zeitfensters, nie davor.
- **Ausschalten**: symmetrischer Versatz von ±5 Minuten (Konstante `JITTER_OFF_SPAN_SECONDS`) um das Fensterende, berechnet in `jittered_window`. Bei einem gleichstandsbedingt verlängerten Fenster (Gleichstand am Schwellwert, Parameter `soft_end`) schaltet die Last stattdessen immer **vor oder auf** der Fenstergrenze ab, um nicht zusätzlich in die nächste, teurere Preiszone hineinzulaufen.
- Dadurch rampt die aggregierte Nachfrage vieler Haushalte über ein rund zehnminütiges Fenster statt als Sprungfunktion zur vollen Stunde bzw. Fenstergrenze – jeder einzelne Sensor bleibt für sich genommen deterministisch und reproduzierbar.

Die Glättung passiert vollständig lokal in Home Assistant: Weder smartENERGY noch der Maintainer dieser Integration erhalten eine Rückmeldung, welche Haushalte wann tatsächlich schalten (siehe [Datenschutz](Datenschutz)).

# Anfragemuster

Weil jede Home-Assistant-Instanz unabhängig und lokal läuft, kommt der Traffic dieser Integration von vielen verschiedenen, üblicherweise privaten IP-Adressen verteilt über den Tag – nicht konzentriert von einem zentralen Server. Gesteuert wird das über `custom_components/smartenergy/coordinator.py` (`_needs_fetch`, `_retry_delay`, `_fetch_allowed`). Pro Instanz gilt:

- **~1 Abruf pro Tag**, plus ein einmaliger Abruf beim Start von Home Assistant.
- Die Morgen-Preise für den Folgetag werden **ab 17 Uhr** (Konstante `NEXT_DAY_PRICES_HOUR`) abgerufen, mit einem deterministischen, aus der Entry-ID und dem Kalendertag abgeleiteten **Jitter über ein 20-Minuten-Fenster** (`FETCH_JITTER_MINUTES`) – so entsteht keine Lastspitze exakt zur vollen Stunde.
- **Retry bei Fehlern**: Der erste erneute Versuch erfolgt nach 30 Minuten (`FETCH_RETRY_INTERVAL_MINUTES`), danach verdoppelt sich die Wartezeit bei jedem weiteren Fehlschlag bis maximal 2 Stunden (`FETCH_RETRY_MAX_INTERVAL_MINUTES`). Ein `Retry-After`-Header wird respektiert, sofern er länger ist als die eigene Wartezeit. Eine dauerhafte Ablehnung (4xx außer 408/429) wird **nicht** in kurzen Abständen erneut versucht, sondern springt sofort auf das Maximal-Intervall.
- Ein **hartes Sicherheitsnetz** (Konstante `MIN_FETCH_INTERVAL_MINUTES`) verhindert unabhängig davon, dass zwei echte Abrufe derselben Instanz jemals weniger als 5 Minuten auseinander liegen.
- Schlägt ein Abruf fehl, bleiben zuvor abgerufene Preise im lokalen Cache erhalten – es gibt also keinen "Retry-Sturm" bei einer länger andauernden Störung.

## User-Agent

Jede Anfrage trägt einen aussagekräftigen `User-Agent`-Header nach dem Schema (aufgebaut in `custom_components/smartenergy/api.py`, Funktion `_build_user_agent`):

```
HomeAssistant-Strompreishelfer/<Version> (+<Link auf diese Seite>)
```

Beispiel: `HomeAssistant-Strompreishelfer/2.1.2 (+https://github.com/da-sa-li/HA-smartenergy-Tarif/wiki/API-EVU)`

Damit lässt sich der Traffic dieser Integration in den Server-Logs eindeutig von anderem Traffic unterscheiden.

> [!IMPORTANT]
> Bei Auffälligkeiten (Rate-Limiting, Blocking, Fragen zum Traffic-Muster) bitte über ein [GitHub Issue](https://github.com/da-sa-li/HA-smartenergy-Tarif/issues) melden.
