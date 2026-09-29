"""Tests for Satellite Alarms data models."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.assist_satellite_alarms.const import (
    CONF_AREA_ID,
    CONF_ASSIST_SATELLITE,
    CONF_MEDIA_PLAYER,
    CONF_NAME,
    DOMAIN,
)
from custom_components.assist_satellite_alarms.models import AlarmEndpoint, AlarmRecord


def test_alarm_record_round_trip() -> None:
    """Alarm metadata should serialize and deserialize without loss."""
    record = AlarmRecord(
        alarm_id="alarm-123",
        endpoint_entry_id="entry-456",
        scheduler_entity_id="switch.schedule_bedroom",
        name="Work",
        metadata={"volume": 0.7, "snooze_minutes": 10},
    )

    restored = AlarmRecord.from_dict(record.as_dict())

    assert restored == record


def test_endpoint_from_config_entry() -> None:
    """A config entry should map cleanly to an alarm endpoint."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        data={
            CONF_NAME: "Bedroom",
            CONF_AREA_ID: "bedroom",
            CONF_ASSIST_SATELLITE: "assist_satellite.bedroom",
            CONF_MEDIA_PLAYER: "media_player.bedroom",
        },
        entry_id="entry-123",
    )

    endpoint = AlarmEndpoint.from_config_entry(entry)

    assert endpoint.entry_id == "entry-123"
    assert endpoint.name == "Bedroom"
    assert endpoint.area_id == "bedroom"
    assert endpoint.assist_satellite_entity_id == "assist_satellite.bedroom"
    assert endpoint.media_player_entity_id == "media_player.bedroom"
