<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/banner-dark.svg">
    <img src="assets/banner-light.svg" alt="Swarm Canvas" width="100%">
  </picture>
</p>

# Swarm Canvas

![Tests](https://github.com/safiqsindha/Swarm-Canvas/actions/workflows/tests.yml/badge.svg)

A small environment for testing how communication changes agents' ability to produce a shared artifact. Painters act on the same 24×16 canvas in simultaneous rounds. Their validated actions are applied in seeded, shuffled order; later writes win.

**SwarmChat is a required experimental condition. Development model calls are restricted in code to OpenRouter free models.** The shipped configurations use random agents and make no model calls.

## Conditions and objective

| Condition | Painters | Paint allowance per painter per round | Channel |
| --- | --- | --- | --- |
| C0 | 1 | 32 | None |
| C1 | 4 | 8 | None |
| C2a | 4 | 8 | Shared numbered document log |
| C2b | 4 | 8 | SwarmChat adapter |

Every condition has the same maximum of 32 paint actions per round. Compute is **not** matched: the group makes more calls and processes more context. Record tokens and reported cost separately.

The four condition configs use **target reconstruction**. Every painter sees the target color grid each turn. The primary outcome is the fraction of cells matching that target. `configs/free_creation.yaml` preserves open-ended creation; it has no hidden target score and requires separate blind quality evaluation before research use.

Three targets are included: `sun_boat`, `stripes`, and `checker`. They use only base-palette colors. The delayed, private supplier remains available, but these tasks do not require catalog colors. They therefore do not test the value of resource negotiation.

## Run locally without model calls

```bash
pip install -r requirements.txt
python -m pytest -q
python cli.py run configs/c1_nochat.yaml --seed 1
```

The command prints the actual run directory, such as `runs/c1_s1_<attempt-id>`. Use that directory for `score`, `judge`, and `export`:

```bash
python cli.py score runs/<printed-run-directory>
python cli.py judge runs/<printed-run-directory>
python cli.py export runs/<printed-run-directory> replay.json
```

Each attempt gets a new directory. A manifest records its completion state, exact final frame and canvas hash, saved target and target hash, effective model settings, immutable slot IDs, prompt hashes, supplier settings, and token totals. Failed attempts remain marked failed and cannot be scored. Names are display labels; simultaneous duplicate renames are rejected.

The event log separates API failures, malformed JSON, invalid actions, and deliberate passes. JSON gets one repair attempt; API errors do not trigger JSON repair. Read acknowledgments are accepted only for lines shown to that agent. Prompt exposure is not recorded as a native SwarmChat read receipt.

Metrics include coverage, target accuracy, per-round accuracy, correct cells destroyed, redundant paints, the first round reaching 90% accuracy with cumulative paints/tokens, and reliability counts. Token/cost data include repair calls. Missing provider cost metadata is unknown, not assumed free based on a successful response. Random smoke tests are not collaboration evidence.

## OpenRouter free-only development policy

To use a live model, copy a config, set `agents.type: llm`, and set `model.name` to a currently available, explicit OpenRouter model ID ending in `:free`. Supply `OPENROUTER_API_KEY` through the environment. Use the same model and settings for all conditions.

The shared model-call layer blocks paid model IDs and other providers before sending HTTP requests, including judge requests. Every OpenRouter request includes zero prompt/completion/request price ceilings and disables provider fallback. There is no paid-model override in this development version. Supporting paid runs requires a separate, explicitly authorized code change.

`openrouter/free` is allowed for standalone smoke checks, but it selects models dynamically, so the pilot runner rejects it. Actual served model/provider IDs, response IDs, reported usage/cost, and call timing are recorded. Free-model availability and limits may interrupt a run; failed calls are flagged rather than interpreted as agent inactivity. No automatic fallback to a paid model occurs.

Official references: [free model router](https://openrouter.ai/docs/guides/routing/routers/free-router), [provider price ceilings and fallback controls](https://openrouter.ai/docs/guides/routing/provider-selection).

## SwarmChat integration status

C2b remains part of every pilot. Its current adapter POSTs accepted messages and acknowledgments to `{server_url}/channels/canvas/messages`, using a token per permanent slot. Existing token files keyed by starting handle also work; display-name changes do not change credentials. `configs/swarmchat_tokens.example.yaml` contains placeholders only.

**The existing adapter is an outbound HTTP mirror.** Agent inboxes still come from the harness log. No native remote inbox, addressed delivery, or server read-receipt API has been verified. C2a/C2b can currently test framing differences and delivery reliability; they cannot establish the benefit of distinct native channel capabilities. A working POST against a mock server does not verify compatibility with a deployed SwarmChat service.

Live C2b runs require `comms.server_url`; remote delivery failure aborts the attempt and marks it failed. Offline random/scripted fixtures may use the local mirror and are labeled development-only. Before real experiments, verify the actual SwarmChat service's authentication, channel isolation, write/read contracts, and receipt behavior, then implement and test the native adapter against those contracts. Never describe local fallback as a completed live SwarmChat trial.

## Matched pilot

```bash
# 3 targets × 5 seeds × 4 conditions = 60 offline smoke runs
python cli.py pilot --output-dir runs

# Optional development-only free-model check, once the SwarmChat endpoint is configured
python cli.py pilot --live --model '<provider>/<model>:free' \
  --swarmchat-url '<server-url>' --token-file '<local-token-file>' \
  --repeats 1 --rounds 2 --output-dir runs
```

The live command preflights all conditions before the first model call. It requires one explicit free model and a SwarmChat endpoint. Pilot manifests are updated after each completed run and remain marked failed if execution aborts. Development pilots are always labeled `research_evidence: false`; completing them is not authorization for confirmatory runs.

Before research runs, assess ceiling/floor effects, choose a fixed task set and repetition count, preregister the primary comparison, and define how reliability failures and provider/model changes affect eligibility. Expanding a pilot after inspecting effects must not be presented as a preregistered confirmatory result.

## Historical demo

<p align="center"><img src="docs/sitting.gif" width="720" alt="Historical random-painter smoke test"></p>

This animation is the original seed-1 random-painter demo, not a live model result. The new manifest and identity formats differ from that historical run.
