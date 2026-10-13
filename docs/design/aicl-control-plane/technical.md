# AICL control plane technical design

## Contracts

### Instance and capability policy

E11-1 owns `AgentInstance {id, tenant_id, template_id, name, instructions, lifecycle, gated_reason, version}` and `CapabilityGrant {instance_id, capability, enabled}`. Lifecycle is `draft|active|paused|archived`; `gated_reason` is an operational overlay. Owner identity derives from `AuthContext`, never request tenant fields.

### BudgetPort

E11-1 owns `reserve(instance_id, estimate, price_table_version) -> Hold`, `settle(hold_id, measured_usage)`, `mark_unknown(hold_id)`, and `read_budget(instance_id)`. A hold atomically checks daily and monthly USD limits; price/limit/validation failure denies. Usage stores token/minute base metrics and the applied price-table version. Unknown work retains its hold.

## Process topology

The authenticated web application calls the instance service. The instance service calls the budget controller over authenticated in-process service boundaries for MVP. The budget controller owns holds, usage, and price-table versioning; UI projections are read-only.

## Configuration

`PRICE_TABLE_VERSION` selects an operator-managed effective-dated table. Default daily/monthly limits are zero. Missing tables, invalid limits, or unavailable budget state deny dispatch.
