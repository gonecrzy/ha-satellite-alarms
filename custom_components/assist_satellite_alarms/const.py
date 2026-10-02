"""Constants for Satellite Alarms."""

from typing import Final

DOMAIN: Final = "assist_satellite_alarms"
SCHEDULER_DOMAIN: Final = "scheduler"

CONF_NAME: Final = "name"
CONF_AREA_ID: Final = "area_id"
CONF_ASSIST_SATELLITE: Final = "assist_satellite_entity_id"
CONF_MEDIA_PLAYER: Final = "media_player_entity_id"
CONF_ADDITIONAL_PLAYBACK_TARGETS: Final = "additional_playback_targets"
CONF_ADDITIONAL_ASSIST_SATELLITES: Final = "additional_assist_satellite_entity_ids"
CONF_ADDITIONAL_MEDIA_PLAYERS: Final = "additional_media_player_entity_ids"
CONF_PLAYBACK_MODE: Final = "playback_mode"

PLAYBACK_MODE_PRIMARY: Final = "primary"
PLAYBACK_MODE_ALL: Final = "all"
PLAYBACK_MODE_FALLBACK: Final = "fallback"
PLAYBACK_MODES: Final = (
    PLAYBACK_MODE_PRIMARY,
    PLAYBACK_MODE_ALL,
    PLAYBACK_MODE_FALLBACK,
)
DEFAULT_PLAYBACK_MODE: Final = PLAYBACK_MODE_PRIMARY

CONF_DEFAULT_VOLUME: Final = "default_volume"
CONF_DEFAULT_SNOOZE_MINUTES: Final = "default_snooze_minutes"
CONF_VOLUME_RAMP_ENABLED: Final = "volume_ramp_enabled"
CONF_VOLUME_RAMP_START: Final = "volume_ramp_start"
CONF_VOLUME_RAMP_SECONDS: Final = "volume_ramp_seconds"
CONF_MAX_RING_MINUTES: Final = "max_ring_minutes"
CONF_DEFAULT_ALARM_MEDIA: Final = "default_alarm_media"
CONF_DEFAULT_ALARM_MESSAGE: Final = "default_alarm_message"

DEFAULT_VOLUME: Final = 0.70
DEFAULT_SNOOZE_MINUTES: Final = 10
DEFAULT_VOLUME_RAMP_ENABLED: Final = True
DEFAULT_VOLUME_RAMP_START: Final = 0.20
DEFAULT_VOLUME_RAMP_SECONDS: Final = 60
DEFAULT_MAX_RING_MINUTES: Final = 30
BUILTIN_ALARM_MEDIA_FILENAME: Final = "alarm.mp3"
BUILTIN_ALARM_MEDIA_URL: Final = (
    f"/api/assist_satellite_alarms/static/{BUILTIN_ALARM_MEDIA_FILENAME}"
)
DEFAULT_ALARM_MEDIA: Final = BUILTIN_ALARM_MEDIA_URL
DEFAULT_ALARM_MESSAGE: Final = "Alarm"

DATA_REGISTRY: Final = "registry"
DATA_SCHEDULER_ADAPTER: Final = "scheduler_adapter"
DATA_ALARM_MANAGER: Final = "alarm_manager"
DATA_PLAYBACK_MANAGER: Final = "playback_manager"
DATA_VOICE_CONTROLLER: Final = "voice_controller"
DATA_RECONCILED: Final = "reconciled"

STORAGE_KEY: Final = f"{DOMAIN}.registry"
STORAGE_VERSION: Final = 1

SERVICE_CREATE: Final = "create"
SERVICE_UPDATE: Final = "update"
SERVICE_DELETE: Final = "delete"
SERVICE_ENABLE: Final = "enable"
SERVICE_DISABLE: Final = "disable"
SERVICE_FIRE: Final = "fire"
SERVICE_STOP: Final = "stop"
SERVICE_SNOOZE: Final = "snooze"
SERVICE_LIST: Final = "list"
SERVICE_SKIP_NEXT: Final = "skip_next"
SERVICE_OVERRIDE_NEXT: Final = "override_next"

ATTR_ALARM_ID: Final = "alarm_id"
ATTR_ENDPOINT_ID: Final = "endpoint_id"
ATTR_TIME: Final = "time"
ATTR_DATE: Final = "date"
ATTR_RECURRENCE: Final = "recurrence"
ATTR_MINUTES: Final = "minutes"
ATTR_DAYS: Final = "days"
ATTR_OCCURRENCE: Final = "occurrence"
ATTR_OCCURRENCE_ID: Final = "occurrence_id"
ATTR_ALARM_MEDIA: Final = "alarm_media"
ATTR_ALARM_VOLUME: Final = "alarm_volume"
ATTR_SNOOZE_MINUTES: Final = "snooze_minutes"
ATTR_PRE_ACTIONS: Final = "pre_actions"
ATTR_POST_ACTIONS: Final = "post_actions"
ATTR_FAILURE_ACTIONS: Final = "failure_actions"

RECURRENCE_ONCE: Final = "once"
RECURRENCE_DAILY: Final = "daily"
RECURRENCE_WEEKDAYS: Final = "weekdays"
RECURRENCE_WEEKENDS: Final = "weekends"
RECURRENCE_SELECTED_DAYS: Final = "selected_days"
RECURRENCES: Final = (
    RECURRENCE_ONCE,
    RECURRENCE_DAILY,
    RECURRENCE_WEEKDAYS,
    RECURRENCE_WEEKENDS,
    RECURRENCE_SELECTED_DAYS,
)

WEEKDAY_MON: Final = "mon"
WEEKDAY_TUE: Final = "tue"
WEEKDAY_WED: Final = "wed"
WEEKDAY_THU: Final = "thu"
WEEKDAY_FRI: Final = "fri"
WEEKDAY_SAT: Final = "sat"
WEEKDAY_SUN: Final = "sun"
WEEKDAYS: Final = (
    WEEKDAY_MON,
    WEEKDAY_TUE,
    WEEKDAY_WED,
    WEEKDAY_THU,
    WEEKDAY_FRI,
    WEEKDAY_SAT,
    WEEKDAY_SUN,
)

META_TIME: Final = "time"
META_DATE: Final = "date"
META_RECURRENCE: Final = "recurrence"
META_DAYS: Final = "days"
META_SKIP_NEXT: Final = "skip_next"
META_OVERRIDE: Final = "override"
META_ALARM_MEDIA: Final = "alarm_media"
META_ALARM_VOLUME: Final = "alarm_volume"
META_SNOOZE_MINUTES: Final = "snooze_minutes"
META_PRE_ACTIONS: Final = "pre_actions"
META_POST_ACTIONS: Final = "post_actions"
META_FAILURE_ACTIONS: Final = "failure_actions"

EVENT_ALARM_TRIGGERED: Final = f"{DOMAIN}_alarm_triggered"
EVENT_ALARM_STOPPED: Final = f"{DOMAIN}_alarm_stopped"
EVENT_ALARM_SNOOZED: Final = f"{DOMAIN}_alarm_snoozed"
EVENT_ALARM_SKIPPED: Final = f"{DOMAIN}_alarm_skipped"
EVENT_ALARM_FAILED: Final = f"{DOMAIN}_alarm_failed"
EVENT_ALARM_OVERRIDE_CREATED: Final = f"{DOMAIN}_alarm_override_created"

OCCURRENCE_SCHEDULED: Final = "scheduled"
OCCURRENCE_SNOOZE: Final = "snooze"
OCCURRENCE_OVERRIDE: Final = "override"
OCCURRENCES: Final = (
    OCCURRENCE_SCHEDULED,
    OCCURRENCE_SNOOZE,
    OCCURRENCE_OVERRIDE,
)

ALARM_REPLAY_INTERVAL_SECONDS: Final = 8
VOLUME_RAMP_STEP_SECONDS: Final = 5
