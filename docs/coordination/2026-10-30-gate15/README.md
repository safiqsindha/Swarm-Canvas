# 15-round required-schema gate, not started

This is not the spontaneous C1 versus C2b pair in `docs/paired/2026-10-29-nemotron`. That pair is already complete and was not rerun. Acknowledgments in the earlier required-schema runs are read receipts, not evidence that a painter understood a note.

Planned here: seeds 7, 8, and 9, 15 rounds, four painters, visible `sun_boat` target, fixed columns, `nvidia/nemotron-3.5-super-vl:free`, reasoning disabled, schema requiring messages, acks, and paints. No assist hints. A failed seed stops the rest. Not research evidence.

Seed 7, round 1, made four calls. All four returned `ReadTimeout` after about 180 seconds (the 60-second client timeout, retried). No paints, messages, or acks were applied. Seeds 8 and 9 were not started. A separate one-word request to the same model also timed out at 90 seconds, so this attempt was not retried and is not a pass.

`seed7-events.jsonl` is the aborted attempt. The free-request quota before the attempt had 606 requests remaining. Reported cost is not available because no call completed.
