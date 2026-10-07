---
name: ctx-release-review
description: Independently reconcile release readiness and final lifecycle evidence for human outcome approval.
---

Verify project, source SHA, pipeline, artifact, configuration and deployment identity
across actual job outcomes and reports. Check applicable license/DCO, branch/MR and
environment controls. Mark absent stages incomplete; an operation name is not proof.

Before release, report unmet prerequisites. Before promotion, present the exact
candidate, target settings, staging/browser/health evidence and required human gate.
After promotion, record what actually deployed and its health. Do not self-approve
or treat a manual CI button as proof of authorized approver enforcement.

Summarize all nine stages with links, distinguishing ready-for-review, approved,
deployed and healthy. Current missing release/monitor adapters prevent a complete
end-to-end verdict but do not erase the user's confirmed live planning run.
