---
name: ctx-merge-queue
description: Check an epic MR's integration order, base movement and required merge controls.
---

Read actual target branch, dependent MRs, current diff and required checks. Verify
upstream work is integrated and the reviewed SHA is still the candidate. Record
conflicts or base movement and the necessary re-verification.

Prepare the merge order and readiness evidence. Do not change branch protection,
self-approve or merge to default. This procedure does not implement a GitLab merge
train or background queue; repository controls govern the actual merge.
