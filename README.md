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

> **Project status:** v0.2 development. Endpoint configuration and Scheduler-backed alarm management are implemented. Alarm audio, stop/snooze playback control, and voice commands are not implemented yet.

## Goals

- Native-feeling voice alarms for Home Assistant Assist.
- Automatic room targeting from the originating `assist_satellite`.
- Generic support for Assist satellites and media players; no EchoMuse-specific dependency.
- Persistent alarms backed by Scheduler Component.
- One-time and recurring alarms using Scheduler Component's schedule engine.
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
     +--> room/satellite mapping
     +--> alarm metadata/state
     +--> stop/snooze/playback logic
     |
     v
Scheduler Component
     |
     +--> persistent schedule
     +--> recurrence / next trigger
     +--> scheduler switch entity
     |
     v
Satellite Alarms fire action
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

## Integration domain

The Home Assistant integration domain is `assist_satellite_alarms`. The project and UI display name remain **Satellite Alarms**.

Services/actions provided by this integration use this namespace, for example `assist_satellite_alarms.create`, `assist_satellite_alarms.stop`, and `assist_satellite_alarms.snooze`.

## Required dependency

Satellite Alarms is designed on top of [Scheduler Component](https://github.com/nielsfaber/scheduler-component). Scheduler Component owns the actual time schedules, recurrence, persistence, enable/disable state, and `next_trigger` calculation. Satellite Alarms adds the alarm-specific behavior that Scheduler Component does not provide: Assist-satellite room routing, alarm metadata, playback, volume handling, stop/snooze, and voice commands.

Development begins against Scheduler Component 3.x (currently 3.3.8). The dependency will be isolated behind a scheduler adapter so it can be changed later without rewriting the alarm/voice layers.

## Current v0.2 actions

The v0.2 service layer provides:

```text
assist_satellite_alarms.create
assist_satellite_alarms.update
assist_satellite_alarms.delete
assist_satellite_alarms.enable
assist_satellite_alarms.disable
assist_satellite_alarms.fire
```

Example one-time alarm:

```yaml
action: assist_satellite_alarms.create
data:
  endpoint_id: <Satellite Alarms config entry ID>
  time: "06:30:00"
  recurrence: once
```

Example weekday alarm:

```yaml
action: assist_satellite_alarms.create
data:
  endpoint_id: <Satellite Alarms config entry ID>
  time: "06:30:00"
  recurrence: weekdays
  name: Work
```

`create` returns the stable alarm ID and Scheduler entity mapping when a response is requested. Scheduler Component owns the actual persistent schedule. The internal `fire` action currently emits a room-targeted Home Assistant event; v0.3 will connect that callback to alarm playback.

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
- Scheduler-backed persistence and restart recovery.

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
| v0.1 | Integration skeleton, Scheduler dependency/adapter, config flow, room mapping, alarm metadata registry |
| v0.2 | Scheduler-backed one-time/daily/weekday alarms and basic services |
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
  assist_satellite_alarms/
    __init__.py
    manifest.json
    config_flow.py
    const.py
    coordinator.py
    models.py
    registry.py
    scheduler_adapter.py
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

There is not yet a tagged public release. For development testing, install and configure Scheduler Component first, then install this repository as a HACS custom integration and add each satellite endpoint through Home Assistant's normal integration config flow.

Until v0.3, scheduled alarms can be created and triggered through Scheduler Component, but they do not yet play alarm audio.

## Contributing

The project is in its design phase. Issues and pull requests should focus on concrete alarm behavior, Home Assistant compatibility, satellite/media-player behavior, and reliability.

Please avoid designing features around one specific hardware platform when the same behavior can be expressed through standard Home Assistant entities.

## License

A license has not yet been selected.
