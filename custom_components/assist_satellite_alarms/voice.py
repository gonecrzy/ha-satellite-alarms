"""Deterministic Home Assistant Assist voice commands for Satellite Alarms."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from hassil.recognize import RecognizeResult
from homeassistant.components.conversation import ConversationInput
from homeassistant.components.conversation.agent_manager import get_agent_manager
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .alarm_manager import AlarmManager
from .const import (
    DOMAIN,
    META_RECURRENCE,
    META_TIME,
    RECURRENCE_DAILY,
    RECURRENCE_ONCE,
    RECURRENCE_SELECTED_DAYS,
    RECURRENCE_WEEKDAYS,
    RECURRENCE_WEEKENDS,
)
from .models import AlarmEndpoint, AlarmRecord
from .playback import ActiveAlarmNotFoundError, PlaybackError, PlaybackManager

_LOGGER = logging.getLogger(__name__)

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
_NAMED_CREATE_SENTENCES = [
    "set [an] alarm (called|named) {name} (for|at) {time}",
    "set [a] {name} alarm (for|at) {time}",
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
_ONE_TIME_SENTENCES = [
    "set [an] alarm (for|at) {time}",
    "set [my] alarm (for|at) {time}",
    "wake me [up] at {time}",
    "wake me [up] {time}",
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
_QUERY_SENTENCES = [
    *_NEXT_SENTENCES,
    "(what time is|when is) my {selector} alarm",
    "(what time is|when is) the {selector} alarm",
]
_LIST_SENTENCES = [
    "what alarms do I have",
    "what are my alarms",
    "list my alarms",
    "tell me my alarms",
]
_CANCEL_SENTENCES = [
    "(cancel|delete|remove) [my] next alarm",
    "(cancel|delete|remove) my alarm",
    "(cancel|delete|remove) my {selector} alarm",
    "(cancel|delete|remove) the {selector} alarm",
]
_SKIP_SENTENCES = [
    "skip my next alarm",
    "skip [the] next alarm",
    "skip tomorrow's alarm",
    "skip my alarm tomorrow",
    "skip my {selector} alarm",
    "skip the {selector} alarm",
]
_OVERRIDE_SENTENCES = [
    "tomorrow wake me [up] at {time} instead",
    "change my next alarm to {time} tomorrow",
    "set my next alarm to {time} tomorrow",
    "move my next alarm to {time} tomorrow",
]

_CREATE_SENTENCES = [
    *_DAILY_SENTENCES,
    *_WEEKDAY_SENTENCES,
    *_WEEKEND_SENTENCES,
    *_NAMED_CREATE_SENTENCES,
    *_TODAY_SENTENCES,
    *_TOMORROW_SENTENCES,
    *_ONE_TIME_SENTENCES,
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
_WEEKDAY_WORDS = {
    "monday": "mon",
    "mon": "mon",
    "tuesday": "tue",
    "tue": "tue",
    "tues": "tue",
    "wednesday": "wed",
    "wed": "wed",
    "thursday": "thu",
    "thu": "thu",
    "thur": "thu",
    "thurs": "thu",
    "friday": "fri",
    "fri": "fri",
    "saturday": "sat",
    "sat": "sat",
    "sunday": "sun",
    "sun": "sun",
}
_WEEKDAY_LABELS = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday",
}
_WEEKDAY_ORDER = tuple(_WEEKDAY_LABELS)


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
            (_QUERY_SENTENCES, self.async_query_alarm),
            (_LIST_SENTENCES, self.async_list_alarms),
            (_CANCEL_SENTENCES, self.async_cancel_alarm),
            (_SKIP_SENTENCES, self.async_skip_alarm),
            (_OVERRIDE_SENTENCES, self.async_override_next),
        ]

        for sentences, callback in groups:
            self._unregister.append(agent_manager.register_trigger(sentences, callback))

    def unregister(self) -> None:
        """Unregister all sentence triggers."""
        while self._unregister:
            self._unregister.pop()()

    async def async_create(self, user_input: ConversationInput, result: RecognizeResult) -> str:
        """Classify and create an alarm from one deterministic voice trigger."""
        text = _normalize_spoken_text(user_input.text)
        selected_days = _selected_days_from_command(text)

        if "weekday" in text:
            recurrence = RECURRENCE_WEEKDAYS
            selected_days = None
        elif "weekend" in text:
            recurrence = RECURRENCE_WEEKENDS
            selected_days = None
        elif "daily" in text or "every day" in text:
            recurrence = RECURRENCE_DAILY
            selected_days = None
        elif selected_days:
            recurrence = RECURRENCE_SELECTED_DAYS
        else:
            recurrence = RECURRENCE_ONCE

        date_offset: int | None = None
        if recurrence == RECURRENCE_ONCE:
            if "tomorrow" in text:
                date_offset = 1
            elif "today" in text:
                date_offset = 0

        name = self._optional_slot(result, "name")
        return await self.async_create_alarm(
            user_input,
            result,
            recurrence=recurrence,
            date_offset=date_offset,
            days=selected_days,
            name=name,
        )

    def resolve_endpoint_id(self, user_input: ConversationInput) -> str:
        """Resolve the room endpoint that owns the originating satellite."""
        entries = self.hass.config_entries.async_entries(DOMAIN)

        if user_input.satellite_id:
            matches = [
                entry
                for entry in entries
                if user_input.satellite_id
                in AlarmEndpoint.from_config_entry(entry).assist_satellite_entity_ids
            ]
            if len(matches) == 1:
                return matches[0].entry_id

        if user_input.device_id:
            entity_registry = er.async_get(self.hass)
            matches = []
            for entry in entries:
                endpoint = AlarmEndpoint.from_config_entry(entry)
                if any(
                    (satellite_entry := entity_registry.async_get(satellite_entity_id))
                    and satellite_entry.device_id == user_input.device_id
                    for satellite_entity_id in endpoint.assist_satellite_entity_ids
                ):
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

    @staticmethod
    def _optional_slot(result: RecognizeResult, name: str) -> str | None:
        """Return an optional wildcard slot."""
        entity = result.entities.get(name)
        if entity is None:
            return None
        value = str(entity.value).strip()
        return value or None

    async def async_create_alarm(
        self,
        user_input: ConversationInput,
        result: RecognizeResult,
        *,
        recurrence: str,
        date_offset: int | None,
        days: list[str] | None = None,
        name: str | None = None,
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
                days=days,
                name=name,
            )
        except (VoiceCommandError, ValueError) as err:
            return str(err)
        except Exception:
            _LOGGER.exception("Could not create alarm from voice command")
            return "I couldn't create that alarm."

        prefix = f"{record.name} alarm set" if name else "Alarm set"
        return f"{prefix} for {format_clock_time(str(record.metadata['time']))}{_recurrence_suffix(record)}."

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

    async def async_snooze(self, user_input: ConversationInput, result: RecognizeResult) -> str:
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

    async def async_query_alarm(
        self, user_input: ConversationInput, result: RecognizeResult
    ) -> str:
        """Report the next alarm or a named/time-selected alarm."""
        try:
            endpoint_id = self.resolve_endpoint_id(user_input)
            selector = self._optional_slot(result, "selector")
            if selector:
                record = self._resolve_alarm_selector(endpoint_id, selector)
                return f"{_display_alarm_name(record)} is set {_alarm_schedule_phrase(record, self.manager)}."

            next_alarm = self.manager.next_alarm_for_endpoint(endpoint_id)
        except VoiceCommandError as err:
            return str(err)

        if next_alarm is None:
            return "There are no scheduled alarms in this room."

        _record, trigger = next_alarm
        return f"Your next alarm is {format_trigger_time(trigger)}."

    async def async_list_alarms(
        self, user_input: ConversationInput, _result: RecognizeResult
    ) -> str:
        """List alarms configured for the originating endpoint."""
        try:
            endpoint_id = self.resolve_endpoint_id(user_input)
            records = self.manager.sorted_alarms_for_endpoint(endpoint_id)
        except VoiceCommandError as err:
            return str(err)

        if not records:
            return "There are no scheduled alarms in this room."

        shown = records[:5]
        descriptions = [
            f"{_display_alarm_name(record)} {_alarm_schedule_phrase(record, self.manager)}"
            for record in shown
        ]
        response = f"You have {len(records)} alarm{'s' if len(records) != 1 else ''}: "
        response += "; ".join(descriptions)
        if len(records) > len(shown):
            response += f"; and {len(records) - len(shown)} more"
        return f"{response}."

    async def async_skip_alarm(self, user_input: ConversationInput, result: RecognizeResult) -> str:
        """Skip one upcoming occurrence without changing the parent schedule."""
        try:
            endpoint_id = self.resolve_endpoint_id(user_input)
            selector = self._optional_slot(result, "selector")
            if selector:
                record = self._resolve_alarm_selector(endpoint_id, selector)
            else:
                next_alarm = self.manager.next_alarm_for_endpoint(endpoint_id)
                if next_alarm is None:
                    return "There are no scheduled alarms in this room."
                record, trigger = next_alarm
                if "tomorrow" in _normalize_spoken_text(user_input.text):
                    tomorrow = dt_util.now().date() + timedelta(days=1)
                    if dt_util.as_local(trigger).date() != tomorrow:
                        return "There is no alarm scheduled for tomorrow in this room."

            await self.manager.async_set_skip_next(record.alarm_id)
        except VoiceCommandError as err:
            return str(err)
        except Exception:
            _LOGGER.exception("Could not skip alarm from voice command")
            return "I couldn't skip the alarm."

        return f"Okay. I'll skip the next {_display_alarm_name(record)}."

    async def async_override_next(
        self, user_input: ConversationInput, result: RecognizeResult
    ) -> str:
        """Temporarily move the room's next alarm occurrence."""
        try:
            endpoint_id = self.resolve_endpoint_id(user_input)
            next_alarm = self.manager.next_alarm_for_endpoint(endpoint_id)
            if next_alarm is None:
                return "There are no scheduled alarms in this room."

            record, trigger = next_alarm
            time_value = parse_alarm_time(_clean_alarm_time_slot(self._slot(result, "time")))
            target_date = (
                dt_util.now().date() + timedelta(days=1)
                if "tomorrow" in _normalize_spoken_text(user_input.text)
                else dt_util.as_local(trigger).date()
            )
            await self.manager.async_override_next(
                record.alarm_id,
                time_value=time_value,
                date_value=target_date.isoformat(),
            )
            parsed_time = dt_util.parse_time(time_value)
            if parsed_time is None:
                raise VoiceCommandError("I couldn't understand the alarm time.")
            target = datetime.combine(target_date, parsed_time, tzinfo=dt_util.now().tzinfo)
        except (VoiceCommandError, ValueError) as err:
            return str(err)
        except Exception:
            _LOGGER.exception("Could not override alarm from voice command")
            return "I couldn't change the next alarm."

        return (
            f"Okay. The next {_display_alarm_name(record)} will ring "
            f"{format_trigger_time(target)} instead."
        )

    async def async_cancel_alarm(
        self, user_input: ConversationInput, result: RecognizeResult
    ) -> str:
        """Delete the next alarm or a named/time-selected alarm."""
        try:
            endpoint_id = self.resolve_endpoint_id(user_input)
            selector = self._optional_slot(result, "selector")
            if selector:
                record = self._resolve_alarm_selector(endpoint_id, selector)
                description = (
                    f"{_display_alarm_name(record)} {_alarm_schedule_phrase(record, self.manager)}"
                )
            else:
                next_alarm = self.manager.next_alarm_for_endpoint(endpoint_id)
                if next_alarm is None:
                    return "There are no scheduled alarms in this room."
                record, trigger = next_alarm
                description = f"the alarm {format_trigger_time(trigger)}"

            await self.manager.async_delete(record.alarm_id)
        except VoiceCommandError as err:
            return str(err)
        except Exception:
            _LOGGER.exception("Could not cancel alarm from voice command")
            return "I couldn't cancel the alarm."

        return f"Canceled {description}."

    def _resolve_alarm_selector(self, endpoint_id: str, selector: str) -> AlarmRecord:
        """Resolve a room-local alarm by exact name first, then by time."""
        name_matches = self.manager.find_by_name(endpoint_id, selector)
        if len(name_matches) == 1:
            return name_matches[0]
        if len(name_matches) > 1:
            raise VoiceCommandError(f"More than one alarm is named {selector} in this room.")

        try:
            time_value = parse_alarm_time(_clean_alarm_time_slot(selector))
        except VoiceCommandError:
            raise VoiceCommandError(
                f"I couldn't find an alarm called {selector} in this room."
            ) from None

        time_matches = self.manager.find_by_time(endpoint_id, time_value)
        if len(time_matches) == 1:
            return time_matches[0]
        if len(time_matches) > 1:
            raise VoiceCommandError(
                f"More than one alarm is set for {format_clock_time(time_value)} in this room."
            )
        raise VoiceCommandError(
            f"I couldn't find an alarm at {format_clock_time(time_value)} in this room."
        )


def _clean_alarm_time_slot(value: str) -> str:
    """Remove recurrence/date words that a broad wildcard may capture."""
    text = _normalize_spoken_text(value)

    for prefix in ("tomorrow at ", "today at ", "at ", "for "):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break

    if " on " in text:
        candidate_time, candidate_days = text.rsplit(" on ", 1)
        if parse_weekday_selection(candidate_days):
            text = candidate_time.strip()

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
    value = value.replace(",", " ")
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
            (0 if hour == 12 else hour) if meridiem == "am" else (12 if hour == 12 else hour + 12)
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


def parse_weekday_selection(value: str) -> list[str]:
    """Parse weekday names from a deterministic spoken phrase."""
    text = _normalize_spoken_text(value)
    found = {
        canonical for token in text.split() if (canonical := _WEEKDAY_WORDS.get(token)) is not None
    }
    return [day for day in _WEEKDAY_ORDER if day in found]


def _selected_days_from_command(value: str) -> list[str] | None:
    """Return selected weekdays only when they occur in an 'on ...' command suffix."""
    text = _normalize_spoken_text(value)
    if " on " not in text:
        return None
    suffix = text.rsplit(" on ", 1)[1]
    days = parse_weekday_selection(suffix)
    return days or None


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


def _format_days(days: list[str] | tuple[str, ...] | None) -> str:
    """Format canonical weekdays for speech."""
    labels = [_WEEKDAY_LABELS[day] for day in _WEEKDAY_ORDER if days and day in days]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return f"{', '.join(labels[:-1])}, and {labels[-1]}"


def _recurrence_suffix(record: AlarmRecord) -> str:
    """Return a spoken recurrence suffix for an alarm."""
    recurrence = record.metadata.get(META_RECURRENCE)
    if recurrence == RECURRENCE_DAILY:
        return " every day"
    if recurrence == RECURRENCE_WEEKDAYS:
        return " on weekdays"
    if recurrence == RECURRENCE_WEEKENDS:
        return " on weekends"
    if recurrence == RECURRENCE_SELECTED_DAYS:
        days = _format_days(record.metadata.get("days"))
        return f" on {days}" if days else ""
    return ""


def _display_alarm_name(record: AlarmRecord) -> str:
    """Return a concise spoken alarm name."""
    name = (record.name or "alarm").strip()
    return name if name.lower().endswith("alarm") else f"{name} alarm"


def _alarm_schedule_phrase(record: AlarmRecord, manager: AlarmManager) -> str:
    """Return a concise spoken schedule description for an alarm."""
    recurrence = record.metadata.get(META_RECURRENCE)
    if recurrence == RECURRENCE_ONCE:
        trigger = manager.trigger_for_record(record)
        if trigger is not None:
            return format_trigger_time(trigger)
    time_value = str(record.metadata.get(META_TIME) or "")
    return f"at {format_clock_time(time_value)}{_recurrence_suffix(record)}"
