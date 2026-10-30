# Revised four-round readiness test, seed 3

Source code PR commit `43564f4a071c31959b44ac52ba06ed1acd791d7b` (the manifest git_commit is a local reconstruction). This run modifies the earlier seed-3 scaffold by explicitly instructing peer-only acknowledgments and avoiding already-correct cells. Four agents, native SwarmChat, required communication schema, same free NVIDIA model and target, fixed territories.

The gate failed: two agent-turns did not acknowledge an exposed peer note. Sixteen valid calls, 16 messages, 33 applied acknowledgments and 128 paints, only 32 unique cells, 96 redundant, 28/384 target matches, reported $0 and no retries. Earlier run: four failures, 48 unique cells, 42/384 matches. These sequential single-seed observations do not isolate the effect of instructions or establish reliability. See local traces for exact model input and output.
