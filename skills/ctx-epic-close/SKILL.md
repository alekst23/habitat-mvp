---
name: ctx-epic-close
description: Prepare a verified epic MR and durable project handoff after complete feature review.
---

Require all tickets integrated, current mandatory CI and acceptance evidence, and
independent whole-epic review without unresolved blockers. Use ctx-epic-docs before
the final review and ctx-merge-queue to check readiness/order.

Open/update the epic MR targeting the actual default branch with linked criteria,
review and job evidence. Apply "Publishing GitLab Markdown" in
docs/development/ctx-contract.md and verify the saved description and links.
Preserve repository merge approval. Report MR-ready, not
merged, deployed or released. Update project state with the exact delivery handoff
to use after the merge result is verified. Do not close the parent issue early.
