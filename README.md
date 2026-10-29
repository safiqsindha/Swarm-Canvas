<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/banner-dark.svg">
    <img src="assets/banner-light.svg" alt="Swarm Canvas" width="100%">
  </picture>
</p>

# Swarm Canvas

![Tests](https://img.shields.io/badge/tests-17%20passing-22c55e?style=flat-square)

<p align="center">
  <img src="docs/sitting.gif" width="720" alt="Seed 1, condition C1. Thirty rounds. Four painters, a shared grid, no channel, no model calls.">
  <br>
  <sub><b>Seed 1, condition C1.</b> Random painters, no channel, no model calls. Same seed, same canvas.</sub>
</p>

Four painters share a 24×16 grid for 30 rounds. The harness changes only the channel between them. Shipped configs use `agents.type: random`, so a dry run makes no model calls. The film above is `configs/c1_nochat.yaml` at seed 1. Run it again and `runs/c1_s1/timelapse.gif` is the same film, unframed.

## Conditions

| Condition | Channel | Config |
| --- | --- | --- |
| C0 | none, solo prompt | `configs/c0_baseline.yaml` |
| C1 | none, shared grid | `configs/c1_nochat.yaml` |
| C2a | numbered doc log | `configs/c2a_doc.yaml` |
| C2b | SwarmChat `#canvas` | `configs/c2b_swarmchat.yaml` |

## What the harness enforces

- An invalid action is logged and dropped. The round continues.
- A reply that is not JSON gets one repair prompt. If it is still not JSON, that painter passes the round.
- The scoring plate is read only by `swarm_canvas/score.py`. No painter is shown it.
- A catalog color arrives one round late, and only for the painter who asked.
- C2b mirrors notes to `comms.server_url` when it is set, using `configs/swarmchat_tokens.example.yaml`. With an empty URL the local channel log still enforces the cap.

## Repository

```
cli.py
configs/          one YAML per condition, plus the SwarmChat token example
prompts/          system, turn, comms blocks, repair, and the judge prompt
swarm_canvas/     canvas, supplier, comms, agents, validation, render, score, judge
targets/          the scoring plate, sun_boat.txt
tests/            pytest suite, no API keys
docs/sitting.gif  the seed-1 C1 film shown above
```

## Reproducing

```bash
pip install -r requirements.txt
python cli.py run configs/c1_nochat.yaml --seed 1
python cli.py score runs/c1_s1
python cli.py judge runs/c1_s1
python -m pytest -q
```

Flip `agents.type` to `llm` for a live model. Every model call goes through `swarm_canvas/models.py` `call_model()` (`anthropic`, `openrouter`, or `openai_compatible`). Keys stay in the environment (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`). Prompts live in `prompts/`.
