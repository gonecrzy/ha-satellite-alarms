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

> **Project status:** v0.7 development. Room endpoints support multiple satellite/media-player pairs, native room status entities, reconfiguration, expanded diagnostics, and repair detection.

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

Each configured room owns one primary Assist satellite/media-player pair and may contain additional paired satellites and speakers. All satellites in the room resolve to the same alarm collection.

```text
Bedroom alarm endpoint
        |
        +--> assist_satellite.bedside_left
        |       +--> media_player.bedside_left
        |
        +--> assist_satellite.bedside_right
        |       +--> media_player.bedside_right
        |
        +--> shared Bedroom alarm collection
```

The design is intentionally generic. EchoMuse satellites are a primary development target, but the integration should work with other Home Assistant voice satellites and compatible media players.

## Integration domain

The Home Assistant integration domain is `assist_satellite_alarms`. The project and UI display name remain **Satellite Alarms**.

Services/actions provided by this integration use this namespace, for example `assist_satellite_alarms.create`, `assist_satellite_alarms.stop`, and `assist_satellite_alarms.snooze`.

## Required dependency

Satellite Alarms is designed on top of [Scheduler Component](https://github.com/nielsfaber/scheduler-component). Scheduler Component owns the actual time schedules, recurrence, persistence, enable/disable state, and `next_trigger` calculation. Satellite Alarms adds the alarm-specific behavior that Scheduler Component does not provide: Assist-satellite room routing, alarm metadata, playback, volume handling, stop/snooze, and voice commands.

Development begins against Scheduler Component 3.x (currently 3.3.8). The dependency will be isolated behind a scheduler adapter so it can be changed later without rewriting the alarm/voice layers.

## Current actions

The service layer provides:

```text
assist_satellite_alarms.create
assist_satellite_alarms.update
assist_satellite_alarms.delete
assist_satellite_alarms.enable
assist_satellite_alarms.disable
assist_satellite_alarms.fire
assist_satellite_alarms.list
assist_satellite_alarms.skip_next
assist_satellite_alarms.override_next
assist_satellite_alarms.stop
assist_satellite_alarms.snooze
```

Example one-time alarm:

```yaml
action: assist_satellite_alarms.create
data:
  endpoint_id: <Satellite Alarms config entry ID>
  time: "06:30:00"
  recurrence: once
```

Example selected-day named alarm:

```yaml
action: assist_satellite_alarms.create
data:
  endpoint_id: <Satellite Alarms config entry ID>
  time: "06:30:00"
  recurrence: selected_days
  days:
    - mon
    - wed
    - fri
  name: Work
```

`assist_satellite_alarms.list` returns alarm IDs, names, recurrence, selected days, Scheduler entity IDs, enabled state, next-trigger data, skip-next state, temporary override metadata, and per-alarm playback overrides.

`create` returns the stable alarm ID and Scheduler entity mapping when a response is requested. Scheduler Component owns the actual persistent schedule. The internal `fire` action now starts room-local alarm playback through the configured Assist satellite and media player.

### Skip and temporary override

Recurring alarms can skip exactly one normal Scheduler occurrence without changing the parent schedule:

```yaml
action: assist_satellite_alarms.skip_next
data:
  alarm_id: <alarm UUID>
```

A next occurrence can also be moved temporarily:

```yaml
action: assist_satellite_alarms.override_next
data:
  alarm_id: <alarm UUID>
  date: "2099-09-30"
  time: "07:00:00"
```

For recurring alarms, the integration creates a transient one-time Scheduler occurrence and marks the original next parent occurrence to be skipped. The recurring schedule itself remains unchanged. For one-time alarms, the existing parent schedule is edited directly.

Voice examples include `Skip my next alarm`, `Skip tomorrow's alarm`, and `Tomorrow wake me at 7 instead`.

### Stop and snooze

While an alarm is ringing, it can be stopped by stable alarm ID:

```yaml
action: assist_satellite_alarms.stop
data:
  alarm_id: <alarm UUID>
```

or by configured endpoint:

```yaml
action: assist_satellite_alarms.stop
data:
  endpoint_id: <Satellite Alarms config entry ID>
```

Snooze accepts the same selector and an optional duration:

```yaml
action: assist_satellite_alarms.snooze
data:
  endpoint_id: <Satellite Alarms config entry ID>
  minutes: 10
```

Snooze creates a temporary one-time Scheduler Component occurrence tied to the parent alarm. It does not alter the parent recurring schedule or create another normal alarm record.

### Per-alarm wake behavior

Create/update actions can override endpoint defaults per alarm:

- alarm media
- alarm volume
- snooze duration
- pre-alarm service actions
- post-stop/timeout service actions
- failure service actions

Simple service actions are stored as mappings such as:

```yaml
pre_actions:
  - action: light.turn_on
    target:
      entity_id: light.bedroom
    data:
      brightness_pct: 20
```

Playback failures emit `assist_satellite_alarms_alarm_failed`. Skip and override lifecycle events are also emitted for automations.

### Room status entities

Each configured room exposes standard Home Assistant entities:

```text
sensor.<room>_next_alarm
sensor.<room>_alarm_count
sensor.<room>_active_alarm
binary_sensor.<room>_alarm_ringing
```

These are local-push entities rather than polling sensors. Alarm registry changes, playback changes, and Scheduler state changes refresh them automatically.

The next-alarm sensor includes attributes such as alarm ID, name, recurrence, selected days, enabled state, Scheduler entity, skip-next state, and temporary override metadata. The active-alarm sensor exposes the current room playback mode and participating satellite/media-player targets.

The entities are grouped under one Home Assistant service device for the room endpoint.

### Diagnostics and repairs

Config-entry diagnostics include room target states, playback mode, Scheduler mapping state, active/queued alarms, next triggers, and alarm override/skip metadata.

Satellite Alarms also raises Home Assistant repair warnings when a configured satellite/media-player entity has been removed or when an active recurring/future alarm record has lost its Scheduler schedule. Repairs clear automatically when the missing target or schedule returns.

Room membership can be changed later with Home Assistant's **Reconfigure** action without recreating the alarm collection.

### Playback defaults

Each endpoint can be configured with:

- room playback mode: primary only, all room speakers, or primary with fallback
- target alarm volume
- default snooze duration
- gradual volume ramp and ramp duration
- maximum ring duration
- bundled two-tone alarm MP3 (default)
- optional custom alarm media
- spoken fallback alarm message

The default alarm sound is a bundled 4-second two-tone MP3 generated specifically for this project (alternating 740 Hz / 980 Hz pulses, mono, 64 kbps). It is served locally by Home Assistant and repeated with no preannounce chime.

A custom endpoint media URL/media-source ID can replace the bundled tone. If alarm media is explicitly cleared, the integration falls back to a short spoken `Alarm` announcement.

The integration saves each participating media player's current volume before ringing and restores it after stop, snooze, or timeout. In all-speakers mode, each speaker is restored to its own previous volume. v0.3 does not attempt to restore the previous media session/source.

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

## Voice control

The deterministic Home Assistant conversation sentence triggers added in v0.4 remain the primary voice-control path in v0.7. They are handled locally before the configured conversation agent, so the core alarm phrases do not require an LLM even when a ChatGPT, Gemini, or other conversation agent is selected.

Supported English examples include:

```text
Set an alarm for 6 AM.
Set an alarm for 6:30 tomorrow.
Wake me at 6:30.
Set a daily alarm for 8 AM.
Wake me at 6:30 on weekdays.
Set a weekend alarm for 8 AM.
Set a work alarm for 6:30 on Monday Wednesday and Friday.
What alarms do I have?
What time is my work alarm?
Cancel my work alarm.
Cancel my 6:30 alarm.
What time is my next alarm?
Cancel my next alarm.
Stop the alarm.
Snooze.
Snooze for 15 minutes.
Skip my next alarm.
Skip tomorrow's alarm.
Tomorrow wake me at 7 instead.
```

The originating `assist_satellite` is matched directly to the configured Satellite Alarms endpoint. If Home Assistant supplies only the originating device ID, the integration uses the configured satellite entity's device as a fallback. If neither path uniquely identifies an endpoint, the integration refuses to guess a room.

Common spoken clock forms such as `6 AM`, `6:30 PM`, `six thirty`, `six oh five`, `noon`, and `midnight` are parsed deterministically. One-time alarms without an explicit day use the next future occurrence; `today` and `tomorrow` are also supported.

Bare `Stop` is intentionally not registered yet because a global sentence trigger would also intercept unrelated media stop commands when no alarm is ringing. Use `Stop the alarm` or `Dismiss the alarm` in v0.4.

v0.7 adds multi-satellite room endpoints, native room status entities, reconfiguration, richer diagnostics, and repair warnings. Later versions may add morning briefings, richer dashboard controls, and optional integrations such as Music Assistant.

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

- Recurrence choices to one-time, daily, weekdays, weekends, and explicit selected weekdays.
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
| v0.7 | Multi-satellite room endpoints, dashboard entities, diagnostics/repairs, and polish |
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

On the v0.7 development branch, rooms can contain multiple satellite/speaker pairs and expose native next-alarm, alarm-count, ringing, and active-alarm entities.

## Contributing

The project is in its design phase. Issues and pull requests should focus on concrete alarm behavior, Home Assistant compatibility, satellite/media-player behavior, and reliability.

Please avoid designing features around one specific hardware platform when the same behavior can be expressed through standard Home Assistant entities.

## License

A license has not yet been selected.
