---
name: ctx-project-design
description: Route a requested Habitat change to an existing feature update, scoped fix, or new planning intake.
---

Read AGENTS.md and docs/development/ctx-contract.md. Compare the request with
existing specs, project state, issues and MRs. Record the source issue, feature,
scope and route; reuse existing work. A materially different product decision
needs an answer on the issue before dependent work continues.

Resolve the actual parent epic issue before allocating IDs. The intake issue is
not necessarily the epic. Preserve existing branch and issue mappings. Pass the
resolved intent to ctx-issue-triage; this operation does not implement the change.
