---
name: ctx-security-check
description: Assess source, dependency, secret and artifact scan evidence and route actionable security findings.
---

Read the actual GitLab jobs and reports for the candidate commit/artifact. Require
source, dependency and secret checks before packaging, then scan the immutable
artifact digest. Verify findings and disposition; do not substitute a build result
or an agent opinion for missing scans.

Deduplicate actionable findings and report a scoped development/planning handoff.
Changed code must rerun affected checks and produce a newly verified artifact.
Never grant secrets or weaken blocking policy to obtain a passing result.
