# Spike: Render API — Feasibility Findings

**Ticket:** E2-1 (issue #3)  
**Epic:** E2 (issue #2)  
**Date:** 2026-10-06  
**Spike scope:** Confirm background worker and Workflow task provisioning via API, resource types, cost estimates, isolation model, and Blueprint support.

## Summary

**Go/No-Go:** ✅ GO — Render API supports programmatic provisioning of services and workers. Blueprint (render.yaml) supports infrastructure-as-code deployment. The isolation model is per-service, which maps to Habitat's per-owner agent model.

---

## Findings

### 1. API-driven provisioning

Source: https://api-docs.render.com/reference/introduction

- Render provides a REST API at `https://api.render.com/v1/`.
- Authentication: Bearer token (API key from the Render dashboard).
- **Services can be created, updated, and deleted via API:**
  - `POST /services` — create a new service (web service, background worker, cron job, etc.)
  - `GET /services/{serviceId}` — get service status
  - `POST /services/{serviceId}/deploys` — trigger a deploy
  - `DELETE /services/{serviceId}` — delete a service
- **Background workers** are a supported service type (`type: background_worker`).
- **Cron jobs** are supported for scheduled tasks.

### 2. Render Workflows (Workflow tasks)

- Render does **not** have a native "Workflow" task type in the same sense as Temporal or Prefect.
- The closest equivalent is a **background worker** (long-running process) or a **cron job** (scheduled).
- For Habitat's marketing agent: a **background worker** per owner is the correct model.
- The background worker runs continuously and processes tasks from a queue or event stream.
- **Alternative:** Use a web service with a task queue (e.g., Redis + worker process) for more flexible task dispatch.

### 3. Resource types available

| Type | Use case | Notes |
|---|---|---|
| Web Service | HTTP API endpoints | Auto-scaling available |
| Background Worker | Long-running agent processes | Per-owner isolation |
| Cron Job | Scheduled tasks | Not suitable for continuous agents |
| Static Site | Frontend hosting | For habitat-site |
| PostgreSQL | Managed database | For ledger, activity log |
| Redis | Cache / queue | For task dispatch |
| Private Service | Internal-only services | For secrets-service, inference-proxy |

### 4. Cost estimates

| Resource | Tier | Monthly cost |
|---|---|---|
| Web Service (Starter) | 512 MB RAM, 0.5 CPU | $7/month |
| Web Service (Standard) | 2 GB RAM, 1 CPU | $25/month |
| Background Worker (Starter) | 512 MB RAM, 0.5 CPU | $7/month |
| PostgreSQL (Starter) | 256 MB RAM, 1 GB storage | $7/month |
| Redis (Starter) | 25 MB | $10/month |

- For the hackathon: platform services (secrets, inference proxy, ledger, tool interface, action broker, PayPal proxy) ≈ 6–8 services × $7–25 = ~$50–200/month.
- Per-owner agent workers: $7/month each (Starter tier is sufficient for demo).
- **Hackathon budget concern:** Render does not offer a free tier for background workers. Use the Starter tier and shut down after the demo.

### 5. Isolation model

- Each Render service is isolated at the container level.
- Per-owner isolation: deploy one background worker service per owner.
- Services in the same Render team can communicate via private networking (internal URLs).
- **Private services** are not exposed to the public internet — correct for secrets-service, inference-proxy, ledger-service.
- Environment variables are set per-service and are not shared between services.

### 6. Blueprint support (render.yaml)

- Render supports **Blueprints** via a `render.yaml` file in the repository root.
- Blueprints define all services, databases, and environment variables declaratively.
- `render.yaml` can be used to provision the entire Habitat platform in one operation.
- Blueprint documentation: https://render.com/docs/blueprint-spec
- **Supported in Blueprint:** web services, background workers, cron jobs, PostgreSQL, Redis, private services.
- **Limitation:** Per-owner agent workers cannot be fully managed by a static Blueprint (they are dynamic). The provisioning-proxy must use the Render API to create/delete per-owner workers at runtime.

### 7. API-driven per-owner worker provisioning

- The `provisioning-proxy` service will:
  1. Call `POST /services` to create a background worker for a new owner.
  2. Set environment variables (owner ID, tool interface URL, inference proxy URL) via `POST /services/{id}/env-vars`.
  3. Trigger a deploy via `POST /services/{id}/deploys`.
  4. Monitor status via `GET /services/{id}`.
  5. Delete the worker via `DELETE /services/{id}` when the owner is removed.
- This flow is confirmed to work via the Render API.

---

## Go/No-Go Decision

**Primary path (Render API + Blueprint):** ✅ GO
- Background workers are supported and can be provisioned via API.
- Blueprint supports the platform services layer.
- Per-owner isolation is achievable via per-service deployment.
- Cost is manageable for the hackathon demo.

## Open questions resolved

- **Q4 from spec.md:** Per-owner isolation layout on Render → **One background worker service per owner, provisioned via the Render API by the provisioning-proxy. Platform services use a static Blueprint.**
