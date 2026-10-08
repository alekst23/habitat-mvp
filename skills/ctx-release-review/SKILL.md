---
name: ctx-release-review
description: Independently reconcile release readiness and final lifecycle evidence for human outcome approval.
---

Verify project, source SHA, pipeline, artifact, configuration and deployment identity
across actual job outcomes and reports. Check applicable license/DCO, branch/MR and
environment controls. Mark absent stages incomplete; an operation name is not proof.

Read the CI artifact `.ctx/reports/delivery-readiness.json` from the exact candidate
pipeline. `scripts/ctx_delivery.py` checks receipt identities, dependencies, artifact
and configuration bindings, approval/deployment identities and observation ordering.
Its four phases are candidate, staging, promotion and production. An
`evidence_complete` result is a consistency check, not proof of authentic jobs or
human approval; independently read GitLab state and evidence. It grants no deployment
authority. Never manufacture the missing plan/create/govern/deployment receipts.

Before release, report unmet prerequisites. Before promotion, present the exact
candidate, target settings, staging/browser/health evidence and required human gate.
After promotion, record what actually deployed and its health. Do not self-approve
or treat a manual CI button as proof of authorized approver enforcement.

Summarize all nine stages with links, distinguishing ready-for-review, approved,
deployed and healthy. Current missing release/monitor adapters prevent a complete
end-to-end verdict but do not erase the user's confirmed live planning run.
