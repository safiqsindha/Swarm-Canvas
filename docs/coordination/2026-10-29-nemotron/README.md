# Explicit coordination diagnostic

This is separate from the earlier spontaneous-chat pair. Same fixed free NVIDIA endpoint, seed 1, four agents, native SwarmChat, temperature 0.2, disabled optional reasoning, and 1,600 completion tokens. The four-round intervention explicitly required a message on each turn, column-ownership proposals, reading and acknowledging peer notes when available, and a scratchpad. These additional instructions were appended to every actual observation and are saved verbatim.

**Observed:** 16 valid model/API calls, $0 reported cost, zero parsing/API errors, 128 paint actions, only 8 distinct painted cells, and 120 redundant actions. Target accuracy was 8/384 (2.08%). All 16 returned action objects contained only `paints`. There were **zero messages, zero acknowledgments, and no saved ownership plans**. No peer messages existed to acknowledge. This failed the explicit communication-adherence gate, despite valid JSON.

Two additional fixed probes requested exactly `{"messages":["coordination-check"]}`. Both returned the requested message: once with the painter action schema and once without it. Both reported $0, normal completion and zero reasoning tokens. The schema therefore permits messages, and the endpoint can produce message JSON on a simple request. This does not rule out every harness interaction, but it weakens schema suppression as the explanation for the full-task failure.

This is a competence diagnostic, not evidence that SwarmChat helps or hurts. The free-model setup is not yet following the combined canvas/coordination instructions reliably. Do not scale its results into a communication benchmark claim. The next useful diagnostic is a simpler multi-turn message/ownership task with an explicit adherence gate, or a different verified-free model. Keep all such changes separate from the completed pair.

The model cost reported across this diagnostic and both probes was $0. Free-only endpoint and zero-price guards remained active. No API keys, environment dumps or native server credentials are included.

Reproduction, with `OPENROUTER_API_KEY` supplied in the environment:

```bash
python -c 'from swarm_canvas.coordination_check import run_coordination_check; print(run_coordination_check())'
python -c 'from swarm_canvas.coordination_check import probe_action_schema; print(probe_action_schema())'
```

Saved base prompt files plus `diagnostic_instruction.txt` reconstruct each diagnostic user observation. `diagnostic_actions.json` retains parsed model actions. `schema_probe.json` retains both probe replies and provider usage metadata. These are single-model development observations without replication or a causal performance comparison.
