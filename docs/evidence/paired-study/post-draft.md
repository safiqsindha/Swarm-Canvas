# Draft post and thread

Status: draft for review. The repository and evidence archive may not yet be publicly accessible. Do not claim a published public dataset until access has been checked.

## Opening post

We asked four AI agents to paint a boat together.

In one run, the agents were told 251 of 384 cells were still blank. In the final round, all four said the grid looked complete and repainted cells that already had the requested color.

Here's what we learned from watching them coordinate. 🧵

Suggested media: `seed13-final-round.gif`. This replays the exact run described in the opening post. The separate `seed13-claim.gif` shows a different run, baseline seed 13.

## Thread

1. We ran six exploratory 24-round experiments: four agents using the same DeepSeek model, a 24 × 16 canvas, and SwarmChat for messages. Each agent saw a reference once and could keep notes. This was an assisted reconstruction task.

2. Across the six runs, 2,734 of 4,558 applied paints (60.0%) repeated the color already in a cell at application time. That includes overlap between agents' actions within a round. Some repetition may have been intentional.

3. In one reminder-enabled run, the round-24 prompt reported 251 blank cells. All 32 proposed paints already matched their cells at the start of that round. All four agents posted messages saying the grid appeared or should be complete. The canvas finished with 251 blanks.

4. We tested a baseline and an enabled reminder across three seeds. The reminder never fired, so we can't conclude anything about its effect. One prior attempt was interrupted and replaced. One model and six completed runs are too small to generalize broadly.

5. All 576 painting calls from the completed runs were matched between the local records and a Langfuse export. The six runs' painting calls cost about $0.076, excluding previews and the interrupted attempt.

6. The next question: what changes when we vary the number and mix of agents, and remove assistance? We need controlled runs and independent scene-quality measures to find out.

Suggested links: repository and paired-study findings once the intended audience has access. Do not post raw Langfuse exports or API keys.
