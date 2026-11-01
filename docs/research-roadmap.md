# Shortest path to a public result

Adapted from the supplied Swarm Canvas Roadmap. This plan separates an exploratory post using existing evidence from a replicated study. No new model runs are required to publish the first post.

## Release slice: public replay and one supportable claim

Lead with the retained-notes seed-11 run: an agent posted "Canvas complete" at round 12; the post-round canvas had 175 painted and 209 blank cells. At round 18 another agent explicitly cited that note and said no further paints were needed. These are observations, not a causal estimate of social influence or a result about all models.

Deliverables: public GIF, final frame, event log, all round frames, scratchpads and prompts, experiment source, reference, hashes, and a reproduction command. Keep native credentials/databases out. This slice supplies public evidence for this post; older account-specific evidence links still need migration before claiming the entire project is publicly reproducible.

The README should begin with the replay, the specific observation, and run instructions. Preserve limitations and the broader findings. Verify a clean checkout, tests, and public evidence links before tagging v0.1. A draft PR is not a release tag. Freeze inference/prompt behavior after selecting the study revision.

## Measurement slice: one scorecard before more inference

Implement a read-only scorecard for every archived attempt, including failures. Report round-start same-color proposals separately from sequential same-color repaints: the existing repetition totals are sequential replay counts, not all avoidable start-of-round duplication.

Detect whole-canvas completion claims separately from "row complete" or "hull done". Identify speaker, round, audience, and whether the claim refers to self, team or artifact. Retain uncertain cases for manual review. Distinguish estimates of zero remaining rounds from explicit textual claims. Record blank counts at both the observation used to make a claim and the post-round frame; simultaneous peers can change the canvas between them.

Report full-grid match, non-background match (reference colors other than S and W), coverage, first claim, subsequent paint actions, and claimed-vs-measured completion. Do not equate blank cells with failure in unconstrained free creation; the new reconstruction study must explicitly require every target cell to be filled. Have a human validate the detected claims in the retained-notes and turn-costing probes. For a research-quality visual comparison, obtain blinded independent ratings; do not manufacture human labels or use assistant impressions as rater agreement.

## Small preregistered study: six runs first

Use three seeds and two 24-round conditions, four painters, eight paint actions each, the same reference, same free model, identical memory settings, and interleaved condition order. This provides 768 paint opportunities per run for a 384-cell reference, including revision capacity. Generate one set of preview notes per seed before assignment and reuse them across arms; preserve them as measured model-generated input.

Define completion in the common task instructions before running. Baseline keeps the current interface. The intervention supplies a standardized factual completion-check reminder after a detected whole-canvas completion claim; specify exact trigger, timing and wording before inference. It must not expose a new target or suggest paint locations. Log unsupported or ambiguous claims rather than improvising prompts mid-run. Stop rules cover request budget, quota, native transport, source/model changes and malformed replies; record failed turns and interrupted attempts under the preregistered rule.

Crucial correction to the supplied roadmap: agents already receive painted and blank counts in CHECK on every observation. A "free count blank cells" arm is therefore not a new information treatment. Also, currently "done" is a message, not a harness stop action. An external checker cannot meaningfully reject it until its effect is defined. Avoid building a new stopping protocol simply to make that arm work.

Primary endpoint: whether each run makes a whole-canvas completion claim while the explicitly specified reconstruction remains incomplete. Secondary: blank count and non-background accuracy at first claim, post-claim paint activity, final scores, and cost. Three seeds are a small replication check, not enough to establish a general property or mechanistic explanation. Publish every attempt and keep the older pilots exploratory.

## Follow-up order

If the headline repeats, run the same comparison on a second free model before generalizing. Freeze the backup model only after verifying current availability, pricing and schema compatibility. No model substitution mid-study.

The existing matched look-cost schedule can follow; it should not delay the first public exploratory post. Its arms also differ in observation timing and model-call count, so describe it as a comparison of two access policies rather than a pure cost effect. Use equal round counts, fixed notes and all-seed reporting.

Mixed-model swarms, swarm-size comparisons and larger canvases are later work. For swarm size, keep team paint allowance fixed and report model-call/token differences. Continue to use SwarmChat and free-only inference. Do not add new tracing, recovery or ledger features for this release slice.

## Planning corrections

The proposed 21 runs need more than a single request estimate: 24 painting rounds × 4 agents = 96 baseline painting calls per run, plus previews, repairs, retries and optional look calls. A free look can add another generation per agent-turn. Preflight the ledger's actual cap for each condition and spread runs across quota windows as needed. No overnight execution is implied unless separately configured and verified.

OpenRouter daily counters use UTC days. Midnight UTC is 7 p.m. Chicago / 5 p.m. Seattle while daylight saving time applies, then 6 p.m. / 4 p.m. during standard time. An earlier chat answer gave the standard-time conversion for October 31; that conversion was one hour early.
