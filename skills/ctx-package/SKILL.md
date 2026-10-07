---
name: ctx-package
description: Reconcile a verified candidate with its versioned artifact, immutable digest and SBOM.
---

Require passing verification, acceptance and source-security jobs for the release
SHA. Use reviewed CI packaging commands, with dependency locks and the actual build
recipe. Retain artifact/SBOM URLs and immutable digest; mutable tags are insufficient.

The delivery agent reads job evidence and coordinates configured CI; it does not
invent artifacts or hold deployment credentials. Missing build adapters block
packaging. Artifact security must pass before configuration/deployment readiness.
