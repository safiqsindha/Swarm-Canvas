# OpenRouter development smoke test, October 29, 2026

These are bounded integration diagnostics, not research evidence or a model-quality comparison. Only explicitly free OpenRouter endpoints were requested, with zero price ceilings and no paid-provider fallback. Credentials and the native SwarmChat server database are excluded.

| Setup | Rounds | Agent turns | Successful API calls, including JSON repair | Parse failures | Paint actions | Distinct painted cells | Chat messages | Reported inference cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Provider defaults | 3 | 12 | 24 | 12 | 0 | 0 | 0 | $0 |
| Optional reasoning disabled | 2 | 8 | 8 | 0 | 64 | 24 | 0 | $0 |

Both runs requested and reported `nvidia/nemotron-3.5-super-vl:free` from provider `Nvidia`, using native local SwarmChat, seed 1, the visible 24×16 target, and four painters with eight paint actions each per round. Both used temperature 0.2 and a 1,600-token completion limit. The reasoning-disabled run had no API errors, invalid actions, or over-budget actions. All 24 painted cells matched the target, for 6.25% whole-grid accuracy; the short horizon allowed at most 64 distinct cells.

The default-setting run returned empty/unparseable actions at exactly 1,600 completion tokens per call, including repairs. This was consistent with the provider consuming the completion budget before returning visible actions. That run did not yet log finish reasons or reported reasoning tokens, so the artifact cannot directly establish their values. Explicit `reasoning.enabled: false` and additional response diagnostics were then added. The subsequent full-observation preflight reported `finish_reason: stop`, zero reasoning tokens, and visible content; all eight integrated calls also returned usable actions. The differing horizons and configuration changes mean this is not a controlled causal comparison.

The clean run still showed substantial duplicated work: 40 of 64 paint actions repeated an existing color, and there were 32 cross-agent overwrites. Agents sent no chat messages or explicit acknowledgments. It verifies a working free-model action path, not successful cooperation or a benefit from communication. Native message delivery and receipts were verified separately by the scripted `swarmchat-check` integration test.

Two successful NVIDIA preflights, outside these runs, also reported $0: a simple JSON request, then a full first-turn observation with optional reasoning disabled. Three Google free-endpoint preflight requests were rejected with HTTP 429; the inspected error identified the upstream provider's shared pool. Those rejected requests were not trial data.

## Reproduce the bounded clean configuration

Install requirements, supply `OPENROUTER_API_KEY` through the environment, then:

```bash
python cli.py run configs/free_smoke_nemotron.yaml
```

This starts a real isolated SwarmChat server automatically. Free endpoint availability and provider behavior can change; a seed fixes harness ordering, not model responses.

The two subdirectories retain manifests, scores, events, targets, and round snapshots. Each `provenance.json` identifies the published source snapshot and hashes the retained artifacts. No painter prompts included a credential. The manifest's temporary local checkout HEAD predates working-tree changes; use the explicitly verified published snapshot in provenance when interpreting these diagnostics.

The next useful check is a longer, paired C1/C2b development run with the same pinned free model and fixed settings, to measure duplicate work and whether communication is used. This smoke test does not justify a confirmatory experiment or changing the primary outcome after seeing results.
