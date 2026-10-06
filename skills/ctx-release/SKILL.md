---
name: ctx-release
description: Coordinate staging or promotion of a verified artifact through authorized deployment jobs.
---

Resolve the merged release SHA on the actual default branch. Require current
verification, acceptance, security, artifact and configuration evidence. Deploy only
through reviewed CI jobs with environment controls; never from an agent shell.

Before promotion, require the authorized human outcome approval bound to artifact,
production configuration and target. Promote that same digest and retain deployment
and recovery evidence. An MR approval is not deployment authorization.

The repository currently has no deployment/promotion adapter. Report this operation
blocked until the jobs and controls exist. Do not create a pretend successful release.
