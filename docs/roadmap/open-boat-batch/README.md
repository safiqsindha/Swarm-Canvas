# Open-ended boat development batch: seeds 12 and 13

A two-seed, six-round check of the open-ended condition, using four agents and native SwarmChat. Agents received the text goal to paint a recognizable boat. All assistance switches were off. There was no reference image or target-derived scoring, assigned territory, suggested paint, required message, required acknowledgment, or JSON response schema. The 24×16 canvas, palette, turn model, 8-paint limit, 2-message limit and supplier rules remained active. Both runs used `nvidia/nemotron-3.5-super-vl:free`, temperature 0.2, reasoning disabled. They are exploratory observations, not controlled comparisons or a validation of boat quality.

| Seed | Applied paints | Final painted cells | Redundant paints | Overwrites | Voluntary messages | Accepted acks | Supplier denials |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12 | 160 | 69 | 88 | 61 | 24 | 53 | 26 |
| 13 | 192 | 42 | 149 | 58 | 22 | 45 | 38 |

Both completed six rounds with 24 successful model calls, zero retries and no API, parsing or agent errors. Both reported $0. The batch used 48 of a 96-attempt cap. Final scores and frame hashes were independently recomputed. All agents could choose to communicate; counts do not establish comprehension or coordination. Messages included several separate hull and sail plans with overlap. Seed 12's supplier requests included requests describing red as water; seed 13 messages described O differently as orange, ocean and brown. These are observations of what messages said, not evidence of the agents' intent or shared understanding. Seed 12 applied fewer than the maximum possible paints; that is not itself a failure.

Source commit `11bfc2e0a50b92831e1e837ad08af08ab41a0bbb`; the batch manifest records source SHA-256 fingerprints. Git commit values in the run manifests are from a local reconstruction, not the GitHub source commit. The evidence archive contains batch and run manifests, scores, raw local traces, prompts, action events and canvas frames. It excludes native server state and credentials. Archive SHA-256: `0b859161e542c26bdba04ba1879400802f71cb5d0bd87faa4780bc985f14e408`. Images are in `seed-12.png` and `seed-13.png`.

These two runs do not establish a reliable distribution, an effect of communication, or a generalizable boat recognizability score. Human blind ratings and a matched comparison are future work. Longer runs, real interruption-recovery testing and grid/model-count scaling remain open.
