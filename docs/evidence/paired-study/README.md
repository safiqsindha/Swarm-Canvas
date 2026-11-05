# Six-run paired study: exploratory results

Four agents painted a 24 × 16 canvas for 24 rounds per run. All agents used `deepseek/deepseek-v4.1-flash-1017` through OpenRouter and communicated through native SwarmChat. They received a one-time reference preview and retained notes. The task was reference reconstruction, not an unassisted test of a plain-text description. Each seed had a baseline and a condition in which an automatic reminder could fire following a detected premature completion claim.

![Six runs, round by round](six-run-comparison.gif)

| Seed | Condition | Painted / 384 | Exact matches / 384 | Foreground matches / 51 |
| --- | --- | ---: | ---: | ---: |
| 11 | Baseline | 323 | 272 | 13 |
| 11 | Reminder enabled | 345 | 295 | 28 |
| 12 | Baseline | 359 | 309 | 24 |
| 12 | Reminder enabled | 241 | 223 | 41 |
| 13 | Baseline | 167 | 130 | 36 |
| 13 | Reminder enabled | 133 | 106 | 33 |

The foreground measure counts correctly matched target cells outside the target's dominant background; it is not a human rating of whether a boat looks good. Pixel accuracy is also sensitive to the large background area. The reminder fired **zero times** in all three reminder-enabled runs. The arm comparisons therefore do not establish a reminder effect. The completion-claim detector was a conservative lexical trigger and missed at least one obvious claim; its counts are not a reliable estimate of prevalence.

![Seed 13 claim replay](seed13-claim.gif)

In the replacement baseline run for seed 13, `slot-0` wrote “All 384 cells complete” in round 12. Its start-of-round view was the end-of-round-11 canvas, which had 220 blank cells. The replay pauses on that snapshot when displaying the message. The source message is in the saved `doc_log.txt`; the canvas is `canvas/round_11.json`.

Six runs completed. An earlier seed-13 baseline attempt was interrupted and replaced; its three reserved requests without recorded responses remain unresolved. Local audits for the six completed runs passed; delivery to an external tracing destination was not verified. The six-run batch and the interrupted attempt, logs, frames, accounting and source snapshot are preserved in the [evidence archive](https://chatgpt.com/library?file_id=libfile_868073de549c8191bf256fea68b34f44&account_id=personal); access may be restricted. The archive omits SwarmChat private databases and tokens. The recorded source snapshot was verified against the study code from GitHub PR #15; the synthetic local commit identifier in the manifest is not a GitHub commit.

To regenerate the GIFs from an extracted evidence archive, install Pillow and run:

```sh
python docs/evidence/paired-study/render_gifs.py /path/to/batch
```

The script reads the batch manifest and its six completed run directories, renders all 24 saved snapshots using the harness palette, and labels the end-of-round-11 snapshot with the round-12 quote. The visualizations are replays, not model-generated images.
