"""Tests für Einrichtung und Entladen des Config-Eintrags."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartenergy.api import SmartTimesApiClient
from custom_components.smartenergy.repairs import ISSUE_FETCH_FAILING, fetch_issue_id

DOMAIN = "smartenergy"


async def test_einrichten_und_entladen(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Der Eintrag lädt seine Hub-Entitäten und entlädt sich wieder sauber."""
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "wien"},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
        AsyncMock(return_value=parsed),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    # 8 Sensor-Entities (die acht Einträge in SENSORS in sensor.py) und der
    # Diagnose-Binary-Sensor „Preise für morgen verfügbar“. Kein „Günstige
    # Stunde“-Untereintrag angelegt, also auch keine Untereintrags-Entitäten.
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert sum(e.domain == "sensor" for e in entities) == 8
    assert sum(e.domain == "binary_sensor" for e in entities) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_tarif_faellt_auf_data_zurueck(
    hass: HomeAssistant, enable_custom_integrations, smartcontrol_payload
):
    """Ein Altbestand ohne Optionen liest den Tarif aus ``data``."""
    parsed = SmartTimesApiClient._parse(smartcontrol_payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={"tariff": "smartcontrol"},
        options={},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
        AsyncMock(return_value=parsed),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    # entry.data["tariff"]="smartcontrol" wird über TARIFF_DISPLAY_NAMES auf den
    # Anzeigenamen "smartCONTROL" abgebildet (nicht den API-Wert "EPEXSPOTAT").
    assert entry.runtime_data.data.tariff == "smartCONTROL"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_untereintrags_geraet_haengt_am_hub(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Das Gerät eines Untereintrags ist mit dem Hub-Gerät verknüpft.

    Ohne die Verknüpfung stünden „Boiler“ und „Strompreishelfer“ im
    Geräteregister gleichrangig nebeneinander; auf der Geräteseite fehlte das
    „Verbunden über“.

    Dass das Hub-Gerät zum nötigen Zeitpunkt schon besteht, prüft
    ``test_hub_geraet_existiert_vor_dem_weiterreichen`` – hier ginge es sonst
    nur zufällig gut (siehe dort).
    """
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "wien"},
        subentries_data=[
            ConfigSubentryData(
                data={
                    "cheap_hours": 4.0,
                    "cheap_mode": "individual",
                    "exact_hours": True,
                },
                subentry_type="cheap_hour",
                title="Boiler",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
        AsyncMock(return_value=parsed),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    subentry_id = next(iter(entry.subentries))
    registry = dr.async_get(hass)
    hub = registry.async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    untereintrag = registry.async_get_device_by_identifier(
        (DOMAIN, subentry_id), entry.entry_id
    )

    assert hub is not None
    assert untereintrag is not None
    assert untereintrag.via_device_id == hub.id

    # Je Untereintrag entstehen zwei Entitäten: der Günstige-Stunde-Binary-
    # Sensor und der Zeitstempel-Sensor. Dazu die acht Hub-Sensoren und der
    # Diagnose-Binary-Sensor.
    entities = er.async_entries_for_config_entry(
        er.async_get(hass), entry.entry_id
    )
    assert sum(e.domain == "sensor" for e in entities) == 9
    assert sum(e.domain == "binary_sensor" for e in entities) == 2

    # Der Tarif-Anzeigename stammt aus der Nutzer-Auswahl, nicht aus der API.
    assert hub.name == "smartTIMES Strompreishelfer"
    assert hub.entry_type is dr.DeviceEntryType.SERVICE
    assert untereintrag.name == "Boiler"
    # Genau diese zwei Geräte – kein drittes aus einer doppelten Registrierung.
    assert len(dr.async_entries_for_config_entry(registry, entry.entry_id)) == 2
    # Das Untereintrags-Gerät gehört dem Untereintrag, nicht dem Haupteintrag;
    # sonst bliebe es beim Löschen des Untereintrags zurück.
    assert untereintrag.config_entries_subentries == {entry.entry_id: {subentry_id}}


async def test_hub_geraet_existiert_vor_dem_weiterreichen(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Das Hub-Gerät besteht, bevor die Plattformen eingerichtet werden.

    Die Geräte der Untereinträge verweisen per ``via_device_id`` – also über die
    Registry-ID, nicht über die Identifier – auf das Hub-Gerät. Eine unbekannte
    ID weist die Geräte-Registry seit Home Assistant 2026.8 mit einem Fehler
    zurück, woraufhin die Entität gar nicht erst angelegt wird.

    Entstünde das Hub-Gerät weiterhin nur als Nebenprodukt des ersten
    Preissensors, hinge das an einem Rennen zwischen den nebenläufig
    eingerichteten Plattformen. Dieses Rennen geht heute meist gut aus – deshalb
    wird hier die Zusage selbst geprüft und nicht ihr Ergebnis: Zum Zeitpunkt
    von ``async_forward_entry_setups`` muss das Gerät bereits stehen.
    """
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "wien"},
    )
    entry.add_to_hass(hass)

    registry = dr.async_get(hass)
    vorhanden: list[bool] = []
    weiterreichen = hass.config_entries.async_forward_entry_setups

    async def _mitschreiben(weitergereichter_eintrag, platforms):
        """Hält fest, ob das Hub-Gerät beim Weiterreichen schon existiert."""
        vorhanden.append(
            registry.async_get_device_by_identifier(
                (DOMAIN, weitergereichter_eintrag.entry_id),
                weitergereichter_eintrag.entry_id,
            )
            is not None
        )
        return await weiterreichen(weitergereichter_eintrag, platforms)

    with (
        patch(
            "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
            AsyncMock(return_value=parsed),
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", _mitschreiben
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert vorhanden == [True]


async def test_zwei_eintraege_laufen_unabhaengig_nebeneinander(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Zwei Einträge (zwei Zähler) laden nebeneinander, jeder für sich.

    Erwartet je Eintrag: ein eigenes Hub-Gerät mit dem Namen seines Tarifs und
    die acht Hub-Sensoren plus Diagnose-Binary-Sensor – zusammen also 16
    Sensoren und 2 Binary-Sensoren ohne Kollision der unique_ids (eine
    Kollision ließe Home Assistant die zweite Entität verwerfen). Wird einer
    entladen, läuft der andere weiter.

    Beide Tarife holen ihre Preise über ``SmartTimesApiClient.async_get_prices``;
    die gepatchte Antwort ist für den Test gleichgültig, der Anzeigename des
    Tarifs stammt aus der Konfiguration.
    """
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    haushalt = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "wien"},
    )
    waermepumpe = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={"tariff": "smartcontrol", "include_vat": True, "grid_zone": "wien"},
    )
    haushalt.add_to_hass(hass)
    waermepumpe.add_to_hass(hass)

    with patch(
        "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
        AsyncMock(return_value=parsed),
    ):
        # Richtet die Integration ein – und damit alle ihre Einträge.
        assert await hass.config_entries.async_setup(haushalt.entry_id)
        await hass.async_block_till_done()

    assert haushalt.state is ConfigEntryState.LOADED
    assert waermepumpe.state is ConfigEntryState.LOADED

    geraete = dr.async_get(hass)
    hub_haushalt = geraete.async_get_device_by_identifier(
        (DOMAIN, haushalt.entry_id), haushalt.entry_id
    )
    hub_waermepumpe = geraete.async_get_device_by_identifier(
        (DOMAIN, waermepumpe.entry_id), waermepumpe.entry_id
    )
    assert hub_haushalt is not None
    assert hub_waermepumpe is not None
    assert hub_haushalt.id != hub_waermepumpe.id
    assert hub_haushalt.name == "smartTIMES Strompreishelfer"
    assert hub_waermepumpe.name == "smartCONTROL Strompreishelfer"

    entitaeten = er.async_get(hass)
    for eintrag in (haushalt, waermepumpe):
        eigene = er.async_entries_for_config_entry(entitaeten, eintrag.entry_id)
        assert sum(e.domain == "sensor" for e in eigene) == 8
        assert sum(e.domain == "binary_sensor" for e in eigene) == 1
    alle = [e for e in entitaeten.entities.values() if e.platform == DOMAIN]
    assert len(alle) == 18
    assert len({e.unique_id for e in alle}) == 18

    assert await hass.config_entries.async_unload(haushalt.entry_id)
    await hass.async_block_till_done()
    assert haushalt.state is ConfigEntryState.NOT_LOADED
    assert waermepumpe.state is ConfigEntryState.LOADED


async def test_einrichten_raeumt_das_abruf_issue_aelterer_versionen_ab(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Das einmalige Abruf-Issue ohne entry_id verschwindet beim Einrichten.

    Bis Version 4.3 hieß das Issue schlicht ``fetch_failing``. Seit es je
    Eintrag geführt wird, schließt es kein Coordinator mehr – stand es beim
    Update offen, bliebe es ohne diesen Schritt dauerhaft in der persistenten
    Issue-Registry stehen.
    """
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_FETCH_FAILING,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_FETCH_FAILING,
    )
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "wien"},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
        AsyncMock(return_value=parsed),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_FETCH_FAILING) is None


async def test_entfernen_raeumt_das_abruf_issue_des_eintrags_ab(
    hass: HomeAssistant, enable_custom_integrations, smarttimes_payload
):
    """Wird ein Eintrag entfernt, verschwindet sein Abruf-Issue mit ihm.

    Schließen könnte es sonst nur der Coordinator dieses Eintrags – und der
    läuft nach dem Entfernen nicht mehr. Das Issue eines anderen Eintrags
    bleibt dagegen stehen.
    """
    parsed = SmartTimesApiClient._parse(smarttimes_payload)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={"tariff": "smarttimes", "include_vat": True, "grid_zone": "wien"},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartenergy.api.SmartTimesApiClient.async_get_prices",
        AsyncMock(return_value=parsed),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    issues = ir.async_get(hass)
    for issue_id in (fetch_issue_id(entry.entry_id), fetch_issue_id("fremd")):
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_FETCH_FAILING,
            translation_placeholders={"name": "x"},
        )

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert issues.async_get_issue(DOMAIN, fetch_issue_id(entry.entry_id)) is None
    assert issues.async_get_issue(DOMAIN, fetch_issue_id("fremd")) is not None


async def test_ha_instanzen_laufen_auf_europe_vienna(hass: HomeAssistant):
    """Jede HA-Instanz im Test läuft in der Zeitzone der Integration.

    Wächter für die Fixture in ``conftest.py``: Das Test-Harness setzt von sich
    aus ``US/Pacific``. Fiele die Überschreibung weg – etwa weil eine neue
    Fassung des Harness die Fixture anders benennt –, verschöben sich
    SNAP-Fenster, Tagesgrenzen und „morgen“ um neun Stunden. Tests, deren
    Sollwerte von Hand aus der Spezifikation abgeleitet sind, träfen dann
    bestenfalls zufällig zu, und das fiele ohne diesen Test niemandem auf.
    """
    assert hass.config.time_zone == "Europe/Vienna"
    assert dt_util.DEFAULT_TIME_ZONE.key == "Europe/Vienna"
