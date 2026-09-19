# replaykit

Record a browser flow once — with a model watching and driving — and replay it
forever afterward with **zero LLM calls**. `replaykit` is a record/replay
system for browser automation against a real banking demo app (ParaBank):
an LLM is used exactly once, at discovery time, to work out *what* a flow
does; everything after that is a deterministic, mechanically-derived
recording that a small Python engine replays against Playwright.

The zero-LLM guarantee isn't a design aspiration — it's enforced by a test
(`tests/test_zero_llm.py`) that fails the whole suite if anything under
`replaykit/` imports an LLM SDK. The one module that talks to a model
(`replaykit/recorder/session.py`) receives its client by injection, so the
import never has anywhere to hide.

---

## Quickstart

### Prerequisites

- Python 3.11+
- Docker (to run ParaBank locally)
- An `ANTHROPIC_API_KEY` — only needed to *record* a new flow or run the
  live recorder tests; replaying an existing recording needs no API key at all

### Install

```bash
pip install -r requirements.txt
playwright install chromium
```

### Start ParaBank

```bash
docker compose -f docker/docker-compose.yml up -d
```

This serves ParaBank at `http://localhost:9099/parabank` (override with the
`PARABANK_URL` env var). The compose healthcheck waits for the app to
actually be serving — give it 30-60s on a first pull. Verify:

```bash
curl -f http://localhost:9099/parabank/index.htm
```

If you want to record a new flow, put your key in `.env` (already
gitignored):

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
```

### Run the tests

```bash
python -m pytest -q -m "not slow"   # unit + component tests — no browser, no ParaBank, no API key
python -m pytest -q -m slow         # live tests — needs ParaBank; LLM cases skip cleanly without a key
```

`not slow` is the fast inner-loop suite (~80 tests, seconds). `slow` drives a
real headless Chromium against live ParaBank and includes:

- `tests/integration/test_login_replay.py` — replays the hand-authored
  `replaykit/flows/login.yaml` **100 times** (10 users × 10 repeats) against
  live ParaBank and asserts zero outbound calls to any LLM host
- `tests/integration/test_recorder_end_to_end.py` — records all four example
  flows from scratch against live ParaBank with a real model, compiles each
  trace, and runs it through the promotion gate (3 replays against 3
  different seeded users). Each case is `pytest.mark.parametrize`d and
  independently skips (not fails) if `ANTHROPIC_API_KEY` isn't set.

### Replay an existing flow

```python
from pathlib import Path
from playwright.sync_api import sync_playwright
from replaykit.recording.loader import load_flow
from replaykit.replayer.engine import ReplayEngine

flow = load_flow(Path("replaykit/flows/accounts_overview.yaml"))

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("http://localhost:9099/parabank/index.htm")
    result = ReplayEngine().run(page, flow, {"username": "...", "password": "..."})
    print(result.status, result.outputs)  # "success", {"balance": "$515.50"}
    browser.close()
```

No model, no API key, no network call to anywhere but ParaBank.

### Record a new flow

```python
from pathlib import Path

from playwright.sync_api import sync_playwright
import anthropic
from replaykit.recorder.session import record
from replaykit.recorder.spec import FlowSpec, InputSpec, OutputSpec
from replaykit.compiler import compile_trace

spec = FlowSpec(
    name="my_flow",
    goal="Log in and read the first account's balance.",
    start_url="http://localhost:9099/parabank/index.htm",
    inputs={"username": InputSpec("string", secret=True), "password": InputSpec("string", secret=True)},
    outputs={"balance": OutputSpec("decimal")},
)

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(spec.start_url)
    trace = record(page, spec, {"username": "...", "password": "..."}, client)
    assert trace.status == "success"
    yaml_text = compile_trace(page, trace, {"username": "...", "password": "..."})
    browser.close()

Path("replaykit/flows/my_flow.yaml").write_text(yaml_text)
```

In practice, never skip the **promotion gate** (`replaykit/promotion/gate.py`)
before trusting a compiled recording — see [Phase 2](#phase-2-the-recorder)
below. `replaykit/flows/specs.py` has four real examples end to end.

---

## Architecture

### The core idea

Most "AI browser agent" systems pay an LLM's latency, cost, and
non-determinism on *every single run*. replaykit pays that cost exactly
once — during a one-time discovery session — and converts what the model
did into a plain-data recording (`recording.yaml`) that a deterministic
engine can replay indefinitely. The model never sees the page again after
recording. Replay is regular Playwright automation: resolve a locator, act,
check a predicate, repeat.

This works in two layers, built in two phases:

```
 ┌─────────────────────────── Phase 2: the recorder ───────────────────────────┐
 │                                                                              │
 │   FlowSpec (prose goal)                                                     │
 │        │                                                                    │
 │        ▼                                                                    │
 │   ┌─────────────┐   ai-mode snapshot    ┌───────────────────┐               │
 │   │   session   │◄──────────────────────┤   live browser     │              │
 │   │  (LLM loop) │──── click/fill/... ──►│   (Playwright)      │             │
 │   └──────┬──────┘                       └───────────────────┘               │
 │          │ Trace (steps + candidate ladders, captured live)                 │
 │          ▼                                                                  │
 │   ┌─────────────┐                                                           │
 │   │  compiler   │  states.py: name & discriminate states                    │
 │   │             │  candidates.py: verify locator ladders                    │
 │   │             │  emit.py: render recording.yaml                          │
 │   └──────┬──────┘                                                           │
 │          ▼                                                                  │
 │   ┌─────────────┐                                                           │
 │   │ promotion   │  N replays through the UNMODIFIED Phase 1 engine,         │
 │   │   gate      │  against N different users, zero LLM calls               │
 │   └──────┬──────┘                                                           │
 └──────────┼───────────────────────────────────────────────────────────────┘
            │ recording.yaml (only if every replay passed)
            ▼
 ┌─────────────────────────── Phase 0/1: the replayer ─────────────────────────┐
 │                                                                              │
 │   recording.yaml → loader (strict validation) → Flow                        │
 │                                                     │                       │
 │                                                     ▼                       │
 │                                            ReplayEngine.run()               │
 │                                          (locator ladder, state predicates, │
 │                                           recovery, extraction — no LLM)    │
 └──────────────────────────────────────────────────────────────────────────────┘
```

The recorder produces recordings; the replayer consumes them. The replayer
was built and proven first (Phase 0/1) against a **hand-written** recording
(`replaykit/flows/login.yaml`); the recorder (Phase 2) exists to produce
that same recording format *mechanically*, so nobody has to hand-write one
ever again.

### Package layout

| Package | Responsibility |
|---|---|
| `replaykit/recording/` | The recording format itself: `schema.py` (dataclasses), `loader.py` (strict, fail-fast YAML validation) |
| `replaykit/locators/` | `ladder.py` — resolves a ranked list of locator candidates against a live page, first one that matches *exactly one* element wins |
| `replaykit/states/` | `predicate.py` — is the page currently in a given named state? (URL regex + partial aria-snapshot match) |
| `replaykit/replayer/` | `engine.py` (the replay loop), `extract.py` (typed output extraction), `recovery.py` (declared dialog-dismiss / session-expiry rules), `handoff.py` (structured failure artifact), `audit.py` (append-only JSONL run log) |
| `replaykit/harness/` | Test-support utilities: `seed.py` (deterministic ParaBank user provisioning via its REST API), `faults.py` (chaos injection — strip DOM ids, delay responses) |
| `replaykit/recorder/` | The only package that talks to an LLM. `snapshot.py` (ai-mode accessibility capture with addressable refs), `spec.py` (`FlowSpec` — what to record), `trace.py` (what got recorded), `tools.py` (the model's tool vocabulary), `session.py` (the discovery loop) |
| `replaykit/compiler/` | Trace → recording, with **no LLM involved**: `candidates.py` (mechanical, live-verified locator derivation), `states.py` (state identity & discriminating aria templates), `emit.py` (YAML rendering) |
| `replaykit/promotion/` | `gate.py` — the acceptance test a compiled recording must pass before anyone trusts it |
| `replaykit/flows/` | Compiled recordings, ready to replay. `login.yaml` is hand-written (Phase 0/1's original proof); `accounts_overview.yaml` was produced end-to-end by the Phase 2 pipeline against live ParaBank |

### The recording format

A recording is plain YAML: named **states** (a URL pattern plus a partial
accessibility-tree template that must match), a linear list of **steps**
(each naming the state it starts from, an action, a *ranked list* of locator
candidates, and optionally the state it ends in), and optional **extract**
entries for reading typed values off the page. `replaykit/flows/login.yaml`
is the whole format in miniature:

```yaml
flow: login
version: 1
inputs:
  username: {type: string, secret: true}
  password: {type: string, secret: true}
states:
  login_page:
    url: /parabank/index\.htm
    aria: |
      - heading "Customer Login"
      - button "Log In"
  accounts_overview:
    url: /parabank/overview\.htm
    aria: |
      - heading "Accounts Overview"
steps:
  - from: login_page
    action: fill
    target:
      - {css: "input[name=username]"}
      - {xpath: "//p[b='Username']/following::input[1]"}
    value: "{{inputs.username}}"
  - from: login_page
    action: click
    target: [{role: button, name: "Log In"}]
    to: accounts_overview
recovery:
  - when: {aria: "- dialog"}
    do: [{action: click, target: [{role: button, name: "/close|dismiss|ok/i"}]}]
  - when: {state: login_page}
    do: [{handoff: session_expired}]
```

A few properties are load-bearing:

- **A target is a ranked ladder, never a single selector.** `resolve()`
  (`locators/ladder.py`) tries each candidate in order and takes the first
  one that matches *exactly one* element on the live page. Ambiguity (more
  than one match) is a hard failure, never "take the first" — a locator that
  might click the wrong thing is worse than one that fails loudly.
- **A state is a predicate, not a snapshot.** `matches()`
  (`states/predicate.py`) checks the current URL against a regex *and* the
  page against a partial aria-snapshot template via Playwright's own
  `expect(page).to_match_aria_snapshot(...)`. It only needs to name enough
  of the page to be unambiguous — `login.yaml`'s states use two lines each.
- **Recovery is declared, never hardcoded.** `recovery.py` understands two
  rule *shapes* (dismiss a dialog matching an aria template; declare a named
  state as meaning "session expired") — which dialog wording or which state
  name means what comes entirely from the recording, not from code.
- **A failure is a structured handoff, not an exception the caller has to
  parse.** `HandoffRecord` (`handoff.py`) captures the expected state, the
  actual URL and aria snapshot, a screenshot, per-candidate ladder outcomes,
  timings, and redacted inputs — everything needed to diagnose why a replay
  didn't match, without ever leaking a secret input into the record.

### Phase 0/1: the replayer

`ReplayEngine.run()` (`replayer/engine.py`) is the whole replay loop: for
each step, wait for its `from` state's predicate (retrying once through
`recovery.recover()` if it doesn't hold), resolve the step's locator ladder,
act, and — if the step names a `to` state — wait for that predicate too
before moving on. Two attempts per step; the second failure produces a
`HandoffRecord` and the run stops rather than guessing. If the flow declares
`extract` entries, they run once every step has succeeded, and their values
are validated against the flow's declared output types (`extract.py`) —
a balance that doesn't parse as a decimal is a `handoff`, not a false
`success`.

This is proven against live ParaBank at real scale:
`test_login_replays_100_times_against_ten_seeded_users_without_llm_calls`
runs `login.yaml` 100 times (10 seeded users × 10 repeats) while routing
every request to a known LLM host to an aborting handler — the assertion
that catches that list is empty is the zero-LLM guarantee made concrete for
one specific flow, on top of the whole-package import guard.

### Phase 2: the recorder

Four stages, run in sequence, each independently testable:

**1. Snapshot** (`recorder/snapshot.py`) — `capture()` calls Playwright's
`aria_snapshot(mode="ai")`, which annotates every interactive element with
an ephemeral `ref` (e.g. `[ref=e34]`) the model can address even when the
element has no accessible name (many ParaBank inputs don't). Navigation
chrome (nav bars, footers) is pruned by role and by a fixed set of known
link labels, since a login page can otherwise emit ~100 refs that are
almost entirely noise.

**2. Discovery loop** (`recorder/session.py`) — `record()` drives an
injected Anthropic client over the live page. Each turn: send the current
snapshot, get back one tool call (`tool_choice` explicitly disables
parallel tool use — the loop only executes and replies to one call per
turn), execute it, capture the resulting snapshot, and record a `TraceStep`
carrying that snapshot pair plus a **locator ladder derived and verified
right then**, while the snapshot that identified the element is still live
(refs are ephemeral and get reassigned after every navigation). The tool
vocabulary (`recorder/tools.py`) is `click` / `fill` / `select` / `goto` /
`extract` / `done`, every element-targeting one keyed by `ref`, never by
name. `goto` executes but is never recorded as a step — the harness already
navigates to the flow's start URL, and the Phase 1 engine has no `goto`
action to replay it with anyway. After every action, `_settle()` gives
async content (a table that populates a moment after the page loads) a
chance to finish rendering — a `networkidle` wait plus a short fixed grace
period, since a capture taken mid-render produces a snapshot that's a
strict subset of the same page a moment later.

**3. Compiler** (`replaykit/compiler/`) — turns a `Trace` into a recording
with **zero model calls**:
  - `states.py` decides state *identity*: two visits collapse to one state
    if they share a URL and an **anchor** — the first `[level=1]` heading if
    one exists (a page's own title, preferred over a shared nav heading
    like ParaBank's left-sidebar "Account Services"), else the first
    heading of any level, else the first usable line. ai-mode-only
    annotations (`[ref=]`, `[cursor=]`, momentary `[active]` focus) are
    stripped first, since none of them are stable across visits to the same
    page. `discriminates()` then checks a candidate template matches its
    own state and no other; if the anchor alone isn't enough,
    `widen_template()` adds lines until it is, or raises rather than ship a
    template that's too loose to mean anything.
  - `candidates.py` derives a ranked locator ladder for one element:
    role+name if the element has a stable accessible name, its own `id` if
    it has one, a **positional** locator (walk up to the nearest ancestor
    with a stable id and express the element as an `nth-of-type` position
    within it — how "the balance in the first account row" is located
    without depending on whose balance it actually is), and finally a
    text-anchor derived from nearby stable content. Every candidate is
    verified against the live page before being kept; role+name and
    text-anchoring are skipped entirely for data cells (`role="cell"`),
    since a cell's accessible name *is* its own dynamic content.
  - `emit.py` renders the recording YAML and **auto-parameterizes**: any
    recorded value that exactly matches a supplied input becomes
    `{{inputs.name}}` rather than a literal, so the same recording works for
    every user, not just the one who happened to be logged in during
    discovery.

**4. Promotion gate** (`promotion/gate.py`) — replays the compiled
recording through the **unmodified Phase 1 `ReplayEngine`**, N times,
against N different (freshly seeded, if the flow declares a `reset` hook)
users. This is the whole point of the architecture: the zero-LLM guarantee
for a *newly recorded* flow isn't asserted, it's *inherited* — by literally
running it through the same replayer that Phase 1 already proved at scale,
before a compiled recording is ever trusted.

### Known limitations

- **Select-value parameterization.** A `select` step's recorded *value*
  (e.g. an account ID) is only parameterized if it exactly matches a
  declared input — an account picked from a dropdown during discovery isn't
  one, so a recording can end up with a hardcoded account ID that doesn't
  exist for a different user. Locator *targets* got a positional strategy
  for exactly this problem (see `candidates.py` above); select *values*
  haven't yet.
- **Discovery reliability.** The model doesn't always execute a flow
  cleanly — it can take redundant exploratory actions, or occasionally
  submit a form before filling it in, despite the discovery prompt telling
  it every action is a permanent replay step. This shows up as inconsistent
  live results across repeated recordings of the same flow, and is a
  prompt/model-behavior question rather than something a compiler-side fix
  can guarantee.
- Only `click`, `fill`, `select` step actions are supported at replay time
  (`ReplayEngine._act`); `goto` and multi-tab/frame flows are out of scope
  for this version.

---

## Testing reference

| Marker | What it needs | What it covers |
|---|---|---|
| (none, default) | nothing | Pure unit tests — dataclasses, YAML parsing, string logic |
| `not slow` (full fast suite) | nothing | Everything above, plus component tests against static local HTML fixtures (`tests/pages/`) via a real headless browser — no network, no ParaBank |
| `slow` | live ParaBank (`docker compose up`); LLM cases also need `ANTHROPIC_API_KEY` | Full integration: the 100-replay login gate, live recorder discovery + compile + promotion gate for all four example flows |

Run everything: `python -m pytest -q` (LLM-dependent `slow` cases skip
cleanly, never fail, when no API key is configured).
