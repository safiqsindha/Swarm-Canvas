# Assisted 12-round pilot

This is a development pilot, not a causal or confirmatory comparison. Four agents used native SwarmChat, fixed territories, deterministic target-derived candidate paints, and a response schema constraining acknowledgment IDs to exposed peer messages. The model was `nvidia/nemotron-3.5-super-vl:free`; temperature 0.2, reasoning disabled. The source was the merged launcher version at main commit `f3e5a7cbca99742dc16e8146fcbb00645b5244ba`, with per-file SHA-256 recorded in the original pilot manifest. Manifest git_commit fields report a local reconstruction and should not be mistaken for the GitHub commit.

| Seed | Completed gate | Correct cells / 384 | Accuracy | Paint actions | Redundant paints | HTTP attempts |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 7 | Pass | 270 | 70.31% | 384 | 108 | 58 |
| 8 | Pass | 324 | 84.38% | 384 | 44 | 51 |
| 9 | **Fail** | 269 | 70.05% | 384 | 74 | 48 |

Seed 9 failed because slot-1 painted M8 and N8 outside its assigned G-L territory during round 12. The full run was scored and retained, but it did not satisfy the predeclared gate. Each completed run reported $0 total model cost; ten retries occurred in seed 7 and three in completed seed 8. Scores and gates were recomputed from saved events, actions and exact final canvas frames.

The execution environment restarted during the first seed-8 attempt, after nine complete round snapshots and during round 10. The original process could not be resumed. That partial attempt is retained and excluded from completed-seed metrics. Its trace shows 40 generation starts, including two without corresponding ends. These starts precede budget acquisition, so 98 (58 from seed 7 plus 40 interrupted starts) is a conservative upper bound on original-attempt inference requests, not a measured exact count. The replacement seed-8 and seed-9 runs used a new shared cap of 190; they consumed 99 attempts. Thus at most 197 of the original 288 allowed attempts are accounted for, including the interruption. The resume code, source-fingerprint check, quota preflight and both manifests are preserved. No claim is made about completed work in the interrupted spans.

`evidence.tar.gz` contains prompts, local traces, event logs, canvas snapshots, target, action and result summaries, and manifests, including the interrupted run. It excludes native SwarmChat server state and credentials. The SHA-256 is `95308981f83c558b4d1e76262192ad90f6db684370efea6b3ba96af276f43ab1`. Local traces include actual appended instructions and suggestions; base prompt files do not. Model inputs and outputs are synthetic task data. Langfuse delivery has not been verified.

The observed failure requires investigation before a larger study; deterministic hints and peer-ID restrictions are part of the condition, and the study lacks an unassisted or no-chat control.
