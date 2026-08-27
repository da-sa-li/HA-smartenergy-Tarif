"""Tests der Config-Entry-Migration (Schema-Version 1 -> 2).

Geprüft wird, dass Bestandseinträge ihr bisheriges Verhalten behalten, obwohl
sich die Vorgabe von ``exact_hours`` mit Version 2 umgekehrt hat.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy import async_migrate_entry
from custom_components.smartenergy.api import SmartTimesApiClient
from custom_components.smartenergy.const import CONFIG_ENTRY_VERSION

DOMAIN = "smartenergy"


def _eintrag(version: int, subentry_data: dict) -> MockConfigEntry:
    """Baut einen Config-Eintrag mit einem Günstig-Stunde-Untereintrag."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        version=version,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "none"},
        subentries_data=[
            ConfigSubentryData(
                data=subentry_data,
                subentry_type="cheap_hour",
                title="Boiler",
                unique_id=None,
            )
        ],
    )


async def _einrichten(hass: HomeAssistant, entry: MockConfigEntry, payload: dict):
    """Richtet den Eintrag ein (löst dabei die Migration aus)."""
    parsed = SmartTimesApiClient._parse(payload)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
        AsyncMock(return_value=parsed),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def _untereintrag(entry: MockConfigEntry) -> dict:
    """Die Daten des einzigen Untereintrags."""
    (subentry,) = entry.subentries.values()
    return dict(subentry.data)


async def test_altbestand_behaelt_das_bisherige_verhalten(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Ein Untereintrag ohne ``exact_hours`` bekommt ausdrücklich False.

    Vor Version 2 war "aus" die Vorgabe (bei Preisgleichstand wird erweitert).
    Ohne die Migration erbte so ein Untereintrag die neue Vorgabe "ein" und
    änderte sein Schaltverhalten ungefragt.
    """
    entry = _eintrag(1, {"cheap_hours": 4.0, "cheap_mode": "individual"})
    await _einrichten(hass, entry, smarttimes_payload)

    assert entry.version == CONFIG_ENTRY_VERSION
    assert _untereintrag(entry)["exact_hours"] is False


async def test_ausdrueckliche_einstellung_bleibt_unberuehrt(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Wer die Option bereits gesetzt hat, behält seinen Wert."""
    entry = _eintrag(
        1, {"cheap_hours": 4.0, "cheap_mode": "individual", "exact_hours": True}
    )
    await _einrichten(hass, entry, smarttimes_payload)

    assert entry.version == CONFIG_ENTRY_VERSION
    assert _untereintrag(entry)["exact_hours"] is True


async def test_neuer_eintrag_wird_nicht_angefasst(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Ein Eintrag auf aktueller Version durchläuft die Migration nicht.

    Er darf insbesondere keinen ``exact_hours``-Schlüssel untergeschoben
    bekommen – dort gilt die neue Vorgabe.
    """
    entry = _eintrag(
        CONFIG_ENTRY_VERSION, {"cheap_hours": 4.0, "cheap_mode": "individual"}
    )
    await _einrichten(hass, entry, smarttimes_payload)

    assert _untereintrag(entry) == {"cheap_hours": 4.0, "cheap_mode": "individual"}


async def test_neuere_version_wird_von_home_assistant_abgelehnt(
    hass: HomeAssistant, enable_custom_integrations
):
    """Ein Eintrag aus einer neueren Fassung lässt sich nicht herunterstufen.

    Wichtig ist, wer das erledigt: **Home Assistant selbst**. Es vergleicht in
    ``ConfigEntry.async_migrate()`` die Version des Eintrags mit
    ``ConfigFlow.VERSION`` und bricht ab, *bevor* ``async_migrate_entry``
    überhaupt aufgerufen wird. Der gleichlautende Vorabtest in ``__init__.py``
    ist deshalb ein Sicherheitsnetz, das im Betrieb nie zum Zug kommt – dieser
    Test deckt ihn nicht ab, auch wenn der Name das früher nahelegte.

    Die Zusicherung unten hält genau diese Arbeitsteilung fest. Ohne sie prüfte
    der Test nur das Ergebnis und behauptete im Docstring eine Ursache, die er
    nie berührt: Er bliebe selbst dann grün, wenn unser Vorabtest fehlerhaft
    wäre oder ganz fehlte.
    """
    entry = _eintrag(
        CONFIG_ENTRY_VERSION + 1, {"cheap_hours": 4.0, "cheap_mode": "individual"}
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartenergy.async_migrate_entry",
        wraps=async_migrate_entry,
    ) as migration:
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.MIGRATION_ERROR
    migration.assert_not_called()


async def test_aeltere_version_erreicht_unsere_migration(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Gegenprobe: Bei einer *älteren* Version läuft unsere Migration sehr wohl.

    Zusammen mit dem Test darüber ist damit beides festgehalten – wann Home
    Assistant selbst abbricht und wann es an uns weiterreicht.
    """
    entry = _eintrag(1, {"cheap_hours": 4.0, "cheap_mode": "individual"})
    entry.add_to_hass(hass)

    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    with (
        patch(
            "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
            AsyncMock(return_value=parsed),
        ),
        patch(
            "custom_components.smartenergy.async_migrate_entry",
            wraps=async_migrate_entry,
        ) as migration,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    migration.assert_called_once()
    assert entry.version == CONFIG_ENTRY_VERSION


async def test_gesamtpreis_entitaet_behaelt_ihren_registry_eintrag(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Der Schlüsselwechsel schreibt die unique_id um, statt neu anzulegen.

    Läge hier eine Neuanlage vor, verlöre der Sensor seine Historie und die
    alte Entität bliebe als verwaister Registry-Eintrag zurück.
    """
    from homeassistant.helpers import entity_registry as er

    entry = _eintrag(1, {"cheap_hours": 4.0, "cheap_mode": "individual"})
    entry.add_to_hass(hass)

    # Zustand vor der Migration nachstellen: die Entität, wie sie Version 1
    # angelegt hat – alte unique_id, alte entity_id.
    registry = er.async_get(hass)
    alt = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_current_price_eur",
        config_entry=entry,
        suggested_object_id="smarttimes_strompreishelfer_total_price_eur_kwh",
    )
    assert alt.entity_id == "sensor.smarttimes_strompreishelfer_total_price_eur_kwh"

    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    with patch(
        "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
        AsyncMock(return_value=parsed),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Derselbe Registry-Eintrag (gleiche interne id) trägt jetzt die neue
    # unique_id – kein zweiter Eintrag, kein Verlust.
    neu = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_total_price"
    )
    assert neu is not None
    assert registry.async_get(neu).id == alt.id
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_current_price_eur"
        )
        is None
    )


async def test_entity_id_wird_angeglichen(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Der Einheitenzusatz verschwindet aus der Entity-ID.

    Damit tragen Bestands- und Neuinstallationen dieselbe ID. Das ist der
    einzige für Nutzer spürbare Teil der Migration.
    """
    from homeassistant.helpers import entity_registry as er

    entry = _eintrag(1, {"cheap_hours": 4.0, "cheap_mode": "individual"})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_current_price_eur",
        config_entry=entry,
        suggested_object_id="smarttimes_strompreishelfer_total_price_eur_kwh",
    )

    await _einrichten(hass, entry, smarttimes_payload)

    neu = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_total_price"
    )
    assert neu == "sensor.smarttimes_strompreishelfer_total_price"


async def test_belegte_entity_id_wird_nicht_ueberschrieben(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Ist der Zielname vergeben, bleibt die alte Entity-ID bestehen.

    Eine fremde Entität zu verschieben, um Platz zu schaffen, wäre schlimmer
    als die uneinheitliche ID.
    """
    from homeassistant.helpers import entity_registry as er

    entry = _eintrag(1, {"cheap_hours": 4.0, "cheap_mode": "individual"})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_current_price_eur",
        config_entry=entry,
        suggested_object_id="smarttimes_strompreishelfer_total_price_eur_kwh",
    )
    # Fremde Entität besetzt den Zielnamen.
    registry.async_get_or_create(
        "sensor",
        "demo",
        "fremd",
        suggested_object_id="smarttimes_strompreishelfer_total_price",
    )

    await _einrichten(hass, entry, smarttimes_payload)

    behalten = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_total_price"
    )
    assert behalten == "sensor.smarttimes_strompreishelfer_total_price_eur_kwh"
