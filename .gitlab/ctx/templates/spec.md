# Feature

One bounded capability per concept-named directory, not an entire multi-feature
epic/MVP. Inventory its purpose and ticket mappings in design.json first. Link
related capabilities; do not duplicate their scenario definitions or renumber IDs.

## Intent and observable success

## Preconditions

Include unbuilt infrastructure as explicit dependencies.

## Features and scenarios

Give each Given/When/Then scenario a stable ID and evidence mapping. Cover the
actual behavior and material risks, not speculative permutations. Multiple criteria
can share one lean test; do not create a test-count quota from the scenario count.

Define each scenario as `**F1-S1:** Given ..., when ..., then ...`, once, with
IDs unique across this epic's specs. Map every ID to ticket ACs in acceptance.json.
Keep typed interfaces, process topology and configuration in technical.md.

## Edge cases and failure behavior

## Non-goals

## Open questions

Unresolved material intent blocks dependent work.

## Implemented by

Epic/ticket/MR links; this spec outlives the epic.
