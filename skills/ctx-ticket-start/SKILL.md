---
name: ctx-ticket-start
description: Implement a scoped ticket after its design and minimal behavioral test prerequisites are satisfied.
---

Read AGENTS.md, the ticket design, spec and test evidence. Check real prerequisites
on direct entry as well as resume. Implement only the ticket on its isolated branch.
Preserve failing assertions; do not reduce requirements or weaken checks to get green.

Use ctx-ci-check for the smallest sufficient verification. Commit the candidate
before collecting SHA-bound results. Open/update the ticket MR targeting the epic.
Apply "Publishing GitLab Markdown" in docs/development/ctx-contract.md to its
description and reports; verify the saved formatting and link targets.
Record design/red/green SHAs, tests and AC evidence. Pending CI blocks validation,
not unrelated work in the supervisor session; it is not a passing verification.
The supervisor may recheck once after actual fresh CI evidence, within its bounds.
If nothing else can progress, persist a durable checkpoint for a reconciled resume.
An independent reviewer determines readiness. New code invalidates prior evidence.

In a version-2 managed implementation phase, ready means the scoped candidate is
saved and handed to verify, not that it passed. Known actionable failures may be
reported as defect findings for the bounded repair loop; missing setup stays blocked.
During repair follow ctx-project-fix, preserve valid failing coverage, commit a new
SHA and report resolved_findings. The supervisor then verifies every scoped AC and
obtains a fresh independent review before integration.

For an explicitly delegated assembled-epic repair, use ctx-project-fix's epic mode
instead of this ticket-entry/MR-creation path. Preserve ticket history and return
through docs, full-epic verification and independent epic review.
