# Exploratory findings: October 31, 2026

These probes used native local SwarmChat and nvidia/nemotron-3.5-super-vl:free through OpenRouter. All were development observations, not preregistered causal estimates. Reference images were text-encoded grids. No vision image was sent to a model.

Seeds control harness shuffles, not model randomness or provider behavior. Most follow-up conditions used seed 11 once. Runs occurred at different times and generated their own preview descriptions. Reported model costs were zero; request and token usage still matter.

## Open-ended creation and interface information

Four agents painted for six rounds in each seed from a plain-text boat goal, without a reference, territories, suggested paints, required messages, or required acknowledgements.

| Seed | Original painted cells | Original same-color repaints / paints | Legend + feedback painted cells | Legend + feedback same-color repaints / paints |
| --- | ---: | ---: | ---: | ---: |
| 11 | 33 | 130 / 178 | 56 | 98 / 178 |
| 12 | 55 | 137 / 192 | 37 | 108 / 170 |
| 13 | 32 | 152 / 192 | 46 | 102 / 182 |

Original runs made 73 HTTP attempts; later runs made 72. Over-budget proposals rose from 8 to 27. Both information changes were enabled together, so their separate effects cannot be identified.

Replay found 365 of the original 419 same-color repaints targeted cells already showing that color at round start. One agent painted J8 through Q8 in S on all six rounds. Repeated catalog requests continued after the shared supply was exhausted.

[Original evidence](evidence/archives/swarm_pilot_evidence.zip) · [Interface evidence](evidence/archives/swarm_interface_evidence.zip)

## Reference access and leadership

| Six-round condition | Painted cells | Exact reference matches |
| --- | ---: | ---: |
| One preparation preview, four painters | 95 | 71 / 384 |
| Leader-only reference each round, three painters | 27 | 15 / 384 |

Together these made 52 HTTP attempts. The leader coordinated while its paints and color requests were suppressed. Followers waited for instructions or catalog colors; the leader asked for colors the reference did not require. Painter count, information access, preparation calls, and timing differed. Neither group could fill 384 cells within six rounds at its allowed paint rate. This does not establish a leadership effect.

[Images](evidence/archives/swarm_reference_evidence.zip) · [Evidence](evidence/archives/swarm_reference_evidence.zip)

## Duration and retained memory

| Condition | Painted cells | Exact matches | Same-color repaints / paints |
| --- | ---: | ---: | ---: |
| One-time preview, 24 rounds | 281 | 187 / 384 | 457 / 758 |
| One-time preview, 48 rounds | 384 | 207 / 384 | 945 / 1,372 |
| Original preview notes retained each round, 24 rounds | 175 | 149 / 384 | 202 / 379 |

The duration pair made 303 HTTP attempts. The 48-round group painted every cell S (light blue) by round 44. Its 207 matches equal the reference's 207 S cells.

Initial notes described the boat and water. Rewritten scratchpads after round one increasingly focused on filling blue rows and lost much of that description. Later messages coordinated blue filling. This is consistent with memory loss and reinforcement of a local plan, but does not isolate either cause.

With original notes retained in all 96 painting-round inputs, a partial boat, mast, sail, water, and sun survived. Agents announced completion around round 12; later agents cited completion messages and stopped despite blank cells. The run made 100 requests including previews. Visual structure appeared more boat-like to the inspecting assistant, but exact matching was lower and there was no blinded human rating.

[Duration archive](evidence/archives/swarm_duration_evidence.zip) · [Duration evidence](evidence/archives/swarm_duration_evidence.zip) · [Memory archive](evidence/archives/swarm_memory_evidence.zip) · [Memory evidence](evidence/archives/swarm_memory_evidence.zip)

## Optional looks and completion estimates

Agents retained preview notes and could estimate additional team rounds. A turn-costing look suppressed current-turn actions and delivered the reference next turn. A free look used another model call and allowed action in the same round.

| Condition | Rounds | Looks | Painted cells | Exact matches | HTTP attempts |
| --- | ---: | ---: | ---: | ---: | ---: |
| Turn-costing look, completed attempt | 24 | 0 | 238 | 190 / 384 | 103 |
| Free look | 6 | 1 | 94 | 81 / 384 | 29 |

The initial turn-costing attempt aborted during round three after failed JSON repair. It used 17 requests and completed two rounds. A fresh attempt continued through failed turns and recorded three parsing failures. Its initial estimates were 23, 10, 20, and 5 additional rounds; all four estimated zero at round 24 although the reference remained incomplete. Both attempts are retained.

The free-look run was shortened because only 112 free requests remained before launch. All four initially estimated five additional rounds. At the end, one estimated zero, one estimated two, and two provided no valid estimate. Slot-0 selected a free look in round one and painted that round. No API or parsing failures were recorded. One short run does not establish an effect of removing look cost.

[Turn-costing archive](evidence/archives/swarm_peek_evidence.zip) · [Both turn-costing attempts](evidence/archives/swarm_peek_evidence.zip) · [Free-look archive](evidence/archives/swarm_free_peek_evidence.zip) · [Free-look evidence](evidence/archives/swarm_free_peek_evidence.zip)

## Conclusions and remaining questions

The harness captures native communication, agent notes, accepted/rejected actions, request usage, and frames. Narrow clean-boundary recovery was exercised with random agents and a live free-model run. Custom probes and partial rounds are not automatically resumable.

Reliable goal completion, independent completion checking, and useful voluntary inspection remain unestablished. The matched three-seed, 24-round look comparison is prepared and waiting for sufficient quota; it has no results yet. No mixed-model or larger-canvas result is claimed. Langfuse delivery was not independently verified for these probes.

Evidence archives are linked from this repository; their frames can be rendered with the project tools. Archives exclude native SwarmChat databases and recovery credentials. Some historical manifests identify a reconstructed local checkout; use source fingerprints and archived scripts for provenance rather than assuming those checkout SHAs identify the published experiment revision.
