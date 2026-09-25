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
| `replay-transfer_funds_nav-1790303756/` | Hand-written `transfer_funds_nav.yaml`: log in, then click the "Transfer Funds" nav link | `needs_approval` (matches `policy.yaml`'s `(?i)transfer` risky pattern), operator resumes via the dashboard, replay continues and lands on the Transfer Funds page: `success`. `human_actions.jsonl` present. |

`transfer_funds_nav.yaml` stops at the Transfer Funds page rather than submitting a transfer: the account-select dropdown is populated per-user by ParaBank, and the compiler's locator ladder does not yet have a positional fallback for `select` values (see README's "Current limits") — submitting the actual transfer is out of scope here, this run only demonstrates the approval-gate and operator-resume mechanism.
