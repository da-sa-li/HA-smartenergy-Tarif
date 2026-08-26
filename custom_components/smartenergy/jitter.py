"""Deterministischer Zeit-Jitter für die „Günstige Stunde“-Sensoren.

Damit nicht hunderte Verbraucher exakt zur selben Sekunde (z. B. 10:00:00)
gleichzeitig eine große Last schalten und so eine Lastspitze im Stromnetz
erzeugen, verschiebt jeder Sensor seine Schaltflanken um einen kleinen,
zufällig *wirkenden* Betrag.

Der Versatz ist **deterministisch** aus der – vom Nutzer nicht editierbaren –
Subentry-ID abgeleitet. Das hat gegenüber einer bei jeder Flanke neu gezogenen
Zufallszahl mehrere Vorteile:

* **Stabil bei jeder Neuberechnung.** Der Binary-Sensor wird minütlich neu
  ausgewertet; eine bei jedem Aufruf frisch gezogene Zufallszahl würde die
  Schaltschwelle ständig verschieben und den Sensor flackern lassen.
* **Transparent/reproduzierbar.** Bei bekannter Sensor-ID lässt sich der
  Versatz jederzeit nachrechnen – makroskopisch zufällig, mikroskopisch
  nachvollziehbar.
* **Gleichverteilt über viele Sensoren.** SHA-256 streut die IDs gleichmäßig,
  sodass sich die aggregierte Last über die Nutzer hinweg glättet.

Beide Schaltflanken werden dabei **gleich** behandelt: Sie wandern nach innen,
sodass das Fenster den günstigen Block nie verlässt (siehe
:func:`jittered_window`).

Wichtig: :func:`jittered_window` wirkt ausschließlich auf den „Günstige Stunde“-
Binary-Sensor und verändert weder die Preis-Sensoren noch die zugrunde
liegenden Preisdaten. :func:`cheap_phase` ist dagegen ein allgemeiner Helfer und
liefert auch dem Koordinator den Versatz seines täglichen API-Abrufs (siehe
``SmartTimesCoordinator._jitter_minutes``).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from .const import JITTER_SPAN_SECONDS


def cheap_phase(seed: str) -> float:
    """Stabiler Pseudo-Zufallswert in ``[0, 1)`` aus ``seed``.

    Es werden die ersten 8 Bytes eines SHA-256-Hashes als 64-Bit-Zahl
    interpretiert und auf ``[0, 1)`` normiert. Gleiche ``seed`` ergeben immer
    denselben Wert; unterschiedliche IDs sind nahezu gleichverteilt.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big")
    return value / 2 ** 64


def jittered_window(
    start: datetime, end: datetime, phase: float
) -> tuple[datetime, datetime]:
    """Verschobenes Ein-/Ausschaltfenster eines zusammenhängenden Günstig-Blocks.

    ``start``/``end`` sind die Grenzen eines (bereits zusammengefassten)
    durchgehenden günstigen Blocks; ``phase`` ist der sensoreigene Wert aus
    :func:`cheap_phase`.

    **Beide Flanken werden gleich behandelt: Sie wandern nach innen.** Das
    Schaltfenster liegt damit immer vollständig *innerhalb* des günstigen
    Blocks – der Verbraucher läuft nie in einer teureren Preiszone, weder vor
    dem Beginn noch nach dem Ende:

    * **Einschalten:** Verzögerung gleichverteilt in ``[0,
      JITTER_SPAN_SECONDS]`` → nie **vor** ``start``.
    * **Ausschalten:** Vorziehen gleichverteilt in ``[-JITTER_SPAN_SECONDS,
      0]`` → nie **nach** ``end``.

    Beide Flanken verschieben sich dabei um **denselben** Betrag ``phase *
    JITTER_SPAN_SECONDS`` und unterscheiden sich nur um einen festen,
    phasenunabhängigen Abzug (``0`` beim Einschalten, ``JITTER_SPAN_SECONDS``
    beim Ausschalten). Das Fenster verschiebt sich deshalb als Ganzes; seine
    Länge ist für *jeden* Sensor dieselbe: ``L - JITTER_SPAN_SECONDS``. Das
    folgt aus der **einen** Breite und kann nicht dadurch kippen, dass zwei
    getrennte Breiten auseinanderlaufen – dann hinge die Fensterlänge von der
    Phase ab, also davon, welche Subentry-ID ein Sensor zufällig bekommen hat
    (siehe ``JITTER_SPAN_SECONDS`` in const.py). Ein durchgehender Block wird so
    nie zerteilt und – solange er länger als ``JITTER_SPAN_SECONDS`` ist – auch
    nie ausgelöscht. Bei der kleinsten Blocklänge (ein Viertelstunden-Intervall,
    das Raster der API) bleiben ``15 min - JITTER_SPAN_SECONDS`` Einschaltzeit.

    Der Preis dieser Gleichbehandlung ist ein deterministischer Verlust von
    ``JITTER_SPAN_SECONDS`` je Block – nicht nur im Mittel, sondern für jeden
    Sensor. Das ist bewusst so gewählt: Lieber etwas weniger günstige Laufzeit
    als Laufzeit zum teureren Preis. Die Last-Glättung bleibt davon unberührt,
    beide Flanken streuen weiterhin über die volle Breite; verschoben ist nur
    die Lage des Fensters, nicht die Streuung.

    Ist ein Block **kürzer** als ``JITTER_SPAN_SECONDS``, würde ihn der Jitter
    ganz aufzehren; dann wird ungejittert exakt auf ``start``/``end``
    geschaltet (siehe unten). Das kann mit dem Viertelstundenraster der API
    nicht vorkommen, ``interval_minutes`` stammt aber aus deren Antwort und ist
    damit keine Konstante dieser Integration.
    """
    # Ein gemeinsamer Versatz für beide Flanken – nur so verschiebt sich das
    # Fenster als Ganzes (siehe Docstring). Die Flanken unterscheiden sich
    # ausschließlich im festen Abzug: keiner beim Einschalten, die volle Breite
    # beim Ausschalten. Dadurch bleibt das Fenster im günstigen Block.
    shift = timedelta(seconds=phase * JITTER_SPAN_SECONDS)
    on_time = start + shift
    off_time = end + shift - timedelta(seconds=JITTER_SPAN_SECONDS)
    # Sicherheitsnetz für (hier nicht vorkommende) extrem kurze Blöcke: Der
    # Jitter darf den Block nie ganz aufzehren. Ein auf einen Punkt
    # zusammengefallenes Fenster (`off == on`) wäre leer – `on <= moment < off`
    # träfe nie zu und der Sensor bliebe dauerhaft „aus“. Lieber ungejittert
    # exakt den Block schalten als gar nicht: Beide Flanken bleiben damit
    # innerhalb ihres oben zugesagten Bereichs (`on` nicht vor `start`, `off`
    # nicht nach `end`), nur eben ohne Last-Glättung.
    if off_time <= on_time:
        return start, end
    return on_time, off_time
