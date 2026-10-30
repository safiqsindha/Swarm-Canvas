# Larger pilot: launch plan

Status: **blocked pending readiness**. This is a development pilot, not a confirmatory experiment. SwarmChat is mandatory for the communication condition; inference is limited to free OpenRouter models. Earlier spontaneous conditions and the assisted condition answer different questions.

## Objective and intervention

First establish that the scaffolded four-agent system can exchange peer messages and make canvas progress over multiple seeds. The assisted condition gives each painter candidate target-colored cells and the latest peer line from its visible snapshot. Fixed territory assignment and these hints are part of the treatment; success cannot establish autonomous coordination or the causal effect of SwarmChat.

## Gate before scaling

1. Freeze the code, prompts, target, model slug and model parameters; record the real Git commit and any working-tree changes. Confirm the specific model remains a free endpoint with zero input/output pricing and enough remaining free request quota. Never relax the free-only price guard.
2. On that frozen version, run the assisted readiness check with seeds 4, 5 and 6, four rounds each. Each run must pass every existing gate: valid action fields, a message and an in-territory paint per agent-turn, at least one applied acknowledgment of an exposed peer note when available, no model/parse/agent errors, and zero reported cost. Missing cost or model metadata is not proof of zero cost. Archive all attempts, including failures and incomplete attempts. Do not cherry-pick or silently rerun failed seeds as successes.
3. Independently audit at least one saved trace and actual native SwarmChat events per seed against the gate, confirm no credentials or private SwarmChat server state are archived, and inspect applied paints and target/frame hashes. Verify every run used the pinned model and the configured schema; a provider schema fallback makes the attempt invalid.
4. Separately assess task utility before launch: report target accuracy, coverage, redundant paints, failures and acknowledgments by seed and round. A communication-gate pass is not proof that the model understands notes or performs the task well. Compare progress trajectories and document a minimum useful task-performance criterion before any confirmatory study.

Commands from repository root, with the OpenRouter API key supplied securely in the execution environment:

```bash
python -m swarm_canvas.readiness_check --seed 4 --rounds 4 --assist
python -m swarm_canvas.readiness_check --seed 5 --rounds 4 --assist
python -m swarm_canvas.readiness_check --seed 6 --rounds 4 --assist
```

Each run permits at most 32 inference HTTP attempts, 96 across the three, plus any separately documented preflight requests. Successful main calls total 48; retries and JSON repair consume the attempt cap. Pacing is 3.5 seconds globally inside each run. These commands do not themselves check quota in advance; perform the documented preflight before starting. The existing readiness checker limits runs to four rounds and must be extended and tested before attempting a longer pilot.

## Proposed larger pilot, after the gate

Use three new seeds 7, 8 and 9, four painters, the fixed target and 12 rounds, with the same explicitly assisted scaffold. This is 144 primary model calls and a proposed ceiling of 288 total HTTP attempts including retries and repairs. Apply a single shared request budget across the pilot, stop on transport/model failures, archive failed and incomplete runs, and record all attempts. Check daily quota against the whole ceiling before launching, then schedule across quota windows if necessary. A separate pilot runner must enforce these requirements and the gate; the present commands do not implement this 12-round pilot.

No comparison with no-chat or spontaneous-chat runs is valid as a causal communication estimate unless all other scaffold, model, budget, task, prompt and timing differences are matched. For a later comparison, define matched arms and order, preserve per-seed pairs, predeclare exclusions and outcomes, and retain all outcomes. Decide whether fixed territories and deterministic paint suggestions are experimental aids or potential confounders before interpreting results.

## Known blockers

The last assisted seed-3, four-round run failed the peer-acknowledgment gate twice despite improved coverage (108 distinct correct cells from 128 paints). The previous unassisted scaffold also failed. Resolve those failures and demonstrate replication before authorizing a larger run. Langfuse live delivery is not independently verified; local run traces are available.
