# Evidence

One live discovery run against ParaBank, then three replays of the resulting
artifact with no model in the loop. The discovery run made real Claude API
calls; nothing here is scripted.

## Discovery

`discovery-accounts_overview_live-1790046700/`

| File | Contents |
| --- | --- |
| `log.jsonl` | One line per model turn: the model's stated reason, the tool it called, the URL, and the outcome |
| `trace.json` | Recorded actions with before/after accessibility snapshots and live-verified locator ladders |
| `recording.yaml` | The compiled flow, before review |
| `promotion_gate.json` | 3 replays of the compiled flow, all passed, before it was saved |
| `artifact.yaml` | The reviewed flow: `recording.yaml` plus a hand-declared `invalid_credentials` outcome |

Secret inputs appear as `[REDACTED]` or `{{inputs.name}}` throughout.

## Replays

All three replay `artifact.yaml` (saved as `replaykit/flows/accounts_overview_live.yaml`).

| Run | Scenario | Result |
| --- | --- | --- |
| `replay-accounts_overview_live-1790046822/` | Correct credentials | `success`, balance `-$497.50` |
| `replay-accounts_overview_live-1790046828/` | Wrong password | `business_outcome` / `invalid_credentials`, message "The username and password could not be verified." |
| `replay-accounts_overview_live-1790046844/` | Replay started on the wrong page (`about.htm`) | `handoff`, precondition failed; `intervention.json` and a screenshot in `result.json` |
