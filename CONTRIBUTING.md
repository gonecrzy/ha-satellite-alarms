# Contributing

## Pull request checks

Every pull request should pass the same checks used by CI:

```bash
python -m pip install -r requirements_test.txt
python -m pip install ruff==0.16.8

ruff check .
ruff format --check .
python -m compileall -q custom_components tests
pytest
```

The current coverage floor is intentionally modest while the project is in its foundation stage. It should move upward as the integration gains behavior and tests.

## Testing policy

Functional changes should include tests for the behavior they add or modify.

At minimum, future alarm work should test:

- Scheduler Component adapter payloads and schedule mapping.
- One-time and recurring schedule behavior.
- Endpoint/satellite routing.
- Playback and volume restoration.
- Stop and snooze isolation between rooms.
- Config flow and options changes.
- Persistence and restart reconciliation.
- Voice intent parsing and originating-satellite routing.

Avoid lowering the coverage threshold to make a feature PR pass. Add or improve tests instead.

## CI checks

PRs currently run:

- Hassfest
- HACS validation
- Ruff lint and format validation
- Python compilation
- pytest with Home Assistant's custom-component test harness
- coverage floor

The HACS job temporarily ignores repository-publication metadata checks for brand assets, license, description, and topics while the project is pre-release. Those ignores must be removed before requesting inclusion in the default HACS repository.

## Recommended branch protection

After the CI workflow is merged, configure the `main` branch/ruleset to require these checks before merging:

- `Hassfest`
- `HACS`
- `Ruff and syntax`
- `Pytest`

Also require the branch to be up to date before merge if that fits the repository workflow.
