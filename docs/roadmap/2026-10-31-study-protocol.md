# Swarm Canvas: proposed six-run comparison

Status: protocol prepared; not preregistered or launched. Freeze the code, this document,
the generated preview notes, model endpoint and provider-price ceilings in a versioned
commit before any confirmatory inference. Existing runs, including the completed DeepSeek
run, are exploratory and do not count toward this comparison.

This is the earlier reference-preview comparison, preserved as a distinct experiment.
The subsequently merged [study redesign](study-redesign.md) uses prefilled backgrounds,
split references and a `done` action. Its outcomes, stop behavior and conditions differ;
do not pool or label these six runs as the redesigned experiment. The original longer-term
goal remains plain-text open creation with optional guardrails, not reconstruction alone.

## Research question

When agents reconstruct a reference from one initial look, does a factual reminder after
a claim of whole-canvas completion change subsequent behavior? The reminder is an
assistance/guardrail intervention. This is a controlled reconstruction task; it does not
demonstrate performance on the separate ultimate goal of painting a scene from text alone.

## Schedule and fixed settings

Six 24-round runs: seeds 11, 12, 13, each with four painters on a 24 × 16 canvas and native
SwarmChat. Each painter may apply up to eight paints per round. Model is
`deepseek/deepseek-v4.1-flash-1017`, temperature 0.2, max output 1600 tokens, reasoning
disabled, same palette, reference, prompts, interface feedback, action and message limits
in both arms. Harness seeds affect shuffle order, not reproducibility of model responses.

For each seed, generate one set of four preview notes before the pair; persist the exact
notes, prompts, responses and calls; reuse those same notes in both arms. Agent slots and
notes must match within each pair. Interleave order: baseline 11, reminder 11, reminder 12,
baseline 12, baseline 13, reminder 13. Store every attempt separately, including failures.

Both arms receive the same initial objective: recreate the reference as accurately as
possible, including filling all cells. Their prior notes remain available for every round.
Both have the existing canvas and blank-count feedback; neither has reference access after
preview. Both run the full 24 rounds unless stopped for infrastructure or budget failure.

* **Baseline:** existing interface, no extra reminder.
* **Reminder:** at the start of the next round after an eligible completion claim is
  actually observed in a native SwarmChat message, append the identical text to each
  painter's observation: `A previous message claimed the whole canvas was complete.
  Check the current canvas and the blank-cell count before deciding what to do.` The
  reminder is delivered at most once per run; it neither stops the run nor specifies
  locations or colors. Log the original message ID, sender, round, recipient round and
  exact reminder. Round-24 claims are observable but cannot trigger a later reminder.

The trigger is a deterministic, versioned rule over applied SwarmChat messages, not
scratchpads, model reasoning or private notes. It must require an affirmative statement
that the *whole* canvas/painting/scene is complete, such as `canvas is complete` or
`finished the entire painting`. Ignore questions, negations, future plans, and claims
about a row, object or individual action. Save the triggering text and candidate matches;
manually classify all candidates in both arms blinded to arm. Ambiguous cases are recorded,
not silently interpreted. The trigger implementation and tests must be frozen before launch.
The trigger is intentionally narrow and misses statements such as `we are done` without
an explicit canvas/painting/picture/scene noun; manual review of all messages and
scratchpads is required for a broader descriptive estimate. Such review must not change
which messages triggered the intervention during a run.

## Outcomes and analysis

The primary descriptive outcome is the fraction of runs with an affirmative whole-canvas
completion claim while any cell differs from the reference, using the round-start canvas
available to the sender. Blank is incorrect; a filled cell of the wrong color is also
incorrect. Record the sender, evidence text, round, observed frame, mismatching cells and
blank cells. Agent views are frozen at round start; report post-round counts separately.
The reminder occurs after the claim, so it **cannot cause or prevent that first claim**.
Its causal contrast concerns subsequent behavior and final outcomes, not the incidence
of the trigger that causes the reminder. Runs without an eligible claim remain in their
assigned arm and receive no reminder.

Report as secondary outcomes: paints after the first claim; number of subsequent
whole-canvas claims; final blank count; exact whole-grid match; match on reference cells
whose colors are not S or W; sequential same-color repaints and round-start redundant
proposals (separately); messages, acknowledgments, provider, token usage, USD cost and
latency. An acknowledgment means delivery, not understanding. A stable human rating
rubric with blinded independent raters is a separate quality measure, not a substitute
for exact reconstruction. Do not infer visual quality from coverage.

Show one row per attempt, including missing outcomes for failed attempts, and compare
paired outcomes by seed without significance claims from three pairs. Report eligible
claims and how many runs actually received the reminder. The same seed does not guarantee
the same model outputs. If no claims trigger the reminder, say the intervention was not
tested; do not reclassify or tune after viewing outcomes.

## Reliability and stop rules

Require matching source and prompt hashes, a separate durable request ledger per attempt,
4.2-second minimum request interval, no automatic paid-model substitution, and provider
maximum prices no greater than $0.30/M input and $1.20/M output as configured. Confirm
current model availability, key allowance and actual provider pricing before starting;
per-token limits are not an aggregate dollar cap. Set a dedicated OpenRouter key spending
limit before launch. Log every preview, model response, canvas frame, message and action.
Stop on missing model/cost metadata, unexpected provider/model, unknown request outcome,
rate limit, malformed responses after repair, failed native transport, source changes,
missing trace or ledger mismatch. No partial-round replay or automatic retry of a failed
attempt. A failed attempt remains in the table; any replacement is separately identified.

Audit the completed attempt with `python -m swarm_canvas.run_audit RUN_DIR --ledger
LEDGER --preview PREVIEW_DIR`. External Langfuse delivery is a separate check; a closed
local trace does not prove delivery. Report any recovered checkpoint-read errors. Run on
an explicitly provisioned ephemeral filesystem only if all artifacts are durably copied
and verified afterward. The checkpoint HTTP 400 root cause is unresolved; a successful
run is not evidence the issue is fixed. LLM continuation from an interrupted attempt is
not supported for this protocol.

## Prerequisites and follow-ups

The paired runner, shared-preview handling, reminder integration, scorecard, per-attempt
ledgers and restart checks are implemented and exercised with mocked model responses and
the real local SwarmChat server. `experiments.paired_study` also checks that the selected
OpenRouter key has a non-resetting remaining allowance no greater than $50. Provider
accounting and other users of the key can affect available allowance; the limit depends
on OpenRouter enforcement. Use a dedicated key and verify its settings immediately before
launch. The current reference pilot was exploratory and was not produced by this runner.

Before inference, publish an immutable source and protocol snapshot, verify it matches
the batch's source hashes, verify that the batch destination is durable and accessible,
and independently review the scorecard and original checkpoint failure. The in-memory
workaround has one completed live run, but its underlying HTTP 400 cause is not proven
fixed. Do not describe this document as preregistered before a timestamped snapshot exists.

The broader roadmap proposes look-cost and plan-drift comparisons, a second model,
mixed-model swarms and 2/4/8-agent teams with a fixed team budget. These are separate
follow-ups, not a frozen 39-run schedule: model selection, per-slot model support and
precise conditions are not finalized. The original proposed free blank-count condition
duplicates existing CHECK information; an outside `done` rejection has no defined effect
because `done` is a message, not a stop action. Neither is a valid independent arm yet.
