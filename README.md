# replaykit

replaykit records a browser workflow with an LLM, compiles the resulting trace
into YAML, and replays that YAML with Playwright. Replaying an existing flow
does not call an LLM or require an API key.

The project uses [ParaBank](https://parabank.parasoft.com/) as its test
application. The included flow logs in and extracts the first account balance.

## How it works

1. The recorder gives an LLM an accessibility snapshot and a small set of
   browser actions.
2. The compiler turns the recorded trace into a YAML flow containing page
   states, actions, locator fallbacks, and output extractors.
3. The replay engine runs the YAML deterministically. It checks page states,
   requires locator candidates to identify exactly one element, and returns a
   structured handoff record when it cannot proceed.

Only the recorder accepts an LLM client. The replay packages do not import an
LLM SDK; tests/test_zero_llm.py checks that boundary.

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs and pins Python 3.13 for you)
- Docker, for the live ParaBank tests
- An ANTHROPIC_API_KEY, only when recording a flow or running the LLM-backed
  integration test

## Setup

~~~bash
uv sync
uv run playwright install chromium
docker compose -f docker/docker-compose.yml up -d
~~~

ParaBank becomes available at http://localhost:9099/parabank. Set
PARABANK_URL to use another instance.

To record a new flow, add your key to the ignored .env file:

~~~bash
ANTHROPIC_API_KEY=your-key
~~~

The key must be exported before running a discovery command: `set -a && source .env && set +a`.

## Tests

~~~bash
# Unit and browser-fixture tests; no Docker or API key required
uv run pytest -q -m "not slow"

# Live ParaBank tests; LLM-backed cases skip if no API key is configured
uv run pytest -q -m slow
~~~

The live suite includes a 100-run replay of the hand-written login flow and
end-to-end recording, compilation, and promotion tests for the example flows.

Three of those end-to-end cases currently fail, and the reason is the known
`select` limitation listed under "Current limits" below: `find_transactions`,
`transfer_funds`, and `open_account` all select an account from a dropdown
ParaBank populates per user. Discovery records the account belonging to the
user it discovered with, while the promotion gate replays against other freshly
seeded users whose dropdowns hold different accounts, so `select_option` finds
no matching option and the gate refuses the recording. `accounts_overview`,
which selects nothing, passes. Fixing this needs a positional fallback for
`select` values, which the compiler's locator ladder does not yet derive.

## Demo path

Replay the hand-written login flow without an LLM or API key:

~~~bash
uv run app.py replay replaykit/flows/login.yaml \
    --target http://localhost:9099/parabank/index.htm \
    --input username=john --input password=demo
~~~

Record a new flow with the LLM, then replay what it produced:

~~~bash
uv run app.py record --name my_accounts_overview \
    --goal "Log in and read the first account's balance" \
    --target http://localhost:9099/parabank/index.htm \
    --input username=john --secret username \
    --input password=demo --secret password \
    --output balance:decimal

uv run app.py replay replaykit/flows/my_accounts_overview.yaml \
    --target http://localhost:9099/parabank/index.htm \
    --input username=john --input password=demo
~~~

See `evidence/README.md` for the recorded runs.

Add --serve to record with a local operator dashboard:

~~~bash
uv run app.py record --name transfer_funds --goal "Transfer funds" \
    --target http://localhost:9099/parabank/index.htm \
    --input username=john --secret username \
    --input password=demo --secret password \
    --input amount=1.00 --output confirmed_amount:decimal --serve
~~~

To watch a replay and take over if it gets stuck, use:

~~~bash
uv run app.py serve replaykit/flows/transfer_funds.yaml \
    --target http://localhost:9099/parabank/index.htm \
    --input username=john --input password=demo --input amount=1.00
~~~

Each record or replay command writes logs, recordings, and intervention
evidence to `evidence/<run-id>/`.

## Project layout

| Path | Purpose |
| --- | --- |
| replaykit/recording/ | Flow dataclasses and YAML loading |
| replaykit/replayer/ | Deterministic Playwright replay, extraction, recovery, audit logs, and handoffs |
| replaykit/locators/ | Ranked locator resolution |
| replaykit/states/ | URL and accessibility-snapshot state checks |
| replaykit/recorder/ | LLM-guided browser discovery |
| replaykit/compiler/ | Trace-to-flow compilation |
| replaykit/promotion/ | Repeated replay gate for compiled flows |
| replaykit/harness/ | Deterministic ParaBank users and browser fault injection |
| replaykit/flows/ | Example recordings and flow specifications |
| tests/ | Unit, fixture, and live integration tests |

## Replay design

Replay is deliberately narrower than discovery. The recording loader validates
the YAML before a browser is opened. For each step, the engine waits for the
declared starting state, resolves the first locator candidate that identifies
exactly one element, performs the action, and waits for the declared
destination state.

The engine retries a failed state check once through the recording's recovery
rules. It does not guess a new selector or send the page back to a model. A
second failure produces a HandoffRecord with the expected state, current URL,
accessibility snapshot, screenshot, locator outcomes, timing, and redacted
inputs. This keeps replay failures inspectable and keeps LLM cost and
non-determinism outside the production path.

States use both a URL pattern and a partial Playwright accessibility snapshot.
The URL distinguishes navigation, while the snapshot distinguishes pages that
share a route. Locator ladders avoid relying on one brittle selector: the
compiler derives role-and-name, ID, positional, and nearby-text candidates
when they resolve uniquely against the live element.

## Recording and promotion

Discovery has four stages:

1. Snapshot captures the accessibility tree in Playwright's AI mode, where
   each interactive element has an ephemeral reference.
2. Recorder sends the goal, placeholder inputs, and current snapshot to an
   injected model client. It records each tool action and derives its locator
   ladder before a navigation can invalidate the reference.
3. Compiler normalizes snapshot annotations, identifies distinct states, and
   emits a parameterized YAML flow. Values supplied as inputs become
   placeholders instead of recorded literals.
4. Promotion replays the compiled flow through the unchanged replay engine
   against fresh users. A recording is usable only when every gate replay
   succeeds.

The model never receives resolved input values. The recorder prompt uses
placeholders such as {{inputs.password}}, and resolves them only while filling
or selecting a browser control.

## Flow format

Flows are YAML files that declare inputs, states, actions, and optional typed
outputs. A step can provide multiple locator candidates; replay uses the first
candidate that matches exactly one element.

~~~yaml
flow: example
inputs:
  username: {type: string, secret: true}
states:
  login:
    url: /index\.htm
    aria: '- heading "Customer Login"'
steps:
  - from: login
    action: fill
    target:
      - css: "#username"
    value: "{{inputs.username}}"
~~~

See replaykit/flows/accounts_overview.yaml for a complete compiled example and
replaykit/flows/specs.py for recorder specifications.

## Testing reference

| Marker | Requirements | Coverage |
| --- | --- | --- |
| default | None | Pure unit tests for schemas, parsing, policies, and control flow |
| not slow | None | The full fast suite, including local HTML fixtures in a real browser |
| slow | ParaBank; model cases also require ANTHROPIC_API_KEY | Live replay, discovery, compilation, and promotion-gate checks |

The login integration test replays the hand-written login recording 100 times
across seeded users while asserting that no LLM host is contacted. The
zero-LLM test also scans the replaykit package for model-SDK imports.

## Current limits

- Replay supports click, fill, and select actions; multi-tab and frame flows
  are not supported.
- Select values that are not declared inputs can remain tied to the account
  chosen during discovery. Locator targets have positional fallbacks; select
  values do not yet. This is what fails the three end-to-end promotion cases
  noted under "Tests" above.
- A flow that mutates bank state needs a reset hook before promotion replays.
- The local operator dashboard shares the same process and browser session as
  the run. It is not a remote, authenticated operator console.
