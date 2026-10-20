"""Tests der Netzentgelte: SNAP-/WiNAP-Fenster, Zonen-Lookup, Summen.

Werte für Wien (Stand 2026, netto): usage_ap=6,98 · usage_snap=5,58 · loss=0,700.
"""

from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timedelta

import pytest

from custom_components.smartenergy import grid_fees
from custom_components.smartenergy.const import TARIFF_DATA_YEAR
from custom_components.smartenergy.grid_fees import GridRates, GridZone
from tests.conftest import VIENNA


def _dt(year, month, day, hour, minute=0):
    """Zeitzonenbehaftetes datetime in Europe/Vienna (knappe Test-Schreibweise)."""
    return datetime(year, month, day, hour, minute, tzinfo=VIENNA)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (_dt(2026, 6, 5, 10, 0), True),    # Start 10:00 inklusive
        (_dt(2026, 6, 5, 15, 59), True),   # kurz vor Ende
        (_dt(2026, 6, 5, 16, 0), False),   # Ende 16:00 exklusiv
        (_dt(2026, 6, 5, 9, 59), False),   # vor dem Fenster
        (_dt(2026, 4, 1, 12, 0), True),    # April: Sommerhalbjahr beginnt
        (_dt(2026, 9, 30, 12, 0), True),   # September: noch drin
        (_dt(2026, 10, 1, 12, 0), False),  # Oktober: raus
        (_dt(2026, 1, 15, 12, 0), False),  # Winter
    ],
)
def test_snap_fenster_gilt_im_sommerhalbjahr(moment, expected):
    """Das SNAP-Fenster gilt im Sommerhalbjahr 10:00-16:00 (Ende exklusiv)."""
    assert grid_fees.is_snap(moment) is expected


# --- WiNAP-Fenster ----------------------------------------------------------- #
#
# Sollwerte von Hand aus § 7 Abs. 4 SNE-G-V: 1. Oktober bis 31. März, je 23:00 bis
# 05:00 Uhr des Folgetags; die Nacht zählt zu dem Tag, an dem sie beginnt.
# Erstmals gilt der WiNAP in der Nacht ab 01.10.2027 (§ 32 Abs. 4).
@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (_dt(2027, 10, 1, 2, 0), False),    # Nacht des 30.09.: vor dem ersten WiNAP
        (_dt(2027, 10, 1, 22, 59), False),  # vor Beginn der ersten Nacht
        (_dt(2027, 10, 1, 23, 0), True),    # erste WiNAP-Nacht beginnt
        (_dt(2027, 10, 2, 4, 59), True),    # Ende noch nicht erreicht
        (_dt(2027, 10, 2, 5, 0), False),    # Ende 05:00 exklusiv
        (_dt(2027, 12, 31, 23, 30), True),  # Jahreswechsel: Nacht beginnt
        (_dt(2028, 1, 1, 0, 0), True),      # ... und läuft über Neujahr weiter
        (_dt(2028, 3, 31, 23, 0), True),    # letzte Nacht beginnt
        (_dt(2028, 4, 1, 4, 45), True),     # gehört noch zur Nacht des 31.03.
        (_dt(2028, 4, 1, 5, 0), False),     # Ende exklusiv
        (_dt(2028, 4, 1, 23, 0), False),    # Sommerhalbjahr
        (_dt(2028, 1, 15, 12, 0), False),   # Winter, aber tagsüber
        (_dt(2027, 1, 15, 2, 0), False),    # Winter 2026/27 hat noch keinen WiNAP
        (_dt(2027, 3, 31, 23, 30), False),  # letzte Nacht davor: ebenfalls nicht
    ],
)
def test_winap_fenster_gilt_nachts_im_winterhalbjahr_ab_2027(moment, expected):
    """Der WiNAP gilt 23:00-05:00 (Ende exklusiv), je Nacht nach ihrem Beginn."""
    assert grid_fees.is_winap(moment) is expected


def test_winap_gilt_in_den_umstellungsnaechten_nach_wanduhr():
    """Der WiNAP folgt der Wanduhr, auch in den Nächten der Zeitumstellung.

    Am 31.10.2027 (03 -> 02 Uhr) wiederholt sich die Stunde 02:00, am 26.03.2028
    (02 -> 03 Uhr) entfällt sie. Beide Nächte liegen im Fenster, auch die
    wiederholte Stunde (``fold=1``) zählt.
    """
    erste = datetime(2027, 10, 31, 2, 30, tzinfo=VIENNA, fold=0)
    zweite = datetime(2027, 10, 31, 2, 30, tzinfo=VIENNA, fold=1)
    assert grid_fees.is_winap(erste) is True
    assert grid_fees.is_winap(zweite) is True
    assert grid_fees.is_winap(_dt(2027, 10, 31, 4, 59)) is True
    assert grid_fees.is_winap(_dt(2027, 10, 31, 5, 0)) is False
    assert grid_fees.is_winap(_dt(2028, 3, 26, 3, 0)) is True   # nach dem Sprung
    assert grid_fees.is_winap(_dt(2028, 3, 26, 5, 0)) is False


def test_winap_und_snap_ueberschneiden_sich_nie():
    """Über ein Jahr in Viertelstunden gerastert gilt nie beides zugleich."""
    moment = _dt(2027, 10, 1, 0, 0)
    for _ in range(366 * 96):
        assert not (grid_fees.is_snap(moment) and grid_fees.is_winap(moment))
        moment += timedelta(minutes=15)


def test_arbeitspreis_im_winap_fenster():
    """Mit hinterlegtem Satz gilt im WiNAP-Fenster er, sonst der normale AP.

    Fiktive Sätze (die echten gibt es erst mit der SNE-T-V 2027): AP 7,00 ·
    SNAP 5,60 · WiNAP 4,90 · Verlust 0,50.
    """
    zone = GridZone("test", "Test", (GridRates(7.00, 5.60, 0.50, usage_winap=4.90),))
    assert zone.usage_rate(_dt(2028, 1, 15, 2)) == 4.90   # WiNAP
    assert zone.usage_rate(_dt(2028, 1, 15, 12)) == 7.00  # Winter, tagsüber
    assert zone.usage_rate(_dt(2028, 6, 5, 14)) == 5.60   # SNAP
    assert zone.total_ct_per_kwh(_dt(2028, 1, 15, 2)) == pytest.approx(5.40)
    assert zone.breakdown(_dt(2028, 1, 15, 2)) == {"grid_usage": 4.90, "grid_loss": 0.50}


def test_winap_satz_folgt_der_satzgruppe_des_tages():
    """Der WiNAP-Satz kommt aus der Gruppe des Kalendertags, nicht aus der Zone.

    Nacht vom 30.11. auf den 1.12.2027 um 23:30 Uhr am 30.11. (alte Gruppe,
    WiNAP 4,90) und um 00:30 Uhr am 1.12. (neue Gruppe, WiNAP 3,70).
    """
    zone = GridZone(
        "test",
        "Test",
        (
            GridRates(7.00, 5.60, 0.50, usage_winap=4.90, until=date(2027, 11, 30)),
            GridRates(5.00, 4.00, 0.40, usage_winap=3.70, since=date(2027, 12, 1)),
        ),
    )
    assert zone.usage_rate(_dt(2027, 11, 30, 23, 30)) == 4.90
    assert zone.usage_rate(_dt(2027, 12, 1, 0, 30)) == 3.70


def test_ohne_winap_satz_gilt_im_fenster_der_normale_arbeitspreis():
    """Solange kein WiNAP-Satz hinterlegt ist, bleibt es beim normalen AP."""
    zone = grid_fees.get_zone("wien")
    assert all(gruppe.usage_winap is None for gruppe in zone.rates)
    assert zone.usage_rate(_dt(2028, 1, 15, 2)) == 6.98


def test_netzgebiet_nachschlagen():
    """Der Zonen-Lookup liefert None für leere/unbekannte Schlüssel, sonst die Zone."""
    assert grid_fees.get_zone(None) is None
    assert grid_fees.get_zone("") is None
    assert grid_fees.get_zone("none") is None        # kein Eintrag mit diesem Schlüssel
    assert grid_fees.get_zone("unbekannt") is None
    assert grid_fees.get_zone("wien").name == "Wien"


def test_arbeitspreis_im_snap_und_zur_regelzeit():
    """Der Netznutzungs-Arbeitspreis ist im SNAP-Fenster reduziert, sonst normal."""
    zone = grid_fees.get_zone("wien")
    assert zone.usage_rate(_dt(2026, 6, 5, 14)) == 5.58   # SNAP
    assert zone.usage_rate(_dt(2026, 1, 15, 12)) == 6.98  # Regelzeit


def test_summe_ausserhalb_des_snap_fensters():
    """Außerhalb des SNAP: 6,98 + 0,700 = 7,68 ct/kWh netto."""
    zone = grid_fees.get_zone("wien")
    assert zone.total_ct_per_kwh(_dt(2026, 1, 15, 12)) == pytest.approx(7.68)


def test_summe_im_snap_fenster():
    """Im SNAP-Fenster: 5,58 + 0,700 = 6,28 ct/kWh netto."""
    zone = grid_fees.get_zone("wien")
    assert zone.total_ct_per_kwh(_dt(2026, 6, 5, 14)) == pytest.approx(6.28)


def test_aufschluesselung_nutzt_den_snap_satz():
    """Die Aufschlüsselung nutzt je nach Zeitpunkt den SNAP- bzw. Regelsatz."""
    zone = grid_fees.get_zone("wien")
    assert zone.breakdown(_dt(2026, 6, 5, 14)) == {"grid_usage": 5.58, "grid_loss": 0.700}
    assert zone.breakdown(_dt(2026, 1, 15, 12)) == {"grid_usage": 6.98, "grid_loss": 0.700}


# --- Vollständige Netzentgelt-Tabelle --------------------------------------- #
#
# Bisher wurde ausschließlich Wien ausgewertet; die übrigen 13 Netzgebiete waren
# unbelegt. Es sind von Hand abgetippte, jährlich zu erneuernde Tarifwerte – der
# realistische Fehler ist der Zahlendreher, und er verschiebt still den
# Gesamtpreis jedes Nutzers in genau dieser Zone.
#
# Zwei Prüfungen mit unterschiedlicher Aussagekraft:
#
# 1. ERWARTETE_ZONEN ist eine bewusste Zweitschrift der Tabelle aus
#    `grid_fees.py` (Netzentgelte 2026, Netzebene 7, Viertelstundenmessung, ohne
#    Leistungsmessung; netto in ct/kWh). Sie ist damit KEINE unabhängige Quelle –
#    ihr Zweck ist, die jährliche Aktualisierung zu einer bewussten Änderung an
#    *zwei* Stellen zu machen, statt eine einseitig verrutschte Ziffer
#    durchzulassen. Beim Aktualisieren also beide Tabellen anfassen und die Werte
#    gegen die Preisblätter des jeweiligen Netzbetreibers gegenlesen.
#
# 2. Die SNAP-Invariante darunter ist dagegen aus der Spezifikation abgeleitet
#    (Modul-Docstring von `grid_fees.py`: SNAP = -20 % auf den Netz-Arbeitspreis).
#    Sie prüft aber nur das *Verhältnis* der beiden Sätze zueinander, nicht ihre
#    Höhe: Der Sollwert entsteht aus `usage_ap` selbst, ein falscher
#    Arbeitspreis mit passend nachgezogenem SNAP-Satz besteht sie also.
#
# Damit bleibt eine Lücke, die keine der beiden Prüfungen schließt: ein Wert,
# der in Produktivtabelle UND Zweitschrift gleich falsch steht. Nachgestellt und
# bestätigt (Graz 5,17 -> 5,71 mit konsistentem SNAP 4,57 an beiden Stellen:
# alle Tests grün; nur einseitig eingebracht: zwei Fehlschläge). Dagegen hilft
# allein ein Abgleich mit den Preisblättern der Netzbetreiber – eine Aufgabe für
# die jährliche Aktualisierung, die diese Datei nicht leisten kann.
ERWARTETE_ZONEN = {
    # Schlüssel: (Anzeigename, usage_ap, usage_snap, loss)
    "burgenland": ("Burgenland", 8.46, 6.77, 0.000),
    "kaernten": ("Kärnten", 9.67, 7.74, 0.368),
    "klagenfurt": ("Klagenfurt", 6.90, 5.52, 0.578),
    "niederoesterreich": ("Niederösterreich", 8.79, 7.03, 0.384),
    "oberoesterreich": ("Oberösterreich", 6.29, 5.03, 0.528),
    "linz": ("Linz", 5.57, 4.46, 0.487),
    "salzburg": ("Salzburg", 6.59, 5.27, 0.357),
    "steiermark": ("Steiermark", 8.82, 7.06, 0.336),
    "graz": ("Graz", 5.17, 4.14, 0.658),
    "tirol": ("Tirol", 6.81, 5.45, 0.293),
    "innsbruck": ("Innsbruck", 8.03, 6.42, 0.453),
    "vorarlberg": ("Vorarlberg", 4.96, 3.97, 0.393),
    "wien": ("Wien", 6.98, 5.58, 0.700),
    "kleinwalsertal": ("Kleinwalsertal", 17.73, 14.18, 0.401),
}


def test_alle_netzgebiete_sind_erfasst():
    """Die Prüftabelle deckt exakt die hinterlegten Netzgebiete ab.

    Ohne diesen Abgleich bliebe ein neu ergänztes Netzgebiet unbemerkt
    ungeprüft – und ein entferntes würde hier still weitergeschleppt.
    """
    assert set(grid_fees.GRID_ZONES) == set(ERWARTETE_ZONEN)


@pytest.mark.parametrize("schluessel", sorted(ERWARTETE_ZONEN), ids=str)
def test_zonenwerte_stimmen_mit_der_tabelle(schluessel: str):
    """Jedes Netzgebiet führt die erwarteten Sätze und seinen Anzeigenamen."""
    name, usage_ap, usage_snap, loss = ERWARTETE_ZONEN[schluessel]
    zone = grid_fees.GRID_ZONES[schluessel]

    assert zone.key == schluessel  # der Schlüssel im dict und im Objekt selbst
    assert zone.name == name
    # Stand 2026: je Netzgebiet genau eine unbefristete Satzgruppe.
    assert len(zone.rates) == 1
    assert zone.rates[0].usage_ap == pytest.approx(usage_ap)
    assert zone.rates[0].usage_snap == pytest.approx(usage_snap)
    assert zone.rates[0].loss == pytest.approx(loss)


@pytest.mark.parametrize("schluessel", sorted(ERWARTETE_ZONEN), ids=str)
def test_snap_liegt_20_prozent_unter_dem_arbeitspreis(schluessel: str):
    """Der SNAP-Satz jeder Zone liegt 20 % unter ihrem Netz-Arbeitspreis.

    Das ist die Regel aus der Spezifikation (siehe Modul-Docstring von
    ``grid_fees.py``), nicht aus der Tabelle abgelesen. Sie prüft alle 14
    Netzgebiete unabhängig von der Zweitschrift oben und fängt damit auch einen
    Zahlendreher ab, der in *beide* Tabellen gleichzeitig geriete.

    Die Netzbetreiber weisen den Satz auf zwei Nachkommastellen aus, daher wird
    der Sollwert genauso gerundet.
    """
    zone = grid_fees.GRID_ZONES[schluessel]
    for gruppe in zone.rates:
        assert gruppe.usage_snap == round(gruppe.usage_ap * 0.8, 2)


@pytest.mark.parametrize("schluessel", sorted(ERWARTETE_ZONEN), ids=str)
def test_jede_zone_rechnet_snap_und_regelzeit(schluessel: str):
    """``total_ct_per_kwh`` summiert je Zone den gültigen AP und das Verlustentgelt.

    Bisher belegte das nur Wien; ein Fehler in ``usage_rate`` oder ``breakdown``
    hätte sich also in jeder anderen Zone unbemerkt auswirken können.
    """
    _, usage_ap, usage_snap, loss = ERWARTETE_ZONEN[schluessel]
    zone = grid_fees.GRID_ZONES[schluessel]

    # 05.06.2026 14:00 liegt im SNAP-Fenster, 15.01.2026 12:00 nicht.
    assert zone.total_ct_per_kwh(_dt(2026, 6, 5, 14)) == pytest.approx(
        usage_snap + loss
    )
    assert zone.total_ct_per_kwh(_dt(2026, 1, 15, 12)) == pytest.approx(
        usage_ap + loss
    )
    assert zone.breakdown(_dt(2026, 6, 5, 14)) == {
        "grid_usage": pytest.approx(usage_snap),
        "grid_loss": pytest.approx(loss),
    }


# --- Satzgruppen mit Gültigkeitszeitraum ------------------------------------ #
#
# Handgerechnet, mit frei gewählten Testsätzen (keine echten Tarifwerte):
#   alt:  AP 7,00 · SNAP 5,60 · Verlust 0,50   (bis 30.11.2027)
#   neu:  AP 5,00 · SNAP 4,00 · Verlust 0,40   (ab  01.12.2027)
# Außerhalb des SNAP-Fensters: alt 7,00 + 0,50 = 7,50; neu 5,00 + 0,40 = 5,40.
# Im SNAP-Fenster (Juni, 12 Uhr): alt 5,60 + 0,50 = 6,10; neu 4,00 + 0,40 = 4,40.
_WECHSELTAG = date(2027, 12, 1)
_ALT = GridRates(7.00, 5.60, 0.50, until=_WECHSELTAG - timedelta(days=1))
_NEU = GridRates(5.00, 4.00, 0.40, since=_WECHSELTAG)
_WECHSEL_ZONE = GridZone("test", "Testgebiet", (_ALT, _NEU))


def test_wechsel_letzter_tag_mit_alten_saetzen():
    """Am Tag vor dem Wechsel gelten noch die alten Sätze (Ende inklusive)."""
    moment = _dt(2027, 11, 30, 23, 45)
    assert _WECHSEL_ZONE.total_ct_per_kwh(moment) == pytest.approx(7.50)
    assert _WECHSEL_ZONE.breakdown(moment) == {"grid_usage": 7.00, "grid_loss": 0.50}


def test_wechsel_erster_tag_mit_neuen_saetzen():
    """Am Wechseltag gelten ab 00:00 Uhr die neuen Sätze (Beginn inklusive)."""
    moment = _dt(2027, 12, 1, 0, 0)
    assert _WECHSEL_ZONE.total_ct_per_kwh(moment) == pytest.approx(5.40)
    assert _WECHSEL_ZONE.breakdown(moment) == {"grid_usage": 5.00, "grid_loss": 0.40}


def test_wechsel_wirkt_auch_auf_den_snap_satz():
    """Der SNAP-Satz kommt aus derselben Gruppe wie der Arbeitspreis."""
    assert _WECHSEL_ZONE.total_ct_per_kwh(_dt(2027, 6, 5, 12)) == pytest.approx(6.10)
    # Mit späterem Wechsel (hier: im Sommer) greift der neue SNAP-Satz.
    spaet = GridZone(
        "test",
        "Testgebiet",
        (
            GridRates(7.00, 5.60, 0.50, until=date(2027, 6, 14)),
            GridRates(5.00, 4.00, 0.40, since=date(2027, 6, 15)),
        ),
    )
    assert spaet.total_ct_per_kwh(_dt(2027, 6, 14, 12)) == pytest.approx(6.10)
    assert spaet.total_ct_per_kwh(_dt(2027, 6, 15, 12)) == pytest.approx(4.40)


def test_wechsel_folgt_dem_lokalen_kalendertag():
    """Maßgeblich ist der Kalendertag in Ortszeit, nicht in UTC.

    00:30 Uhr Wiener Zeit am 1.12.2027 ist am 30.11. um 23:30 UTC – es gelten
    trotzdem schon die neuen Sätze.
    """
    moment = _dt(2027, 12, 1, 0, 30).astimezone(zoneinfo.ZoneInfo("UTC"))
    assert _WECHSEL_ZONE.total_ct_per_kwh(moment) == pytest.approx(5.40)


def test_luecke_faellt_nicht_auf_null_netzentgelt():
    """Greift keine Gruppe, gilt die nächstliegende – nie 0.

    Handgerechnet: erste Gruppe bis 30.06.2027, zweite ab 01.08.2027.
    * 15.07.: 15 Tage nach Ende der ersten, 17 Tage vor Beginn der zweiten
      -> die erste ist näher.
    * 20.07.: 20 Tage nach Ende der ersten, 12 Tage vor Beginn der zweiten
      -> die zweite ist näher.
    * 16.07.: 16 Tage nach Ende der ersten, 16 Tage vor Beginn der zweiten
      -> Gleichstand, die frühere gilt.
    """
    luecke = GridZone(
        "test",
        "Testgebiet",
        (
            GridRates(7.00, 5.60, 0.50, since=date(2027, 1, 1), until=date(2027, 6, 30)),
            GridRates(5.00, 4.00, 0.40, since=date(2027, 8, 1)),
        ),
    )
    assert luecke.total_ct_per_kwh(_dt(2027, 7, 15, 20)) > 0
    assert luecke.rates_on(date(2026, 12, 31)) is luecke.rates[0]  # vor der ersten
    assert luecke.rates_on(date(2027, 7, 15)) is luecke.rates[0]  # näher an der ersten
    assert luecke.rates_on(date(2027, 7, 20)) is luecke.rates[1]  # näher an der zweiten
    assert luecke.rates_on(date(2027, 7, 16)) is luecke.rates[0]  # Gleichstand: früher
    assert luecke.rates_on(date(2028, 1, 1)) is luecke.rates[1]  # nach der letzten


def test_zone_ohne_satzgruppe_wird_abgewiesen():
    """Ein Netzgebiet ohne jede Satzgruppe ist ein Tabellenfehler."""
    with pytest.raises(ValueError):
        GridZone("leer", "Leer", ())


@pytest.mark.parametrize("schluessel", sorted(grid_fees.GRID_ZONES), ids=str)
def test_satzgruppen_decken_das_datenjahr_lueckenlos_ab(schluessel: str):
    """An jedem Tag von ``TARIFF_DATA_YEAR`` gilt je Netzgebiet genau eine Gruppe.

    Eine Lücke hieße: Intervalle ohne passende Gruppe; eine Überschneidung:
    der Satz hinge von der Reihenfolge in der Tabelle ab. Beides fiele sonst
    erst auf, wenn ein Nutzer eine falsche Rechnung meldet.
    """
    zone = grid_fees.GRID_ZONES[schluessel]
    tag = date(TARIFF_DATA_YEAR, 1, 1)
    while tag.year == TARIFF_DATA_YEAR:
        passend = [g for g in zone.rates if g.applies_on(tag)]
        assert len(passend) == 1, f"{schluessel}: {len(passend)} Gruppen am {tag}"
        tag += timedelta(days=1)


@pytest.mark.parametrize("schluessel", sorted(grid_fees.GRID_ZONES), ids=str)
def test_satzgruppen_sind_chronologisch_sortiert(schluessel: str):
    """Die Gruppen stehen in zeitlicher Reihenfolge (Voraussetzung von ``rates_on``)."""
    beginne = [g.since or date.min for g in grid_fees.GRID_ZONES[schluessel].rates]
    assert beginne == sorted(beginne)
