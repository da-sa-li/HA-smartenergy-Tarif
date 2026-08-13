# Hinweise für den API-Betreiber

Diese Seite richtet sich an den **Betreiber der smartENERGY-Tarifpreis-API** – nicht an Endanwender der
Integration.

> Community-Projekt, keine Verbindung zu smartENERGY oder der Energie Steiermark Kunden GmbH.

## Was ist Home Assistant?

[Home Assistant](https://www.home-assistant.io/) ist eine quelloffene Heimautomatisierungsplattform. Anders als bei einem klassischen Cloud-Dienst betreibt jede Nutzerin und jeder Nutzer eine **eigene, lokale Instanz** – typischerweise auf einem Raspberry Pi oder Mini-PC im eigenen Haushalt. Es gibt keine zentrale Instanz eines Anbieters, die stellvertretend für alle Installationen Daten abruft: Jede Installation ruft die Tarifpreis-API unabhängig und eigenständig auf.

## Was diese Integration tut

**smartENERGY Strompreishelfer** ist eine Community-Integration (installiert über [HACS](https://hacs.xyz/)), kein offizielles smartENERGY-Produkt. Sie bildet je nach Wahl der Nutzerin/des Nutzers **smartTIMES** oder **smartCONTROL** in Home Assistant als Preis-Sensoren ab – inklusive der üblichen variablen Nebenkosten (Steuern, Abgaben, Netzentgelte).

## Anfragemuster

Weil jede Home-Assistant-Instanz unabhängig und lokal läuft, kommt der Traffic dieser Integration von vielen verschiedenen, üblicherweise privaten IP-Adressen verteilt über den Tag – nicht konzentriert von einem zentralen Server. Pro Instanz gilt:

- **~1 Abruf pro Tag**, plus ein einmaliger Abruf beim Start von Home Assistant.
- Die Morgen-Preise für den Folgetag werden **ab 17 Uhr** abgerufen, mit einem deterministischen, aus der Konfiguration abgeleiteten **Jitter über ein 20-Minuten-Fenster** – so entsteht keine Lastspitze exakt zur vollen Stunde.
- **Retry bei Fehlern**: Der erste erneute Versuch erfolgt nach 30 Minuten, danach verdoppelt sich die Wartezeit bei jedem weiteren Fehlschlag bis maximal 2 Stunden. Ein `Retry-After`-Header wird respektiert, sofern er länger ist als die eigene Wartezeit. Eine dauerhafte Ablehnung (4xx außer 408/429) wird **nicht** in kurzen Abständen erneut versucht, sondern springt sofort auf das Maximal-Intervall.
- Ein **hartes Sicherheitsnetz** verhindert unabhängig davon, dass zwei echte Abrufe derselben Instanz jemals weniger als 5 Minuten auseinander liegen.
- Schlägt ein Abruf fehl, bleiben zuvor abgerufene Preise im lokalen Cache erhalten – es gibt also keinen "Retry-Sturm" bei einer länger andauernden Störung.

## User-Agent

Jede Anfrage trägt einen aussagekräftigen `User-Agent`-Header nach dem Schema:

```
HomeAssistant-Strompreishelfer/<Version> (+<Link auf diese Seite>)
```

Beispiel: `HomeAssistant-Strompreishelfer/2.1.2 (+https://github.com/da-sa-li/HA-smartenergy-Tarif/wiki/API-Betreiber)`

Damit lässt sich der Traffic dieser Integration in den Server-Logs eindeutig von anderem Traffic unterscheiden.

## Kontakt

Bei Auffälligkeiten (Rate-Limiting, Blocking, Fragen zum Traffic-Muster) bitte über ein [GitHub Issue](https://github.com/da-sa-li/HA-smartenergy-Tarif/issues) melden.
