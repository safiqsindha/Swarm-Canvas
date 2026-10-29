# Swarm Canvas

Four painters share a 24×16 grid for 30 rounds. The harness compares what they can say to each other:

| Condition | Channel | Config |
| --- | --- | --- |
| C0 | none, solo prompt | `configs/c0_baseline.yaml` |
| C1 | none, shared grid | `configs/c1_nochat.yaml` |
| C2a | numbered doc log | `configs/c2a_doc.yaml` |
| C2b | SwarmChat `#canvas` | `configs/c2b_swarmchat.yaml` |

Shipped configs use `agents.type: random`, so a dry run makes no model calls. Same seed, same canvas.

## Run

```bash
python cli.py run configs/c1_nochat.yaml --seed 1
python cli.py score runs/c1_s1
python cli.py judge runs/c1_s1
pytest
```

Dependencies: `openpyxl`, `pillow`, `imageio`, `pyyaml`, `httpx`, `pytest`.

Flip `agents.type` to `llm` when you want a live model. Every model call goes through `swarm_canvas/models.py` `call_model()` (`anthropic`, `openrouter`, or `openai_compatible`). Keys stay in the environment (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`). Prompts live in `prompts/`. The scoring plate is read only by `swarm_canvas/score.py`.

An invalid action is logged and dropped. A reply that is not JSON gets one repair prompt, then that painter passes the round.

C2b mirrors notes to `comms.server_url` when it is set, using `configs/swarmchat_tokens.example.yaml`. With an empty URL the local channel log still enforces the cap.
