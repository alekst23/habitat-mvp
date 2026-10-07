---
name: ctx-epic-docs
description: Update the documentation needed to use and operate a completed feature.
---

Compare implemented behavior with the spec and existing setup/API/operation docs.
Update only material changed behavior, configuration and known limitations. Preserve
historical evidence and distinguish implemented behavior from planned capability.
Avoid duplicate documents and generic boilerplate. Documentation edits normally
need inspection or existing validators, not new behavioral tests.

Commit on the epic branch. Documentation commits change the candidate SHA; obtain
the applicable CI and final review before publishing readiness for the new SHA.
