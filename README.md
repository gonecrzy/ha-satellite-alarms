# Home Assistant Satellite Alarms

Room-aware wake-up alarms for Home Assistant voice satellites.

**Satellite Alarms** is a planned Home Assistant custom integration for creating, managing, and ringing alarms on the specific Assist satellite where the request originated.

The initial use case is a house with multiple voice satellites—such as EchoMuse-converted Echo Dots—where someone can say:

- "Set an alarm for 6 AM."
- "Wake me at 6:30 on weekdays."
- "Set a daily alarm for 8 AM."
- "What time is my next alarm?"
- "Snooze for 10 minutes."
- "Stop."

The alarm should belong to that room and ring only on that room's configured speaker.

> **Project status:** Planning / initial development. This repository does not yet contain a usable integration.

## Goals

- Native-feeling voice alarms for Home Assistant Assist.
- Automatic room targeting from the originating `assist_satellite`.
- Generic support for Assist satellites and media players; no EchoMuse-specific dependency.
- Persistent alarms that survive Home Assistant restarts.
- One-time and recurring alarms.
- Room-local stop and snooze behavior.
- Safe volume handling: save, raise/ramp, ring, then restore.
- Multiple alarms per room as the project matures.
- Services that can also be called from dashboards, automations, scripts, and LLM tools.

## Proposed architecture

```text
Voice request
     |
     v
Home Assistant Assist
     |
     +--> originating assist_satellite
     |
     v
Satellite Alarms integration
     |
     +--> persistent alarm store
     +--> scheduling engine
     +--> room/satellite mapping
     +--> alarm state
     |
     v
Configured media_player
     |
     v
Alarm sound / announcement
```

Each configured room will associate an Assist satellite with the media player that should ring there.

```text
assist_satellite.bedroom_voice_assistant
        |
        +--> media_player.bedroom_voice_assistant
        +--> Bedroom alarm collection
```

The design is intentionally generic. EchoMuse satellites are a primary development target, but the integration should work with other Home Assistant voice satellites and compatible media players.

## Initial feature set

The first usable release is intended to support:

- One-time alarms.
- Daily recurring alarms.
- Weekday recurring alarms.
- Automatic originating-satellite routing.
- Enable/disable and cancel.
- Query next alarm.
- Stop.
- Snooze and configurable snooze duration.
- Alarm sound selection.
- Configurable alarm volume.
- Save and restore prior media-player volume.
- Optional gradual volume ramp.
- Persistent storage and restart recovery.

See [Project Plan](docs/PROJECT_PLAN.md) for the proposed architecture, restrictions, data model, and version roadmap.

## Planned voice examples

```text
Set an alarm for 6 AM.
Set a daily alarm for 8 AM.
Wake me at 6:30 on weekdays.
What time is my next alarm?
Cancel my alarm.
Stop.
Snooze.
Snooze for 15 minutes.
```

Later versions may add named alarms, selected weekdays, skip-next, temporary overrides, pre/post alarm actions, morning briefings, fallback speakers, and richer dashboard controls.

## Design principles

### Room-local by default

If a command is spoken to the Bedroom satellite, an unqualified alarm command should affect Bedroom. A user should not have to say the room name every time.

### Deterministic alarm control

Alarm creation, scheduling, stop, and snooze should not require an LLM. LLM tool support may be added, but the core alarm path should remain deterministic.

### No duplicate timer system

Home Assistant already provides satellite-bound timers. Satellite Alarms is intended for absolute clock-time alarms and recurring wake-up schedules, not countdown timers.

### Do not hard-code EchoMuse

The integration should depend on Home Assistant entity capabilities, not a particular satellite firmware or vendor.

### Reliability before advanced features

Wake-up alarms are time-sensitive. Persistence, restart behavior, volume restoration, and predictable routing take priority over advanced conversational features.

## Proposed limitations for early releases

Early releases may intentionally limit:

- Recurrence choices to one-time, daily, weekdays, and weekends.
- Alarm playback to one configured media player per satellite.
- Voice commands to a documented set of sentence patterns.
- One active ringing alarm per room.
- Advanced media restoration beyond volume.
- Cross-room alarm control unless a room is explicitly named.
- LLM-created alarms until the deterministic service API is stable.

These restrictions can be relaxed in later versions without changing the core alarm model.

## Development roadmap

| Version | Focus |
| --- | --- |
| v0.1 | Integration skeleton, config flow, room mapping, persistent alarm model |
| v0.2 | Scheduling, one-time/daily/weekday alarms, basic services |
| v0.3 | Alarm playback, volume save/ramp/restore, stop and snooze |
| v0.4 | Native Assist voice commands and originating-satellite routing |
| v0.5 | Multiple alarms, query/cancel by time or name, richer recurrence |
| v0.6 | Skip-next, temporary overrides, pre/post actions, fallback behavior |
| v0.7 | Dashboard entities/cards and polish |
| v1.0 | Stable storage schema, migration support, documented compatibility and release |

The roadmap is provisional and may change during implementation.

## Repository layout

Planned structure:

```text
custom_components/
  satellite_alarms/
    __init__.py
    manifest.json
    config_flow.py
    const.py
    coordinator.py
    models.py
    storage.py
    scheduler.py
    alarm_manager.py
    services.yaml
    strings.json
    translations/
      en.json

docs/
  PROJECT_PLAN.md
```

The internal file layout may change as the implementation develops.

## Installation

Not available yet.

When an installable release exists, the intended installation path is HACS custom repository support plus Home Assistant's normal integration config flow.

## Contributing

The project is in its design phase. Issues and pull requests should focus on concrete alarm behavior, Home Assistant compatibility, satellite/media-player behavior, and reliability.

Please avoid designing features around one specific hardware platform when the same behavior can be expressed through standard Home Assistant entities.

## License

A license has not yet been selected.
