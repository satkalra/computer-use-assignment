# REPORT

## 1. Architecture

replaykit separates discovery from execution. During discovery, an LLM receives
an accessibility snapshot and uses element references to drive a real browser.
The recorder captures the action, source and destination snapshots, and a
live-verified locator ladder while the reference is still valid. The compiler
then emits a YAML flow. Replay consumes only that flow and Playwright; it does
not import or call an LLM SDK.

This split makes the expensive, non-deterministic part a build-time activity
instead of a runtime dependency. A saved flow is inspectable, reviewable, and
can be replayed repeatedly against fresh users. The trade-off is that the
recording is only as durable as its state predicates and locator candidates.
The promotion gate addresses that by replaying a compiled flow repeatedly
before it is trusted, but it does not eliminate site drift.

~~~mermaid
flowchart TD
    A[FlowSpec and inputs] --> B[LLM-guided discovery]
    B --> C[Trace with live-verified locator ladders]
    C --> D[Compiler]
    D --> E[Reviewed YAML flow]
    E --> F[Deterministic ReplayEngine]
    F --> G{Policy allows step?}
    G -->|yes| H[Act and check destination state]
    G -->|risky| I[needs_approval]
    G -->|blocked| J[HandoffRecord]
    H -->|happy path| K[success]
    H -->|declared alternate state| L[business_outcome]
    H -->|technical failure| J
    I --> M[Local operator dashboard]
    J --> M
    M -->|Resume| F
    M -->|Abort| N[stop]
~~~

The guardrail and handoff layer keeps its control plane in-process. The CLI, the
replay loop, and the Flask dashboard share one ControlState object. That is
deliberately small:
there is no queue, database, websocket, or second service to deploy. The cost
is that the operator must be local to the machine running the browser, and a
process restart loses a pending handoff.

## 2. Artifact schema

A flow declares inputs, named page states, steps, recovery rules, and optional
typed outputs. A state combines a URL pattern with a partial accessibility
snapshot. A step names its starting state, an action, a ranked list of targets,
and optionally its expected destination state.

The locator list is a practical compromise for legacy applications. A clean
role-and-name locator is preferred, but a flow can fall back to an element ID,
a position beneath a stable ancestor, or a nearby text anchor. Replay accepts
only a candidate that resolves to exactly one element. Refusing ambiguous
targets makes a missed run easier to diagnose than a run that clicks the
wrong control.

The outcomes block adds named, non-happy-path terminal states. For example,
a search flow can declare no_results and extract the displayed message. These
outcomes are hand-declared rather than inferred by the model. That keeps the
business meaning in the reviewed artifact and avoids a second heuristic
discovery pass.

## 3. Determinism & error handling

Replay waits for a step's starting predicate, resolves its locator ladder,
performs one action, and waits for the destination predicate. It retries once
through the flow's declared recovery rules. If a declared outcome state matches
after a failed postcondition, replay returns business_outcome immediately
instead of retrying or escalating a valid result.

Technical failures return a HandoffRecord. The record includes the expected
state, current URL, accessibility snapshot, base64 screenshot, candidate
outcomes, timing, and redacted inputs. It gives an operator enough context to
decide whether to fix the page and resume, or abort. Existing callers retain
the established handoff status for technical failures; the CLI treats that
status as an escalation path.

On resume, the engine matches the live page against step states starting from
the step that got stuck, never earlier. This avoids persisting a mutable
"current step" pointer that can become wrong after a human changes the page,
while also avoiding a real bug an earlier version of this had: searching from
step 0 would return the *first* step matching a given state, so a stuck point
partway through several same-state fields (three fields on one login page, for
example) would resume by replaying the earlier fields. Pinning the search to
"at or after the stuck step" fixes that without needing a stored step counter.

## 4. Heterogeneity & multi-tenant

The useful boundary is state matching plus target resolution, not Playwright
itself. A different browser-like surface could replace the accessibility-tree
predicate and locator implementation while keeping the flow's state, step,
and ranked-target model. That matters for older applications where semantic
roles are sparse and positional or anchored candidates carry more weight.

For tenants, a base flow can remain shared while a small override replaces
only a state predicate or target ladder for a tenant-specific UI variation.
The current implementation does not add that override layer. It keeps the
recording format stable enough to support it later, and repeated promotion
replays are the natural drift signal when an application changes.

## 5. Escalation & handoff

The CLI opens the browser headed when a ControlState is present. If replay
returns a technical handoff or needs_approval, it writes intervention.json,
captures a screenshot, exposes the reason in the Flask dashboard, and blocks
the automation loop. The operator then uses the same Playwright page that the
automation left behind, rather than a new session or a screenshot-only mock.

The dashboard has two decisions: Resume and Abort. Resume returns ownership
to the agent and re-runs from the matching live state. Abort leaves the run
failed. Browser-side capture listeners write click, change, and submit events
to human_actions.jsonl. Password inputs and fields declared secret are redacted
before the value reaches that log.

This is intentionally a local operator mechanism. A remote console would add
authenticated access, a CDP or screencast relay, a durable intervention queue,
and concurrency rules for multiple operators. Those are product concerns, not
necessary infrastructure for proving the handoff state machine in this
assignment.

## 6. Safety

Policy is enforced at the two points where the system can act: recorder
discovery and deterministic replay. The policy allowlists URL origins and
action types. An origin or action outside that list raises a hard violation.
Risk patterns match the target name, such as Transfer Funds or Open Account,
and require a step-index approval before replay performs the action.
Unnamed click and select targets also require approval; selector syntax alone
is not treated as evidence that an action is safe.

The risk rule is deliberately conservative but limited. Regex matching cannot
recognize a risky action whose accessible name is vague or missing. It is,
however, one central enforcement point rather than separate ad-hoc checks in
each flow. A later version can replace the rule with explicit per-step
capabilities without changing the recorder or dashboard interface.

The recorder prompt uses placeholders such as {{inputs.password}} for every
input. It resolves a value only inside the fill or select call that acts on the
browser, which keeps literal credential values out of the model prompt while
preserving parameterized recordings for later replay. That alone isn't enough:
Playwright's accessibility snapshot doesn't mask a filled type=password field,
so the very next snapshot taken after a fill would put the real value back in
front of the model and into the saved trace. Both the recorder and the replay
engine's failure record redact every declared secret value out of a snapshot's
text before it's used anywhere else.

## 7. Cuts

- No remote operator console, authentication, queue, or websocket transport.
- No durable handoff state across a process restart.
- No running multi-tenant override system or scheduled drift monitor.
- No native-desktop adapter.
- No model-assisted replay recovery after a technical failure.
- The dashboard polls once per second instead of using push updates.
