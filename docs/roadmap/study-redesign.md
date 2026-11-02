# Roadmap: study redesign

This branch makes the reconstruction task measurable enough to support a clean comparison. Every change is opt-in through config. Existing configs, archived evidence and default behavior are unchanged, and `events.jsonl` remains the source of truth. No change here makes a model call or relaxes the free-only, zero-price guard in `swarm_canvas/models.py`.

## Why change the study

The exploratory findings show three problems that more of the same runs would not fix:

- **Background dominates pixel agreement.** 333 of the 384 target cells are sky or water. The 48-round run scored 207 of 384 by painting everything light blue (S), which equals the reference's 207 S cells.
- **Coordination is optional.** With a shared full reference, any agent can do the whole job alone, so comms on or off need not matter. Most paints also repeated an existing color (419 of 562 in the first open-ended runs).
- **Completion is a message, not an action.** Agents wrote "Canvas complete" while 209 cells were blank, and peers then stopped. That claim was only ever a chat line, so it could not be counted or checked.

## 1. Prefilled background

`task.prefill_background: [S, W]` (reconstruction only). Before round 1 the harness paints every target cell whose color is listed. The cells are attributed to the pseudo-agent `prefill` (`agent` and `agent_id` both `"prefill"`) and logged as `prefill` events with `round: 0`, a distinct type from `paint`. Agents see the cells on the canvas and in CHECK counts, plus one prompt line saying the harness painted them.

Rationale: the remaining 51 cells (sun, cloud, hull, mast, sail) are the part of the picture that needs work. Removing the free 333 stops background agreement from masking the result and stops the budget being spent on sky and water. Prefill never counts as agent work: it is not a paint, not in `per_agent`, not a peer overwrite, and not in useful/wasted. It does count toward canvas-level `target_accuracy`, which describes the canvas, not the agents.

## 2. Split reference

`task.reference_split` maps a slot (`slot-0`) or starting handle (`a1`) to a fragment. A fragment is a named region (`sun`, `cloud`, `hull`, `mast_sail`), a color list, or `{colors, rows, cols}` with inclusive 1-based rows and column letters. `swarm_canvas/reference_split.py` derives fragments from the target by color and optional row/column range and renders every cell outside the fragment as `?`.

Each observation contains only that agent's fragment, under a block that says it holds one piece and its teammates hold the rest. The system objective says the same. The prompt is identical across comms arms; it does not tell agents to talk. Fragments are saved to `reference_fragments.json` and the normalized spec is in the manifest.

Validation is strict: every agent needs a fragment, no fragment may be empty, and the fragments must cover every target cell that is not prefilled. Without that coverage some cells would be unknowable to everyone. Overlap is allowed. The option is rejected together with `assistance.suggested_paints`, which would leak the whole target.

Rationale: if each agent knows only part of the target, the team can finish only by sharing what it knows. Comms on versus comms off (`redesign_split_comms` vs `redesign_split_nocomms`) then becomes a clean contrast in which the channel is the only difference.

## 3. Scoring

New `scores.json` keys, computed from events and the saved target (existing keys are unchanged):

| Key | Meaning |
| --- | --- |
| `nonbackground_accuracy` | Matches over target cells not in the background set. Background defaults to `S`, `W`; override with `task.background`. |
| `nonbackground_by_round` | The same fraction after every round up to the configured horizon. |
| `rounds_to_nonbg_threshold` | First round at 0.9 or higher, with cumulative `paints`, `input_tokens`, `output_tokens` and `tokens` at that point; `null` if never reached. |
| `useful_paints` | Applied paints that changed a cell to its correct target color. |
| `wasted_paints` | Same-color repaints (`wasted_same_color`) plus paints that changed a correct cell to a wrong color (`wasted_destroyed_correct`). |
| `neutral_paints` | The rest (for example blank to wrong, or wrong to a different wrong). Useful, wasted and neutral sum to `paints`. |

Rationale: the curve gives a time-capped anytime measure. Runs are compared at equal rounds and at equal tokens rather than only at an end state, and the early-stop and fixed-horizon runs line up. Useful versus wasted exposes the repeated-paint pattern that earlier tables could only report as a replay count.

## 4. The "done" action

Top-level `stop_action: true`. An agent may include `"done": true`. Paints and messages in that reply still apply. The agent then takes no further turns: no model call, no inbox read, no exposure event. The run ends early if all agents are done, and the manifest records `rounds_executed` and the shorter `final_frame`. The reply schema (`done: boolean`) and a short DONE prompt block exist only when the option is on. A non-boolean `done` is an `invalid` event.

A `done` event records `round`, `agent`, `agent_id`, and the blank and incorrect non-background cell counts twice: `*_seen` from the round-start snapshot the agent actually saw, and `*_after` from the post-round frame (simultaneous peers can change the canvas in between). Under a split reference it also records `fragment_blank_after` and `fragment_incorrect_after` for the agent's own piece. Scores add `first_done_round`, `done_rounds` per agent, `done_while_incomplete` (any agent declared done while any non-background cell was blank or wrong in the post-round frame) and `done_while_incomplete_by_agent`.

Rationale: a completion claim becomes a recorded action with a ground-truth check, and the "Canvas complete" failure turns into the primary endpoint, a measurable event rather than something found by reading chat. The tradeoff is that done is irreversible, so an agent that quits early cannot fix later damage. That is also what makes premature stopping visible.

## 5. Catalog off switch

`supplier.enabled: false` or `supplier.swarm_budget: 0` disables the catalog. Prompts switch to `*_nocatalog` variants with no catalog text, the LLM reply schema drops `requests`, a request in an action is rejected as `invalid` with reason `catalog_disabled`, and `Supplier.request` denies with the same reason. Enabled configs render exactly as before.

Rationale: the target needs no catalog color, and in earlier runs repeated requests continued after the shared supply was exhausted. The catalog is parked, not removed.

## 6. Configs

All use `agents.type: random`, so they run offline with no model calls; the same files carry the pinned free model block, and a live run changes `agents.type` to `llm`. All prefill S/W, enable `stop_action`, park the catalog and run 24 rounds.

| Config | Agents | Paint budget per agent | Comms | Reference |
| --- | --- | --- | --- | --- |
| `redesign_split_comms.yaml` | 4 | 8 | SwarmChat | split: sun, cloud, hull, mast and sail |
| `redesign_split_nocomms.yaml` | 4 | 8 | none | same split; differs only in `comms.kind` |
| `redesign_solo.yaml` | 1 | 32 | none | full reference, no split |
| `redesign_reasoning_calibration.yaml` | 4 (`llm`) | 8 | SwarmChat | split_comms plus `reasoning_enabled: true`; makes live free-model calls |
| `redesign_size_{2,4,8,16}.yaml` | N | 32 / N | SwarmChat | split into N fragments |

- **Matched solo baseline.** One painter with 32 paints per round has the same allowance as four with 8, the full reference and no coordination problem. It separates "the team is slower because the information is split" from "the team has fewer paint opportunities".
- **Size sweep with a fixed team allowance.** Per-agent budgets are 16, 8, 4 and 2, so the team always has 32 paints per round, and growing N changes who holds what, not how much can be painted. Fragments are a partition of the 51 non-background cells: 2 groups (sky objects, boat), 4 as above, 8 and 16 by splitting regions further by column (the mast and sail by row and column). `redesign_size_4` is the same experiment as `redesign_split_comms` under another run code. Model-call and token counts still grow with N and should be reported, not controlled.
- Reasoning tokens share `model.max_tokens` (1600); with `reasoning_enabled: true` watch `parse_errors` for truncated replies before reading anything into the arm.

Offline random runs only prove the pipeline and scoring: random agents ignore observations, so comms and split have no effect on them (hence identical scores for the comms and no-comms configs).

## Stronger-model calibration (recommended, not implemented)

A single pinned free model may be too weak for the split task to expose a communication effect; a floor effect would look like "comms do not help". A calibration arm with a stronger model would show whether the task is solvable at all and where the free model sits relative to it. That requires the owner to deliberately relax the free-only guard in `swarm_canvas/models.py` (`validate_model_policy`, plus the zero-price ceilings in the OpenRouter payload) or to add a separate, explicitly opted-in policy. This branch does not do either, and no config here names a non-free model.

## Running it

    python cli.py run configs/redesign_split_comms.yaml --seed 1
    python -m pytest -q

## Limits

- The ordering, retry and recovery machinery is unchanged. Resume still supports only unassisted free creation; reconstruction runs with these options are not resumable, and the prompt additions change the source fingerprint used to match a resume to its run.
- Three-seed comparisons remain a replication check, not a general result. Report every attempt.
- The done action is irreversible by design. Its incorrect and non-background counts need a target, so in free creation the `done` event records only total blank cells and `done_while_incomplete` is `null`.
