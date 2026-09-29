"""Constants for Satellite Alarms."""

from typing import Final

DOMAIN: Final = "satellite_alarms"
SCHEDULER_DOMAIN: Final = "scheduler"

CONF_NAME: Final = "name"
CONF_AREA_ID: Final = "area_id"
CONF_ASSIST_SATELLITE: Final = "assist_satellite_entity_id"
CONF_MEDIA_PLAYER: Final = "media_player_entity_id"

CONF_DEFAULT_VOLUME: Final = "default_volume"
CONF_DEFAULT_SNOOZE_MINUTES: Final = "default_snooze_minutes"
CONF_VOLUME_RAMP_ENABLED: Final = "volume_ramp_enabled"
CONF_VOLUME_RAMP_START: Final = "volume_ramp_start"
CONF_VOLUME_RAMP_SECONDS: Final = "volume_ramp_seconds"
CONF_MAX_RING_MINUTES: Final = "max_ring_minutes"
CONF_DEFAULT_ALARM_MEDIA: Final = "default_alarm_media"

DEFAULT_VOLUME: Final = 0.70
DEFAULT_SNOOZE_MINUTES: Final = 10
DEFAULT_VOLUME_RAMP_ENABLED: Final = True
DEFAULT_VOLUME_RAMP_START: Final = 0.20
DEFAULT_VOLUME_RAMP_SECONDS: Final = 60
DEFAULT_MAX_RING_MINUTES: Final = 30
DEFAULT_ALARM_MEDIA: Final = ""

DATA_REGISTRY: Final = "registry"
DATA_REGISTRY_LOCK: Final = "registry_lock"
DATA_SCHEDULER_ADAPTER: Final = "scheduler_adapter"

STORAGE_KEY: Final = f"{DOMAIN}.registry"
STORAGE_VERSION: Final = 1
