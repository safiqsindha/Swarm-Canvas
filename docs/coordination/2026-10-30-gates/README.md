# Two-agent development gates

Both two-round checks use real isolated SwarmChat channels, the pinned free NVIDIA model, temperature 0, response schema and at most eight HTTP attempts each. Each check made four successful calls, each reporting $0. They use assigned ownership (slot-0 A-L, slot-1 M-X), not autonomous negotiation.

The message-only check returned four string messages and both correct acknowledgements. The combined check returned four string messages, both correct acknowledgements and the requested paint in all four responses. In the combined check paint actions were inspected in the responses, not applied to a canvas. Repeat painting of A1/M1 was requested, so this is not a measure of coverage or painting performance. Data contain prompts, outputs and call metadata, not native server credentials. Results are one run per gate and do not establish reliability at scale or a causal effect of communication.

These checks differ from the earlier unstructured diagnostic in schema, task and prompting, so no single change can be identified as the cause of improvement. Next evaluate the integrated harness with an actual canvas, multiple seeds, gates defined in advance, and free-only request caps. Avoid treating interventions that require communication as comparable to the earlier spontaneous communication condition.

To reproduce with an OpenRouter key in the environment, run from repository root:

```
PYTHONPATH=. python docs/coordination/2026-10-30-gates/reproduce-schema.py
PYTHONPATH=. python docs/coordination/2026-10-30-gates/reproduce-paint.py
```

Integrated follow-up: two rounds, four agents, actual canvas and native SwarmChat, fixed ownership, explicit messaging instructions, temperature 0.2. The optional-fields schema run returned only paints in all eight calls, with zero messages. A separate run requiring messages, acks, and paints in the schema generated eight applied messages, 16 applied acknowledgments and 64 applied paints, all eight calls reporting $0. The two runs are sequential single-seed development observations; the requirement is a behavioral intervention, and the run is not a causal comparison. The traces contain actual model-visible messages and responses. Each reproduction script sets the corresponding schema in-process; it does not change the benchmark defaults. Source code was the working tree based on PR commit 7df5f78 plus the message type validation fix from 11ef98d; git_commit recorded in the manifest is a local reconstruction and is not the GitHub source commit.

A second required-fields run, seed 2, also produced eight applied messages, 16 applied acknowledgments and 64 applied paints, from eight calls with $0 reported cost. Only two seeds and two rounds each have been tested. Acknowledgments are harness-accepted read receipts; this count does not establish that each message was substantively understood.
