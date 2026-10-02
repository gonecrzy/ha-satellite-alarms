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
11. Use Scheduler Component as the scheduling/persistence base instead of rebuilding a scheduler.

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
- Reimplement Scheduler Component's mature schedule persistence, recurrence, enable/disable, and next-trigger engine.
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
                  +--------------+---------------+
                  |                              |
                  v                              v
        +-------------------+          +-------------------+
        | Alarm Registry    |          | Alarm Manager     |
        | metadata/mapping  |          | lifecycle/state   |
        +---------+---------+          +---------+---------+
                  |                              |
                  +--------------+---------------+
                                 |
                                 v
                      +-----------------------+
                      | Scheduler Adapter     |
                      +-----------+-----------+
                                  |
                                  v
                      +-----------------------+
                      | Scheduler Component   |
                      | schedules/persistence |
                      | recurrence/next time  |
                      +-----------+-----------+
                                  |
                            scheduled action
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

Scheduler Component is a required runtime dependency for the initial architecture. Satellite Alarms should interact with it through a dedicated adapter rather than spreading Scheduler-specific calls through the codebase. This keeps room routing, voice logic, playback, and alarm state independent from the scheduling backend.

---

## 6. Proposed repository layout

```text
custom_components/
└── assist_satellite_alarms/
    ├── __init__.py
    ├── manifest.json
    ├── config_flow.py
    ├── const.py
    ├── coordinator.py
    ├── models.py
    ├── registry.py
    ├── scheduler_adapter.py
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

## 10. Scheduler Component base

Scheduler Component is the scheduling engine for the initial implementation.

It already provides:

- persistent schedule storage
- scheduler `switch` entities
- `next_trigger`
- enable/disable behavior
- one-time schedules using `repeat_type: single`
- repeating schedules
- weekday/workday/weekend selection
- start/end dates
- `scheduler.add`, `scheduler.edit`, and `scheduler.remove` actions

Satellite Alarms should therefore store only alarm-specific metadata that Scheduler Component does not own, such as the alarm UUID, endpoint association, display name, playback settings, and the corresponding Scheduler entity ID.

### Scheduler adapter

All Scheduler-specific interaction belongs behind `scheduler_adapter.py`.

The adapter will be responsible for:

- validating that Scheduler Component is installed and configured
- creating a Scheduler schedule for an alarm
- finding and recording the created Scheduler entity
- editing/removing the Scheduler schedule
- enabling/disabling schedules
- reading `next_trigger`
- translating Satellite Alarms recurrence values to Scheduler Component's format
- insulating the rest of the integration from Scheduler Component implementation details

### Scheduler callback action

v0.2 uses a stable alarm UUID and a Scheduler tag of `assist_satellite_alarms:<alarm_id>`. Scheduler schedules use an immutable internal name so the Scheduler switch entity can be predicted without using the user-facing alarm name.

A weekday schedule is represented as:

```yaml
weekdays:
  - workday
timeslots:
  - start: "06:30:00"
    actions:
      - service: assist_satellite_alarms.fire
        service_data:
          alarm_id: <stable-alarm-uuid>
repeat_type: repeat
tags:
  - assist_satellite_alarms
  - assist_satellite_alarms:<stable-alarm-uuid>
```

The `fire` action resolves the owning Satellite Alarms endpoint and starts the Playback Manager for the target Assist satellite and media player.

### One-time alarms

A one-time alarm will use:

- the target date as `start_date` and `end_date`
- the requested time as the timeslot `start`
- `repeat_type: single`

This lets Scheduler Component remove the schedule after it fires.

### Recurring alarms

Initial mappings:

```text
daily     -> daily
weekdays  -> workday
weekends  -> weekend
```

Selected weekday lists are planned for a later version.

### Restart behavior

Scheduler Component owns schedule persistence and reconstruction after Home Assistant restarts. Satellite Alarms reloads its metadata registry, reconciles stored alarm records with Scheduler entities, and marks missing/orphaned mappings for repair rather than silently recreating duplicates.

### Missed alarms

Scheduler Component already contains restart/shutdown handling. Satellite Alarms should not add a second independent missed-alarm scheduler. Any alarm-specific grace/fallback behavior will be implemented only after Scheduler behavior is tested with the supported version.

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

v0.5 policy: the first active alarm keeps ownership of the endpoint. Additional due alarms for the same endpoint are queued in trigger order and begin after the active alarm finishes. Different endpoints remain independent. Queued alarms are discarded on endpoint unload or Home Assistant shutdown.

---

## 15. Voice command layer

Core voice operations should be deterministic and not depend on an LLM.

The voice layer needs to resolve:

- requested time
- recurrence
- alarm identity when relevant
- originating Assist satellite
- associated alarm endpoint

### v0.4 commands

```text
Set an alarm for 6 AM.
Wake me at 6:30.
Set a daily alarm for 8 AM.
Wake me at 6:30 on weekdays.

What time is my next alarm?
Cancel my next alarm.

Stop the alarm.
Snooze.
Snooze for 15 minutes.
```

### Originating satellite

Home Assistant's conversation input exposes the originating `satellite_id` and `device_id`. v0.4 matches `satellite_id` directly to the configured endpoint and uses the configured satellite entity's device ID only as a fallback.

Fallback behavior when the originating satellite cannot be resolved remains conservative:

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
assist_satellite_alarms.create
assist_satellite_alarms.update
assist_satellite_alarms.delete
assist_satellite_alarms.enable
assist_satellite_alarms.disable
assist_satellite_alarms.stop
assist_satellite_alarms.snooze
assist_satellite_alarms.skip_next
assist_satellite_alarms.test
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

Persistence is split between two owners.

### Scheduler Component

Scheduler Component is the source of truth for:

- execution time
- recurrence
- enabled/disabled schedule state
- Scheduler switch entity
- next trigger
- actual persistent schedule definition

### Satellite Alarms registry

Satellite Alarms persists only its own management metadata:

- stable alarm UUID
- endpoint/config-entry association
- cached Scheduler entity ID
- alarm name
- normalized requested time/recurrence/date needed to edit the Scheduler schedule
- playback overrides
- snooze/ringing metadata that is not represented by Scheduler Component

Scheduler Component remains the execution source of truth. Satellite Alarms does not duplicate Scheduler timeslots, conditions, enabled state, internal schedule ID, or next-trigger calculation.

Requirements before v1.0:

- registry storage schema version
- migration support
- stable alarm IDs
- reconciliation with Scheduler entities after restart
- safe handling of removed endpoints
- detection of orphaned Scheduler schedules
- no duplicate schedules after restart
- no silent loss of endpoint/alarm metadata

The integration must not copy Scheduler Component's full schedule data into a second competing source of truth.

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

- Scheduler Component must already be installed and configured.
- No alarm ringing yet.
- No voice commands.
- Endpoint configuration and alarm metadata registry only.
- Scheduler adapter validates the dependency but does not yet create user alarms.
- One media player per endpoint.

### v0.2 restrictions

- One-time, daily, weekdays, weekends only.
- Services/API first.
- Schedules are created/edited/removed through Scheduler Component.
- No voice commands.
- No advanced recurrence.
- Basic next-trigger reporting comes from the Scheduler entity.

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

- Named/multiple alarm support is deterministic; arbitrary natural-language scheduling remains out of scope.
- Selected weekdays are explicit weekday names rather than free-form recurrence rules.
- Name matching is exact and case-insensitive.
- Time-based cancel/query refuses to choose when more than one room-local alarm shares that time.

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
- Required Scheduler Component dependency.
- Config flow for satellite/media-player endpoints.
- Endpoint configuration and defaults.
- Versioned alarm metadata registry.
- Scheduler adapter with dependency/readiness validation.
- Basic diagnostics/logging.

Success criteria:

- Multiple satellite endpoints can be configured.
- Duplicate satellite endpoints are rejected.
- Scheduler Component absence/not-ready state is reported clearly.
- Configuration survives restart.
- Alarm metadata can be stored/reloaded without creating schedules.

### v0.2 — Scheduler-backed alarms

Deliverables:

- Scheduler adapter create/edit/remove/enable/disable operations.
- Satellite Alarms create/update/delete/enable/disable actions.
- One-time alarms.
- Daily alarms.
- Weekday/weekend alarms.
- Scheduler entity mapping.
- Next-trigger reporting from Scheduler Component.
- Registry/Scheduler reconciliation after restart.

Success criteria:

- Service-created alarms create Scheduler Component schedules.
- The Scheduler schedule calls back into the correct Satellite Alarm ID.
- Recurring alarms use Scheduler Component recurrence correctly.
- Restart does not duplicate schedules or alarm metadata.

#### v0.2 implementation status

Implemented in the v0.2 development branch:

- create/update/delete/enable/disable service actions
- one-time, daily, weekday, and weekend translation
- stable UUID and Scheduler tag mapping
- service responses with alarm/Scheduler IDs
- `assist_satellite_alarms.fire` callback and room-targeted event data
- registry rollback on Scheduler create failure
- restart reconciliation of cached Scheduler entity IDs by stable tag

Playback remains intentionally deferred to v0.3.

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

#### v0.3 implementation status

Implemented in the v0.3 development branch:

- one active ringing alarm per endpoint
- simultaneous independent ringing across different endpoints
- save/set/restore media-player volume
- optional bounded gradual volume ramp
- repeated `assist_satellite.announce` playback
- optional endpoint alarm media
- spoken fallback alarm message when no media is configured
- maximum ring duration
- `assist_satellite_alarms.stop`
- `assist_satellite_alarms.snooze`
- transient one-time Scheduler snooze occurrences tied to the parent alarm
- one-time alarm metadata cleanup after stop/timeout
- best-effort media stop and volume restore during unload/shutdown

Snooze preserves the parent alarm definition. Repeated snoozes do not create additional normal alarm records.

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

#### v0.4 implementation status

Implemented in the v0.4 development branch:

- deterministic English Home Assistant sentence triggers
- originating-`assist_satellite` endpoint routing
- originating-device fallback when `satellite_id` is unavailable
- one-time alarm creation using next-occurrence semantics
- explicit `today` and `tomorrow` alarm creation
- daily, weekday, and weekend alarm creation
- deterministic spoken-time parsing
- room-local next-alarm query using Scheduler Component's `next_trigger`
- room-local cancellation of the next scheduled alarm
- room-local stop with `Stop the alarm` / `Dismiss the alarm`
- room-local default and explicit-duration snooze
- spoken confirmations and conservative routing errors
- local sentence triggers that run before an external conversation agent

Bare `Stop` remains deferred because a permanently registered global sentence trigger would intercept unrelated media stop commands even when no Satellite Alarm is ringing. Named alarm management and selected weekdays remain v0.5 work.

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

#### v0.5 implementation status

Implemented in the v0.5 development branch:

- multiple alarms per endpoint
- stable alarm names alongside UUID identity
- `assist_satellite_alarms.list` action with endpoint filtering
- exact case-insensitive alarm lookup by name
- alarm lookup by normalized clock time with ambiguity protection
- selected weekday recurrence using Scheduler's `mon` through `sun` values
- service create/update support for explicit `days`
- voice creation such as `Set a work alarm for 6:30 on Monday Wednesday and Friday`
- room-local `What alarms do I have?`
- room-local query by name
- room-local cancel by name or time
- deterministic same-room queueing when multiple alarms become due while one is already ringing

Scheduler Component continues to own actual recurrence execution and next-trigger calculation.

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

Scheduler Component is an intentional runtime dependency and provides the schedule engine. Ideas from alarm-specific projects should be implemented in Satellite Alarms' own alarm/voice/playback layers rather than depending on those projects' internal data models.

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

1. Whether named alarm creation should eventually enforce unique names per endpoint or continue allowing duplicates with explicit disambiguation.
2. Whether to restore prior media playback in addition to volume.
3. Whether any alarm-specific missed-alarm grace behavior is needed beyond Scheduler Component's restart handling.
4. How alarm entities should be represented without creating entity clutter.
5. Whether pre/post actions should be scripts, generic actions, or events.
6. Whether a future configurable playback strategy should supplement the current `assist_satellite.announce` path.
7. How much date parsing should remain deterministic before optionally delegating language interpretation to an LLM.
8. Whether bare `Stop` can be implemented without stealing unrelated stop commands when no alarm is active.

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
"Stop the alarm."

Living room's alarm configuration remains untouched.
```

If that behavior is reliable across Home Assistant restarts and normal satellite reconnects, the integration has achieved its core purpose.
