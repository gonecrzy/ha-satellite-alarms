"""Deterministic Home Assistant Assist voice commands for Satellite Alarms."""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from hassil.recognize import RecognizeResult
from homeassistant.components.conversation import ConversationInput
from homeassistant.components.conversation.agent_manager import get_agent_manager
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .alarm_manager import AlarmManager
from .const import (
    CONF_ASSIST_SATELLITE,
    DOMAIN,
    RECURRENCE_DAILY,
    RECURRENCE_ONCE,
    RECURRENCE_WEEKDAYS,
    RECURRENCE_WEEKENDS,
)
from .playback import ActiveAlarmNotFoundError, PlaybackError, PlaybackManager

_LOGGER = logging.getLogger(__name__)

_ONE_TIME_SENTENCES = [
    "set [an] alarm (for|at) {time}",
    "set [my] alarm (for|at) {time}",
    "wake me [up] at {time}",
    "wake me [up] {time}",
]
_TODAY_SENTENCES = [
    "set [an] alarm (for|at) {time} today",
    "set [an] alarm today (for|at) {time}",
    "wake me [up] at {time} today",
    "wake me [up] today at {time}",
]
_TOMORROW_SENTENCES = [
    "set [an] alarm (for|at) {time} tomorrow",
    "set [an] alarm tomorrow (for|at) {time}",
    "wake me [up] at {time} tomorrow",
    "wake me [up] tomorrow at {time}",
]
_DAILY_SENTENCES = [
    "set [a] daily alarm (for|at) {time}",
    "set [an] alarm (for|at) {time} every day",
    "wake me [up] at {time} every day",
    "wake me [up] at {time} daily",
]
_WEEKDAY_SENTENCES = [
    "set [a] weekday alarm (for|at) {time}",
    "set [an] alarm (for|at) {time} on weekdays",
    "wake me [up] at {time} on weekdays",
    "wake me [up] at {time} weekdays",
]
_WEEKEND_SENTENCES = [
    "set [a] weekend alarm (for|at) {time}",
    "set [an] alarm (for|at) {time} on weekends",
    "wake me [up] at {time} on weekends",
    "wake me [up] at {time} weekends",
]
_STOP_SENTENCES = [
    "(stop|dismiss|turn off) [the] alarm",
    "(stop|dismiss) my alarm",
]
_SNOOZE_SENTENCES = [
    "snooze",
    "snooze [the] alarm",
    "snooze for {duration}",
    "snooze [the] alarm for {duration}",
]
_NEXT_SENTENCES = [
    "(what time is|when is) my next alarm",
    "(what time is|when is) the next alarm",
    "when does my next alarm go off",
]
_CANCEL_SENTENCES = [
    "(cancel|delete|remove) [my] next alarm",
    "(cancel|delete|remove) my alarm",
]

_CREATE_SENTENCES = [
    *_ONE_TIME_SENTENCES,
    *_TODAY_SENTENCES,
    *_TOMORROW_SENTENCES,
    *_DAILY_SENTENCES,
    *_WEEKDAY_SENTENCES,
    *_WEEKEND_SENTENCES,
]

_SMALL_NUMBERS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}


class VoiceCommandError(ValueError):
    """Raised when a deterministic voice command cannot be completed."""


class VoiceController:
    """Register and handle room-local voice alarm commands."""

    def __init__(
        self,
        hass: HomeAssistant,
        manager: AlarmManager,
        playback: PlaybackManager,
    ) -> None:
        """Initialize voice control."""
        self.hass = hass
        self.manager = manager
        self.playback = playback
        self._unregister: list[CALLBACK_TYPE] = []

    def register(self) -> None:
        """Register deterministic sentence triggers with Home Assistant Assist."""
        if self._unregister:
            return

        agent_manager = get_agent_manager(self.hass)
        groups = [
            (_CREATE_SENTENCES, self.async_create),
            (_STOP_SENTENCES, self.async_stop),
            (_SNOOZE_SENTENCES, self.async_snooze),
            (_NEXT_SENTENCES, self.async_next_alarm),
            (_CANCEL_SENTENCES, self.async_cancel_next),
        ]

        for sentences, callback in groups:
            self._unregister.append(agent_manager.register_trigger(sentences, callback))

    def unregister(self) -> None:
        """Unregister all sentence triggers."""
        while self._unregister:
            self._unregister.pop()()

    async def async_create(
        self, user_input: ConversationInput, result: RecognizeResult
    ) -> str:
        """Classify and create an alarm from one deterministic voice trigger."""
        text = _normalize_spoken_text(user_input.text)

        if "weekday" in text:
            recurrence = RECURRENCE_WEEKDAYS
        elif "weekend" in text:
            recurrence = RECURRENCE_WEEKENDS
        elif "daily" in text or "every day" in text:
            recurrence = RECURRENCE_DAILY
        else:
            recurrence = RECURRENCE_ONCE

        date_offset: int | None = None
        if recurrence == RECURRENCE_ONCE:
            if "tomorrow" in text:
                date_offset = 1
            elif "today" in text:
                date_offset = 0

        return await self.async_create_alarm(
            user_input,
            result,
            recurrence=recurrence,
            date_offset=date_offset,
        )

    def resolve_endpoint_id(self, user_input: ConversationInput) -> str:
        """Resolve the configured endpoint that owns the originating satellite."""
        entries = self.hass.config_entries.async_entries(DOMAIN)

        if user_input.satellite_id:
            matches = [
                entry
                for entry in entries
                if entry.data.get(CONF_ASSIST_SATELLITE) == user_input.satellite_id
            ]
            if len(matches) == 1:
                return matches[0].entry_id

        if user_input.device_id:
            entity_registry = er.async_get(self.hass)
            matches = []
            for entry in entries:
                satellite_entity_id = entry.data.get(CONF_ASSIST_SATELLITE)
                if not satellite_entity_id:
                    continue
                satellite_entry = entity_registry.async_get(satellite_entity_id)
                if satellite_entry and satellite_entry.device_id == user_input.device_id:
                    matches.append(entry)

            if len(matches) == 1:
                return matches[0].entry_id

        raise VoiceCommandError("I couldn't match this voice satellite to a Satellite Alarms room.")

    @staticmethod
    def _slot(result: RecognizeResult, name: str) -> str:
        """Return a required wildcard slot."""
        entity = result.entities.get(name)
        if entity is None:
            raise VoiceCommandError(f"I couldn't understand the {name}.")
        return str(entity.value).strip()

    async def async_create_alarm(
        self,
        user_input: ConversationInput,
        result: RecognizeResult,
        *,
        recurrence: str,
        date_offset: int | None,
    ) -> str:
        """Create an alarm from a deterministic sentence."""
        try:
            endpoint_id = self.resolve_endpoint_id(user_input)
            time_value = parse_alarm_time(_clean_alarm_time_slot(self._slot(result, "time")))
            date_value = None
            if date_offset is not None:
                date_value = (dt_util.now().date() + timedelta(days=date_offset)).isoformat()

            record = await self.manager.async_create(
                endpoint_id=endpoint_id,
                time_value=time_value,
                recurrence=recurrence,
                date_value=date_value,
            )
        except (VoiceCommandError, ValueError) as err:
            return str(err)
        except Exception:
            _LOGGER.exception("Could not create alarm from voice command")
            return "I couldn't create that alarm."

        suffix = {
            RECURRENCE_ONCE: "",
            RECURRENCE_DAILY: " every day",
            RECURRENCE_WEEKDAYS: " on weekdays",
            RECURRENCE_WEEKENDS: " on weekends",
        }[recurrence]
        return f"Alarm set for {format_clock_time(str(record.metadata['time']))}{suffix}."

    async def async_stop(self, user_input: ConversationInput, _result: RecognizeResult) -> str:
        """Stop the alarm ringing on the originating endpoint."""
        try:
            endpoint_id = self.resolve_endpoint_id(user_input)
            await self.playback.async_stop(endpoint_id=endpoint_id)
        except VoiceCommandError as err:
            return str(err)
        except ActiveAlarmNotFoundError:
            return "There is no alarm ringing in this room."
        except PlaybackError:
            _LOGGER.exception("Could not stop alarm from voice command")
            return "I couldn't stop the alarm."
        return "Alarm stopped."

    async def async_snooze(
        self, user_input: ConversationInput, result: RecognizeResult
    ) -> str:
        """Snooze using the endpoint default or a spoken duration."""
        minutes = None
        if result.entities.get("duration") is not None:
            try:
                minutes = parse_snooze_minutes(self._slot(result, "duration"))
            except VoiceCommandError as err:
                return str(err)
        return await self._async_snooze(user_input, minutes=minutes)

    async def _async_snooze(self, user_input: ConversationInput, *, minutes: int | None) -> str:
        """Snooze the alarm ringing on the originating endpoint."""
        try:
            endpoint_id = self.resolve_endpoint_id(user_input)
            _active, actual_minutes, _entity_id = await self.playback.async_snooze(
                endpoint_id=endpoint_id,
                minutes=minutes,
            )
        except VoiceCommandError as err:
            return str(err)
        except ActiveAlarmNotFoundError:
            return "There is no alarm ringing in this room."
        except PlaybackError:
            _LOGGER.exception("Could not snooze alarm from voice command")
            return "I couldn't snooze the alarm."
        return f"Snoozed for {actual_minutes} minutes."

    async def async_next_alarm(
        self, user_input: ConversationInput, _result: RecognizeResult
    ) -> str:
        """Report the next scheduled alarm for the originating endpoint."""
        try:
            endpoint_id = self.resolve_endpoint_id(user_input)
            next_alarm = self.manager.next_alarm_for_endpoint(endpoint_id)
        except VoiceCommandError as err:
            return str(err)

        if next_alarm is None:
            return "There are no scheduled alarms in this room."

        _record, trigger = next_alarm
        return f"Your next alarm is {format_trigger_time(trigger)}."

    async def async_cancel_next(
        self, user_input: ConversationInput, _result: RecognizeResult
    ) -> str:
        """Delete the next scheduled alarm for the originating endpoint."""
        try:
            endpoint_id = self.resolve_endpoint_id(user_input)
            next_alarm = self.manager.next_alarm_for_endpoint(endpoint_id)
            if next_alarm is None:
                return "There are no scheduled alarms in this room."
            record, trigger = next_alarm
            await self.manager.async_delete(record.alarm_id)
        except VoiceCommandError as err:
            return str(err)
        except Exception:
            _LOGGER.exception("Could not cancel alarm from voice command")
            return "I couldn't cancel the alarm."

        return f"Canceled the alarm {format_trigger_time(trigger)}."


def _clean_alarm_time_slot(value: str) -> str:
    """Remove recurrence/date words that a broad wildcard may capture."""
    text = _normalize_spoken_text(value)

    for prefix in ("tomorrow at ", "today at ", "at ", "for "):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break

    suffixes = (
        " on weekdays",
        " weekdays",
        " on weekends",
        " weekends",
        " every day",
        " daily",
        " tomorrow",
        " today",
    )
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()
                changed = True
                break

    return text


def _normalize_spoken_text(value: str) -> str:
    """Normalize speech-to-text output for deterministic parsing."""
    value = value.lower().strip()
    value = value.replace(".", "")
    value = value.replace("-", " ")
    value = re.sub(r"\s+", " ", value)
    return value


def _parse_number_words(tokens: list[str]) -> int | None:
    """Parse a small spoken number from zero through fifty-nine."""
    if not tokens:
        return None
    if tokens == ["a"] or tokens == ["an"]:
        return 1
    if len(tokens) == 1:
        if tokens[0].isdigit():
            return int(tokens[0])
        if tokens[0] in _SMALL_NUMBERS:
            return _SMALL_NUMBERS[tokens[0]]
        return _TENS.get(tokens[0])
    if len(tokens) == 2 and tokens[0] == "oh":
        return _SMALL_NUMBERS.get(tokens[1])
    if len(tokens) == 2 and tokens[0] in _TENS and tokens[1] in _SMALL_NUMBERS:
        return _TENS[tokens[0]] + _SMALL_NUMBERS[tokens[1]]
    return None


def parse_alarm_time(value: str) -> str:
    """Parse common spoken alarm times into Scheduler's HH:MM:SS format."""
    text = _normalize_spoken_text(value)
    if text == "noon":
        return "12:00:00"
    if text == "midnight":
        return "00:00:00"

    meridiem: str | None = None
    replacements = (
        (" in the morning", " am"),
        (" this morning", " am"),
        (" in the afternoon", " pm"),
        (" this afternoon", " pm"),
        (" in the evening", " pm"),
        (" this evening", " pm"),
        (" at night", " pm"),
    )
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new)

    meridiem_match = re.search(r"\s*(am|pm|a m|p m)$", text)
    if meridiem_match:
        meridiem = meridiem_match.group(1).replace(" ", "")
        text = text[: meridiem_match.start()].strip()

    text = re.sub(r"\s*o\s*clock$", "", text).strip()

    hour: int | None = None
    minute = 0

    colon_match = re.fullmatch(r"(\d{1,2}):(\d{1,2})", text)
    if colon_match:
        hour = int(colon_match.group(1))
        minute = int(colon_match.group(2))
    else:
        tokens = text.split()
        if tokens and tokens[0].isdigit():
            hour = int(tokens[0])
            if len(tokens) > 1:
                parsed_minute = _parse_number_words(tokens[1:])
                if parsed_minute is None:
                    raise VoiceCommandError("I couldn't understand the alarm time.")
                minute = parsed_minute
        elif tokens and tokens[0] in _SMALL_NUMBERS:
            hour = _SMALL_NUMBERS[tokens[0]]
            if len(tokens) > 1:
                parsed_minute = _parse_number_words(tokens[1:])
                if parsed_minute is None:
                    raise VoiceCommandError("I couldn't understand the alarm time.")
                minute = parsed_minute

    if hour is None or minute > 59:
        raise VoiceCommandError("I couldn't understand the alarm time.")

    if meridiem:
        if not 1 <= hour <= 12:
            raise VoiceCommandError("I couldn't understand the alarm time.")
        hour = (
            (0 if hour == 12 else hour)
            if meridiem == "am"
            else (12 if hour == 12 else hour + 12)
        )
    elif not 0 <= hour <= 23:
        raise VoiceCommandError("I couldn't understand the alarm time.")

    return f"{hour:02d}:{minute:02d}:00"


def parse_snooze_minutes(value: str) -> int:
    """Parse a spoken snooze duration into minutes."""
    text = _normalize_spoken_text(value).replace(" and ", " ")
    if text in {"half an hour", "half a hour", "half hour"}:
        return 30

    total = 0
    hour_match = re.search(r"(.+?)\s+hours?\b", text)
    if hour_match:
        hours = _parse_number_words(hour_match.group(1).split())
        if hours is None:
            raise VoiceCommandError("I couldn't understand the snooze duration.")
        total += hours * 60
        text = text[hour_match.end() :].strip()

    minute_match = re.search(r"(.+?)\s+minutes?\b", text)
    if minute_match:
        minutes = _parse_number_words(minute_match.group(1).split())
        if minutes is None:
            raise VoiceCommandError("I couldn't understand the snooze duration.")
        total += minutes
    elif total == 0:
        minutes = _parse_number_words(text.split())
        if minutes is None:
            raise VoiceCommandError("I couldn't understand the snooze duration.")
        total = minutes

    if not 1 <= total <= 120:
        raise VoiceCommandError("Snooze must be between 1 and 120 minutes.")
    return total


def format_clock_time(value: str) -> str:
    """Format HH:MM:SS for a concise spoken response."""
    parsed = dt_util.parse_time(value)
    if parsed is None:
        return value
    hour = parsed.hour
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    if parsed.minute:
        return f"{display_hour}:{parsed.minute:02d} {suffix}"
    return f"{display_hour} {suffix}"


def format_trigger_time(trigger) -> str:
    """Format a Scheduler next-trigger timestamp for speech."""
    local = dt_util.as_local(trigger)
    today = dt_util.now().date()
    if local.date() == today:
        date_text = "today"
    elif local.date() == today + timedelta(days=1):
        date_text = "tomorrow"
    else:
        date_text = f"on {local.strftime('%A, %B')} {local.day}"
    return f"at {format_clock_time(local.strftime('%H:%M:%S'))} {date_text}"
