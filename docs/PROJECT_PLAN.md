# Satellite Alarms — Project Plan

This document defines the proposed architecture, scope, restrictions, and staged implementation plan for **Home Assistant Satellite Alarms**.

It is a design document, not a guarantee of final behavior. Decisions may change as Home Assistant APIs and real satellite/media-player behavior are tested.

---

## 1. Problem statement

Home Assistant Assist supports countdown timers, but a multi-room voice installation also needs absolute and recurring wake-up alarms:

- "Set an alarm for 6 AM."
- "Wake me at 6:30 on weekdays."
- "Set a daily alarm for 8 AM."
- "Snooze."
- "Stop."

The desired behavior is room-local:

```text
Bedroom satellite hears request
           |
           v
Alarm is created for Bedroom
           |
           v
Bedroom speaker rings at the scheduled time
```

The system should not require the user to say "bedroom" when the room can be inferred from the voice satellite that heard the request.

---

## 2. Project goals

### Core goals

1. Provide absolute clock-time alarms for Home Assistant Assist satellites.
2. Associate alarms with the originating satellite/room.
3. Persist alarms across Home Assistant restarts.
4. Support one-time and recurring schedules.
5. Ring through a configured `media_player`.
6. Support room-local stop and snooze.
7. Preserve and restore speaker volume.
8. Provide a service API independent of voice.
9. Keep the implementation generic to Home Assistant entities.
10. Avoid requiring an LLM for deterministic alarm operations.

### Secondary goals

- Multiple alarms per room.
- Named alarms.
- Selected-day recurrence.
- Gradual volume ramp.
- Alarm sound selection.
- Skip next occurrence.
- Temporary one-day overrides.
- Pre-alarm and post-alarm actions.
- Dashboard-visible alarm state.
- Optional fallback actions when a satellite is unavailable.
- LLM tool exposure after the deterministic API is stable.

---

## 3. Non-goals

The integration should not initially attempt to:

- Replace Home Assistant's native countdown timers.
- Implement general reminders, calendars, or task management.
- Become a generic scheduler for all Home Assistant entities.
- Require EchoMuse.
- Require Scheduler Component.
- Require an LLM.
- Guarantee operation while Home Assistant itself is offline.
- Provide synchronized whole-house audio playback.
- Reproduce every Alexa alarm feature in the first release.

A reminder subsystem may be added later, but it should remain conceptually separate from wake-up alarms.

---

## 4. Supported device model

The integration should operate on standard Home Assistant concepts.

Each configured **alarm endpoint** maps:

```text
Assist satellite
      +
Media player
      +
Area/room metadata
      =
Satellite Alarm Endpoint
```

Example:

```text
Bedroom
├── assist_satellite.bedroom_voice_assistant
└── media_player.bedroom_voice_assistant
```

EchoMuse-converted Echo Dots are a primary development/test platform, but no core code should depend on EchoMuse entity names, APIs, or firmware.

---

## 5. Proposed system architecture

```text
                      +----------------------+
Voice command ------>| Home Assistant Assist|
                      +----------+-----------+
                                 |
                                 | originating satellite/context
                                 v
                      +----------------------+
Dashboard/service -->| Satellite Alarms     |<-- Automation / LLM tool
                      | service API          |
                      +----------+-----------+
                                 |
                 +---------------+----------------+
                 |                                |
                 v                                v
        +------------------+            +------------------+
        | Alarm Store      |            | Alarm Manager    |
        | persistent data  |            | lifecycle/state  |
        +--------+---------+            +---------+--------+
                 |                                |
                 +---------------+----------------+
                                 |
                                 v
                       +------------------+
                       | Scheduler        |
                       | HA time helpers  |
                       +--------+---------+
                                |
                                v
                       +------------------+
                       | Playback Manager |
                       +--------+---------+
                                |
                 +--------------+--------------+
                 |                             |
                 v                             v
          media_player                   assist_satellite
          alarm audio                    confirmations
```

### Design rule

The voice layer should call the same alarm-management API used by services and dashboards. Voice behavior must not contain a separate scheduling implementation.

---

## 6. Proposed repository layout

```text
custom_components/
└── satellite_alarms/
    ├── __init__.py
    ├── manifest.json
    ├── config_flow.py
    ├── const.py
    ├── coordinator.py
    ├── models.py
    ├── storage.py
    ├── scheduler.py
    ├── alarm_manager.py
    ├── playback.py
    ├── intent.py
    ├── services.yaml
    ├── strings.json
    └── translations/
        └── en.json

docs/
├── PROJECT_PLAN.md
└── future documentation
```

This is provisional. Files should be split only when responsibilities justify it.

---

## 7. Alarm endpoint model

A configured endpoint represents one room/satellite pairing.

Proposed fields:

```text
endpoint_id
name
area_id
assist_satellite_entity_id
media_player_entity_id
default_alarm_sound
default_alarm_volume
default_snooze_minutes
volume_ramp_enabled
volume_ramp_start
volume_ramp_duration
maximum_ring_duration
```

The config flow should validate that selected entities exist and expose required capabilities where practical.

### Early restriction

For v0.x, one endpoint maps to exactly:

- one Assist satellite
- one media player

Multi-speaker alarm endpoints can be considered later.

---

## 8. Alarm data model

Each alarm should have a stable ID independent of its display name.

Proposed fields:

```text
alarm_id
endpoint_id
name
enabled
time
timezone
recurrence
days_of_week
created_at
next_trigger
sound
volume
snooze_minutes
maximum_ring_duration
skip_next
metadata
```

### Recurrence model

Initial recurrence types:

```text
once
daily
weekdays
weekends
```

Later:

```text
selected_days
specific_date
custom recurrence rules
```

### One-time alarm interpretation

If a user says:

```text
Set an alarm for 6 AM.
```

the default interpretation should be the **next future occurrence of 6:00 AM in Home Assistant's configured local timezone**.

If it is 5:00 AM, the alarm is today.

If it is 8:00 AM, the alarm is tomorrow.

Explicit dates override this rule once date-aware commands are implemented.

---

## 9. Alarm lifecycle

Proposed states:

```text
scheduled
ringing
snoozed
disabled
completed
cancelled
```

Simplified lifecycle:

```text
                  +-----------+
                  | scheduled |
                  +-----+-----+
                        |
                     trigger
                        |
                        v
                  +-----------+
             +--->|  ringing  |---+
             |    +-----+-----+   |
             |          |         |
          snooze       stop    max duration
             |          |         |
             v          v         v
        +---------+  completed  completed
        | snoozed |
        +----+----+
             |
         snooze ends
             |
             +-------------------> ringing
```

For recurring alarms, `completed` means the current occurrence completed and the next occurrence is scheduled.

---

## 10. Scheduling engine

The integration should use Home Assistant's native event/time scheduling helpers rather than requiring another custom scheduler.

Responsibilities:

- Calculate next trigger.
- Register/cancel callbacks.
- Re-register alarms after Home Assistant restart.
- Recalculate recurring alarms after an occurrence.
- Handle timezone and daylight-saving changes using Home Assistant's configured timezone.
- Keep persistent alarm data separate from in-memory callback handles.

### Restart behavior

On startup:

1. Load stored alarms.
2. Validate endpoint references.
3. Recalculate `next_trigger`.
4. Register future alarms.
5. Restore state without duplicating already-completed one-time alarms.

### Missed alarms

Early versions should **not silently fire every missed alarm after a long Home Assistant outage**.

Proposed later option:

```text
missed_alarm_grace_period
```

Example: if HA restarts within 2 minutes of the intended trigger, the alarm may still ring. Otherwise it is marked missed and the next recurring occurrence is calculated.

This behavior must be explicit and configurable before v1.0.

---

## 11. Playback behavior

A ringing alarm should be owned by the endpoint where it was created.

Proposed sequence:

```text
Capture current speaker state
        |
        v
Capture current volume
        |
        v
Set/ramp alarm volume
        |
        v
Play or repeat alarm sound
        |
        +--> Stop
        |
        +--> Snooze
        |
        +--> Maximum duration reached
        |
        v
Stop alarm playback
        |
        v
Restore prior volume
```

### Volume handling

Minimum requirement:

- save current `volume_level`
- set alarm volume
- restore previous volume when the alarm ends

Optional ramp:

```text
20% -> 30% -> 40% -> 50% -> 60% -> 70%
```

The exact ramp implementation must avoid excessive service calls.

### Early restoration restriction

v0.x should guarantee **volume restoration**, but not necessarily restoration of every previous media playback state.

Restoring paused music, playback position, source selection, or complex media sessions may differ by media-player integration and should be treated as a later feature.

---

## 12. Alarm sound handling

Initial support should allow:

- Integration default sound.
- Endpoint-specific default sound.
- Per-alarm override where supported.
- Home Assistant-accessible media URL or media-source reference.

Potential later support:

- TTS wake message.
- Music Assistant source.
- Radio station.
- Playlist.
- Random sound from a configured set.

### Reliability rule

The default alarm mode should use a predictable local or HA-served sound rather than relying on an external internet stream.

---

## 13. Snooze behavior

Initial snooze behavior:

```text
Snooze.
Snooze for 10 minutes.
```

Snooze applies to the alarm currently ringing on the originating endpoint.

Proposed endpoint default:

```text
default_snooze_minutes: 10
```

Later options:

- maximum snooze count
- per-alarm snooze duration
- disable snooze
- escalating volume after repeated snoozes

---

## 14. Stop behavior

"Stop" is intentionally context-sensitive.

If spoken to Bedroom:

```text
Bedroom satellite -> stop Bedroom's active ringing alarm
```

It should not stop another room's alarm unless the user explicitly identifies that room in a future cross-room command.

### Early restriction

Only one alarm may be in the `ringing` state per endpoint at a time.

If two alarms on the same endpoint become due simultaneously, the Alarm Manager must resolve them deterministically rather than starting overlapping playback sessions.

Possible initial rule:

1. Earliest scheduled alarm wins.
2. Other due alarms are coalesced or queued.
3. Behavior is logged.

Exact policy should be finalized before v0.3.

---

## 15. Voice command layer

Core voice operations should be deterministic and not depend on an LLM.

The voice layer needs to resolve:

- requested time
- recurrence
- alarm identity when relevant
- originating Assist satellite
- associated alarm endpoint

### Proposed v0.4 commands

```text
Set an alarm for 6 AM.
Wake me at 6:30.
Set a daily alarm for 8 AM.
Wake me at 6:30 on weekdays.

What time is my next alarm?
Cancel my alarm.
Disable my alarm.
Enable my alarm.

Stop.
Snooze.
Snooze for 15 minutes.
```

### Originating satellite

When Home Assistant exposes originating satellite context to the intent/sentence path, that context should be the default endpoint selector.

Fallback behavior when the originating satellite cannot be resolved must be conservative:

- do not guess a room
- ask for a room or return a clear error

### Explicit room commands

Later versions may support:

```text
Set the bedroom alarm for 6 AM.
Cancel Riley's room alarm.
What time is the guest room alarm?
```

---

## 16. Service API

The integration should expose services before advanced voice functionality so behavior can be tested independently.

Proposed services:

```text
satellite_alarms.create
satellite_alarms.update
satellite_alarms.delete
satellite_alarms.enable
satellite_alarms.disable
satellite_alarms.stop
satellite_alarms.snooze
satellite_alarms.skip_next
satellite_alarms.test
```

Possible create payload:

```yaml
endpoint_id: bedroom
time: "06:30:00"
recurrence: weekdays
name: work
volume: 0.7
```

Service schemas must be validated and documented.

---

## 17. Home Assistant entities

The integration should avoid creating an excessive number of helper entities.

Possible endpoint-level entities:

```text
sensor.bedroom_next_alarm
sensor.bedroom_alarm_count
binary_sensor.bedroom_alarm_ringing
button.bedroom_alarm_stop
button.bedroom_alarm_snooze
```

Possible alarm entities may be considered later if the Home Assistant entity model provides a clean representation.

### Early design preference

Store alarms in the integration's persistent model rather than requiring users to manually create:

- `input_datetime`
- `input_boolean`
- `input_number`

The integration may expose entities for UI visibility without making helpers the source of truth.

---

## 18. Configuration flow

Proposed setup flow:

1. Add Satellite Alarms integration.
2. Select Assist satellite.
3. Select matching media player.
4. Confirm or select Home Assistant Area.
5. Configure alarm defaults.
6. Save endpoint.
7. Repeat for additional rooms.

Endpoint options:

- default alarm sound
- default volume
- ramp enabled
- ramp start volume
- ramp duration
- snooze duration
- maximum ring duration

Configuration should be editable without deleting stored alarms.

---

## 19. Persistence and migrations

Alarm data should use Home Assistant-supported persistent storage mechanisms.

Requirements before v1.0:

- storage schema version
- migration support
- stable alarm IDs
- safe handling of removed endpoints
- no duplicate alarms after restart
- no silent loss of recurrence information

A stored alarm should not depend on entity display names.

---

## 20. Concurrency and conflict handling

The integration must account for:

- two rooms ringing simultaneously
- snooze while another alarm is ringing elsewhere
- editing an alarm immediately before it triggers
- deleting an alarm while callback execution begins
- Home Assistant shutdown during ringing
- media-player unavailability
- entity rename or removal
- two alarms due on the same endpoint at the same time

The manager should use alarm IDs and endpoint IDs rather than global "current alarm" variables.

Each endpoint should maintain independent runtime state.

---

## 21. Reliability restrictions

The project should clearly communicate these limitations.

### Home Assistant availability

Satellite Alarms cannot ring if Home Assistant is powered off, crashed, or unable to execute automations/services at the scheduled time.

This is not a replacement for a dedicated hardware alarm clock where missing an alarm would create a safety-critical situation.

### Satellite availability

If the configured speaker is offline, early versions may fail the alarm and log the failure.

Later versions may provide fallback targets such as:

- another media player
- mobile notification
- alternate satellite

### Network dependence

Even with local audio, a network outage between Home Assistant and the satellite can prevent playback.

### Volume behavior

The integration can request volume changes but cannot guarantee identical volume semantics across every media-player integration.

### Audio looping

Repeat/loop behavior may differ by media player. The playback manager should prefer explicit repeat logic it controls rather than assuming a device supports native looping.

---

## 22. Proposed feature restrictions by stage

### v0.1 restrictions

- No alarm ringing yet.
- No voice commands.
- Configuration and persistence only.
- One media player per endpoint.

### v0.2 restrictions

- One-time, daily, weekdays, weekends only.
- Services/API first.
- No voice commands.
- No advanced recurrence.
- Basic next-trigger reporting.

### v0.3 restrictions

- One active ringing alarm per endpoint.
- Volume restoration only; full prior media-session restoration not guaranteed.
- Default/local alarm audio preferred.
- Basic snooze and stop.
- No cross-room stop.

### v0.4 restrictions

- Voice grammar intentionally limited.
- No LLM requirement.
- If satellite context is missing, do not guess endpoint.
- Date parsing may remain limited to time + supported recurrence phrases.

### v0.5 restrictions

- Named/multiple alarm support expands, but arbitrary natural-language scheduling may still be out of scope.
- Selected weekdays supported explicitly rather than free-form recurrence rules.

### v1.0 target

- Stable storage and migration path.
- Stable service contracts.
- Documented supported HA version range.
- Tested restart behavior.
- Tested multi-room concurrency.
- Tested one-time and recurring alarms.
- Documented satellite/media-player compatibility expectations.

---

## 23. Version plan

### v0.1 — Foundation

Deliverables:

- HACS-compatible custom integration skeleton.
- Manifest and translations.
- Config flow.
- Endpoint configuration.
- Persistent storage abstraction.
- Alarm data model.
- Basic diagnostics/logging.

Success criteria:

- Multiple satellite endpoints can be configured.
- Configuration survives restart.
- Alarm objects can be stored/reloaded without scheduling.

### v0.2 — Scheduler

Deliverables:

- Native HA scheduling engine.
- Create/update/delete/enable/disable services.
- One-time alarms.
- Daily alarms.
- Weekday/weekend alarms.
- Next-trigger calculation.
- Restart rescheduling.

Success criteria:

- Service-created alarms trigger internal callbacks at correct local times.
- Recurring alarms compute the next occurrence correctly.
- Restart does not duplicate schedules.

### v0.3 — Ringing, stop, and snooze

Deliverables:

- Playback manager.
- Sound configuration.
- Save/set/restore volume.
- Optional initial volume ramp.
- Ringing state.
- Stop service.
- Snooze service.
- Maximum ring duration.
- Multi-room independent runtime state.

Success criteria:

- Two different endpoints can ring independently.
- Stop/snooze affects only the specified endpoint/alarm.
- Previous volume is restored reliably.

### v0.4 — Home Assistant Assist voice support

Deliverables:

- Deterministic intents/sentences.
- Originating-satellite endpoint resolution.
- Set one-time alarm.
- Set daily/weekday alarm.
- Query next alarm.
- Cancel/disable.
- Room-local stop/snooze.
- Spoken confirmations.

Success criteria:

```text
"Set an alarm for 6 AM"
```

spoken in Bedroom creates a Bedroom alarm without saying "Bedroom."

### v0.5 — Multiple and named alarms

Deliverables:

- Multiple alarms per endpoint.
- Named alarms.
- Query/list alarms.
- Cancel by time/name.
- Selected weekdays.
- More robust simultaneous-due handling.

Example:

```text
Set an alarm called work for 6:30 on Monday, Wednesday, and Friday.
```

### v0.6 — Advanced wake behavior

Deliverables:

- Skip next occurrence.
- Temporary next-occurrence override.
- Improved volume ramp.
- Optional pre-alarm actions.
- Optional post-dismiss actions.
- Per-alarm sound/volume.
- Failure/fallback hooks.

Examples:

```text
Skip tomorrow's alarm.
Tomorrow wake me at 7 instead.
```

### v0.7 — UI and ecosystem

Possible deliverables:

- Richer endpoint/alarm entities.
- Dashboard controls.
- Diagnostics.
- Repair issues for invalid/offline endpoints.
- Optional LLM tool exposure.
- Optional blueprint/examples for lights, blinds, weather, and morning routines.

### v1.0 — Stable release

Requirements:

- Stable storage schema.
- Migrations tested.
- Service API documented.
- Voice grammar documented.
- Core multi-room behavior tested.
- Restart/reload behavior tested.
- HACS installation documented.
- Compatibility matrix documented.
- Known limitations documented.

---

## 24. Features intentionally deferred

These are useful, but should not delay the core alarm engine:

- Music Assistant alarms.
- Internet radio alarms.
- Calendar-aware alarms.
- Holiday exceptions.
- "Wake me 30 minutes before sunrise."
- Presence-based alarms.
- Person-specific voice recognition.
- Automatic alarm migration between rooms.
- Whole-house synchronized alarms.
- Natural-language LLM-only alarm creation.
- General reminder/task system.

They can be evaluated after the deterministic alarm path is stable.

---

## 25. Ideas borrowed from existing alarm projects

Other Home Assistant alarm projects demonstrate useful patterns worth adopting conceptually:

- recurring weekday schedules
- named alarms
- multiple alarms
- snooze and stop
- configurable alarm volume
- custom alarm sounds
- pre-alarm and post-alarm actions
- skip/override concepts
- dashboard visibility
- persistent schedules

Satellite Alarms should implement these against its own architecture rather than depending on another alarm integration's internal data model.

The differentiating feature is **satellite-aware room ownership** as a first-class concept.

---

## 26. Initial test matrix

At minimum, development should test:

### Scheduling

- alarm later today
- alarm next day
- midnight boundary
- daily recurrence
- weekday Friday -> Monday transition
- weekend recurrence
- DST transition where applicable
- restart before trigger
- restart after occurrence

### Room routing

- Bedroom command -> Bedroom
- Room A and Room B both have alarms
- simultaneous alarms in different rooms
- stop in Room A does not affect Room B
- snooze in Room A does not affect Room B

### Playback

- volume at 0 before alarm
- volume at 100% before alarm
- speaker unavailable
- HA restart while alarm is ringing
- stop during volume ramp
- snooze during volume ramp
- maximum ring timeout
- volume restoration after stop
- volume restoration after snooze

### Persistence

- create -> restart -> still scheduled
- edit -> restart -> edited value retained
- delete -> restart -> does not return
- disabled alarm remains disabled

---

## 27. Open design questions

These should be resolved through implementation/testing rather than guessed up front:

1. Best Home Assistant API path for receiving originating Assist satellite context inside a custom integration.
2. Best generic method for repeating alarm audio across different media-player platforms.
3. Whether to restore prior media playback in addition to volume.
4. Exact missed-alarm grace behavior after HA restart.
5. How alarm entities should be represented without creating entity clutter.
6. Whether pre/post actions should be scripts, generic actions, or events.
7. Whether alarm audio should use `media_player.play_media`, `assist_satellite.announce`, or a configurable playback strategy.
8. How much date parsing should remain deterministic before optionally delegating language interpretation to an LLM.

---

## 28. Definition of a successful first public release

A user with three Home Assistant voice satellites should be able to configure each satellite with a media player and then reliably do this:

```text
Bedroom:
"Set an alarm for 6 AM."

Living room:
"Set a daily alarm for 8 AM."

Bedroom at 6 AM:
Alarm rings only in Bedroom.

Bedroom:
"Snooze for 10 minutes."

Ten minutes later:
Bedroom rings again.

Bedroom:
"Stop."

Living room's alarm configuration remains untouched.
```

If that behavior is reliable across Home Assistant restarts and normal satellite reconnects, the integration has achieved its core purpose.
