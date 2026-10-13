# AICL control plane

## Intent

A signed-in owner configures a Default template instance without giving it direct credentials or authority outside AICL.

## Scenarios

**F1-S1:** Given an authenticated owner, when they create Default with a name and free-form instructions, then AICL creates a tenant-owned draft instance.

**F1-S2:** Given a draft instance, when the owner enables a listed capability, then only that capability becomes eligible for evaluation.

**F1-S3:** Given an active instance, when inference or compute is requested, then AICL reserves the maximum estimated USD against daily and monthly limits before work begins.

**F1-S4:** Given measured token/minute usage, when work completes, then AICL settles usage with the applied versioned price table and exposes USD totals.

**F1-S5:** Given an exhausted, missing, invalid, or unavailable limit, when work is requested, then AICL denies it and reports `gated`.

**F1-S6:** Given an active instance, when the owner pauses or archives it, then new work is denied and its history remains visible.

## Failures and non-goals

Unknown prices, disabled capabilities, and uncertain outcomes fail closed; uncertain outcomes retain reservations until reconciliation. This feature has no payment rail, provider enablement, BYOA runtime, or arbitrary code execution.
