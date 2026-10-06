---
name: ctx-monitor
description: Assess deployment health, browser smoke evidence and operational signals over a recorded observation window.
---

Require a real deployment identity tied to the artifact and effective configuration.
Read health/smoke results, relevant redacted logs and a few meaningful metrics. Reuse
the critical browser journey; do not repeat the entire application suite after deploy.
Record the observation window and expected versus observed behavior.

An expected budget denial is a successful policy check, not an outage. Unexpected
failures block a healthy verdict. Deduplicate findings and hand them to planning or
development. Missing deployment/monitor adapters are blocked, not healthy. This
operation does not create a recurring scheduler or incident-response authority.
