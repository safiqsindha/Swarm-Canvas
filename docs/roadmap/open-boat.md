# Roadmap: open-ended shared boat creation

## Goal

Study what multiple model agents do when asked to make a recognizable boat together on a shared canvas. Let them decide whether to communicate, plan, assign roles or revise work. Preserve native SwarmChat, full message exposure and read receipts, and free-only OpenRouter inference during development. The exploratory question is what interactions and outcomes emerge; controlled comparisons come later.

## Remove scaffolding deliberately

1. **Open boat goal:** `configs/open_boat_dev.yaml`: no target plate, preassigned areas, suggested cells, required messages, acknowledgments or schema requiring coordination fields. The goal asks for a recognizable boat. Notes and scratchpads are available but optional. JSON is an interface contract, not a prescribed plan. The response format schema is omitted in this condition. This development configuration still has a fixed 24×16 board, four agents, a limited palette, 8 paints/agent/round and 2 short notes/agent/round. Those are environment constraints, not evidence of unrestricted interaction.
2. **Interaction study:** collect all prompts actually sent, raw model responses, validated and rejected actions, canvas frames, channel messages and read receipts. Analyze who proposes a plan, who responds, explicit agreements and conflicts, revision patterns, overwrites, independent work and silence. Distinguish messages produced by the model from server-generated events. Do not infer understanding from a read receipt.
3. **Fair comparisons:** after the open condition functions, predefine matched conditions varying one scaffold at a time (such as optional target or cell suggestions), using identical model settings, seeds, task and budgets. Scaffold removal is an intervention, not an estimate of SwarmChat's effect. To estimate communication impact, match all other conditions and vary the channel. Preserve all failed, interrupted and completed attempts and do not select only successful seeds.
4. **Scale:** remove fixed-size assumptions from grid, schema, render, scoring and tests together; parameterize agent count and per-slot model assignment; measure context growth, latency, provider limits, quotas and SwarmChat traffic at each step. First test 2, 4 and 8 agents, then increase grid sizes and model diversity. Define fixed per-agent versus fixed team budgets before comparing sizes. OpenRouter free-model availability can change; validate pricing and quota at runtime. Do not silently swap models or paid providers.

## Assess the open task

Do not score against the reconstruction target or silently treat cell coverage as boat quality. Predefine a human-readable rubric with separate scores for boat recognizability, coherent composition and completion, plus rater confidence and abstention. Blind raters to model, seed and condition; use independent ratings, report disagreement and retain images and rubric versions. Before making model-based judge claims, compare any free-only judge to human labels and report errors; a judge is not ground truth. Automated metrics such as painted-cell coverage, overwrite count, messages, ack events and cost describe behavior but do not prove boat quality or collaboration. Keep outcome metrics separate from process observations.

## First development check

Run a small, bounded single-condition smoke test before drawing conclusions; use the real SwarmChat transport and pinned free model. Record whether each agent completes turns, whether they use messages voluntarily, what emerges visually, and all failure and cost metadata. No intervention or forced messages may be added after observing an output. A single run is not a performance estimate. Review the resulting image and traces, then decide what to fix before a seeded comparison. Retain prompt, model, exact config, source fingerprint and evidence. A fresh readiness verification is required for the earlier assisted pilot launcher whenever its frozen source files change.
