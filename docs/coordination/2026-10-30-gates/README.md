# Two-agent development gates

Both two-round checks use real isolated SwarmChat channels, the pinned free NVIDIA model, temperature 0, response schema and at most eight HTTP attempts each. Each check made four successful calls, each reporting $0. They use assigned ownership (slot-0 A-L, slot-1 M-X), not autonomous negotiation.

The message-only check returned four string messages and both correct acknowledgements. The combined check returned four string messages, both correct acknowledgements and the requested paint in all four responses. In the combined check paint actions were inspected in the responses, not applied to a canvas. Repeat painting of A1/M1 was requested, so this is not a measure of coverage or painting performance. Data contain prompts, outputs and call metadata, not native server credentials. Results are one run per gate and do not establish reliability at scale or a causal effect of communication.

These checks differ from the earlier unstructured diagnostic in schema, task and prompting, so no single change can be identified as the cause of improvement. Next evaluate the integrated harness with an actual canvas, multiple seeds, gates defined in advance, and free-only request caps. Avoid treating interventions that require communication as comparable to the earlier spontaneous communication condition.

To reproduce with an OpenRouter key in the environment, run from repository root:

```
PYTHONPATH=. python docs/coordination/2026-10-30-gates/reproduce-schema.py
PYTHONPATH=. python docs/coordination/2026-10-30-gates/reproduce-paint.py
```
