# E<epic issue IID>-<ticket number>: <title>

Project ID / ticket GitLab issue IID and URL / parent epic issue IID and URL / branch / MR / status:

Use this ID in the GitLab issue title and filename. The ticket number is a stable
sequence within its epic, not the ticket's GitLab issue IID. Preserve it on resume.

## Acceptance criteria

Planning: high-level acceptance expectations; preserve existing stable AC IDs.
Design: feature spec and stable scenario/AC IDs; matching acceptance.json entries
with UI classification and required methods (test/browser/justified inspection).

## Dependencies

## Design

Design pending until CTX Design saves the solution approach, contracts, boundaries,
technical.md pointer and verified design commit reference. Pending design does not
block ticket creation, but it does block implementation.

## Tests before implementation

AC-to-test mapping; existing tests reused and why each new test is necessary.
Write the absolute minimum meaningful tests, using one test for multiple ACs where
appropriate. Small fixtures, direct assertions, no duplicated layers or quotas.
Command, collected count, expected assertion failure, red-test SHA and evidence URL.
Collection/import errors do not satisfy this gate. For unchanged behavior or docs,
record why existing coverage or inspection is sufficient rather than adding ritual tests.

## Implementation and verification

Candidate SHA, passing tests, required CI job URLs, browser evidence if applicable:

## Independent ticket review

Checked SHA; every AC's passed/failed/blocked verdict, code reference and actual
test/browser/inspection evidence; material findings; reviewer report URL:

## Closure

Epic integration SHA/CI, ancestry check, persisted state and next handoff:
