Der Abruf ist **rein lesend** und kommt ohne Konto und API-Schlüssel aus.

# Was die Integration abruft

Sie ruft ausschließlich die öffentliche Tarifpreis-API von smartENERGY ab – je nach gewähltem Tarif [smartTIMES](https://www.smartenergy.at/api-schnittstellen-smarttimes) oder [smartCONTROL](https://www.smartenergy.at/api-schnittstellen). Das geschieht etwa **einmal täglich** (Details zur Abruf-Frequenz und Retry-Logik siehe [Fehlerbehebung](Fehlerbehebung)).

Übertragen wird dabei nur, was jede Web-Anfrage zwangsläufig mit sich bringt:

- IP-Adresse
- User-Agent
- Zeitpunkt der Anfrage

# Was Home Assistant nicht verlässt

- **Verbrauchsdaten** – die Integration liest keine Verbrauchswerte, sie stellt nur Preise bereit.
- **Sensornamen** – frei vergebene Namen (z. B. „Boiler“, „Wallbox“) bleiben lokal.
- **Gewähltes Netzgebiet** – wird nur lokal zur Berechnung der Netzentgelte verwendet und **nicht** an die API übertragen. In der Diagnose-Datei ist es allerdings enthalten (siehe unten).

Nebenkosten, Gesamtpreis und die Auswahl der günstigen Stunden werden **vollständig lokal** in Home Assistant berechnet (siehe [Netzentgelte und Nebenkosten](Netzentgelte-und-Nebenkosten)). Es findet keine Übertragung an Drittserver statt, und die Integration erhebt **keine Telemetrie**, weder für den Maintainer, noch für smartENERGY.

# Diagnose-Dateien

Diagnose-Dateien (**Einstellungen → Geräte & Dienste → smartENERGY Strompreishelfer → Diagnose herunterladen**) enthalten **keine frei vergebenen Sensornamen** und lassen sich daher unverändert an ein [GitHub-Issue](https://github.com/da-sa-li/HA-smartenergy-Tarif/issues) anhängen.

Enthalten ist dagegen bewusst das **gewählte Netzgebiet** – ohne diese Angabe lässt sich ein gemeldeter Gesamtpreis nicht nachrechnen. Es benennt eine grobe Versorgungsregion (z. B. „Wien“ oder „Steiermark“), keine Adresse.
