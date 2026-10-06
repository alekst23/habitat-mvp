---
name: ctx-environment-configure
description: Check reviewed environment settings and distinguish configuration validation from actual application.
---

Verify candidate digest, target environment, configuration content hash, limits,
secret references and migration requirements. Configuration reports must identify
what was validated and what was actually applied, without exposing secrets.

Current CI supports staging validation only. Applying settings or migrations needs
separate reviewed deployment jobs and target controls. Do not label validation as
deployment. Production approval must identify its own configuration revision.
