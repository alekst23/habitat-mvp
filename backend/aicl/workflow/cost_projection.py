"""Read-only cost classification over recorded charges, without repricing history.

The control ledger's inference bucket can include search fees. Preserve the
canonical amount as one bundled line when a receipt contains both token and tool
usage; do not manufacture an allocation from current or historical prices.
"""
from __future__ import annotations

from decimal import Decimal
from urllib.parse import quote


LABELS = {"model": "Model", "model_and_tools": "Model + tools", "tools": "Tools / network",
          "compute": "Compute", "storage": "Storage / data access", "merchant": "Merchant payment",
          "funding": "Service funding", "other": "Unknown resource"}
SERVICE_COMPONENTS = ("model", "model_and_tools", "tools", "compute", "storage", "other")


def cost_line(source):
    """Add a shared display contract while preserving source category and IDs."""
    row = dict(source)
    category = row["category"].lower().replace("_", " ")
    amount = row.get("amount_micro_usd")
    if amount is None:
        amount = int(Decimal(str(row["amount_usd"])) * 1_000_000)
    tokens = (row.get("input_tokens") or 0) + (row.get("output_tokens") or 0)
    searches = row.get("web_search_calls") or 0
    if row.get("component") in LABELS:
        component = row["component"]
    elif "service funding" in category:
        component = "funding"
    elif any(word in category for word in ("purchase", "merchant", "ad funding")):
        component = "merchant"
    elif "compute" in category:
        component = "compute"
    elif "storage" in category or "data access" in category:
        component = "storage"
    elif any(word in category for word in ("tool", "network", "search")):
        component = "tools"
    elif searches:
        component = "model_and_tools" if tokens else "tools"
    elif "inference" in category or "setup" in category or "model" in category:
        component = "model"
    else:
        component = "other"
    if row.get("charge_kind") in ("usage", "estimate", "funding", "reservation", "waiver"):
        kind = row["charge_kind"]
    elif "reservation" in category:
        kind = "reservation"
    elif "waived" in category:
        kind = "waiver"
    elif component == "funding":
        kind = "funding"
    elif component == "compute":
        kind = "estimate"
    else:
        kind = "usage"
    pricing, note = "recorded", "Recorded ledger amount."
    if component == "model_and_tools":
        pricing, note = "combined", "Model tokens and search calls share this recorded charge; individual prices were not recorded."
    elif component == "tools":
        note = "Recorded search-only charge. Other network or tool costs are not separately metered." if searches else "Recorded tool / network charge."
    elif component == "compute" and kind == "estimate":
        pricing, note = "estimated", "Compute estimate from recorded runtime; a provider invoice is not recorded."
    if kind == "reservation":
        pricing, note = "reserved", "Maximum held for unresolved work; excluded from recorded charges and estimates."
    elif kind == "funding":
        note = "Credit added to the account; excluded from work costs."
    elif kind == "waiver":
        note = "Waived setup usage; excluded from work costs."
    elif component == "merchant":
        note = "Merchant payment, separate from resource usage."
    job_id = row.get("job_id") or row.get("run_id")
    row.update(amount_micro_usd=amount, amount_usd=amount / 1_000_000,
               component=component, component_label=LABELS[component], charge_kind=kind,
               pricing=row.get("pricing", pricing), coverage_note=row.get("coverage_note", note), job_id=job_id, run_id=job_id)
    row.setdefault("step_id", None)
    row.setdefault("hold_id", None)
    row.setdefault("price_table_version", None)
    row.setdefault("provenance", "application_record")
    return row


def cost_summary(rows):
    """Separate settled resource use, runtime estimates, and unresolved holds."""
    lines = [cost_line(row) for row in rows]
    service = [row for row in lines if row["component"] in SERVICE_COMPONENTS]
    settled = sum(row["amount_micro_usd"] for row in service if row["charge_kind"] == "usage")
    estimated = sum(row["amount_micro_usd"] for row in service if row["charge_kind"] == "estimate")
    components = []
    for component in SERVICE_COMPONENTS:
        matching = [row for row in service if row["component"] == component and row["charge_kind"] in ("usage", "estimate")]
        # A combined charge covers models and tools without assigning it twice.
        bundled = component in ("model", "tools") and any(row["component"] == "model_and_tools" for row in service)
        usage = sum(row["amount_micro_usd"] for row in matching if row["charge_kind"] == "usage")
        estimate = sum(row["amount_micro_usd"] for row in matching if row["charge_kind"] == "estimate")
        if component in ("model_and_tools", "other") and not matching:
            continue
        components.append({"component": component, "label": LABELS[component],
            "amount_micro_usd": usage + estimate if matching else None,
            "settled_micro_usd": usage, "estimated_micro_usd": estimate,
            "coverage": "bundled" if bundled else "recorded" if matching else "not_metered",
            "coverage_note": "Additional usage is included in the combined model + tools charge." if bundled and matching else
                             "Included in the combined model + tools charge." if bundled else
                             "Recorded charge; no separate price allocation." if component == "model_and_tools" else
                             "Recorded charges only." if matching else "No separate charge is recorded; this is not a claim that usage is free."})
    return {"settled_micro_usd": settled, "estimated_micro_usd": estimated,
        "total_micro_usd": settled + estimated,
        "held_micro_usd": sum(row["amount_micro_usd"] for row in service if row["charge_kind"] == "reservation"),
        "merchant_micro_usd": sum(row["amount_micro_usd"] for row in lines if row["component"] == "merchant" and row["charge_kind"] == "usage"),
        "components": components,
        "coverage_note": "Only recorded charges and runtime estimates are totaled. Bundled fees are counted once; unmetered storage, data access and other tools are not assumed free."}


def cost_jobs(rows, jobs=()):
    """Roll up exactly these period lines, including honest unallocated charges."""
    lookup = {row["id"]: row for row in jobs if row.get("id")}
    groups = {}
    for source in rows:
        row = cost_line(source)
        if row["component"] not in SERVICE_COMPONENTS or row["charge_kind"] not in ("usage", "estimate", "reservation"):
            continue
        agent_id = row.get("agent_id") or row.get("instance_id")
        key = (agent_id, row["job_id"])
        groups.setdefault(key, []).append(row)
    result = []
    for (agent_id, job_id), lines in groups.items():
        summary = cost_summary(lines)
        job = lookup.get(job_id, {})
        latest = job.get("latest_deliverable") or {}
        title = latest.get("name") or job.get("output_name") or job.get("deliverable_name") or job.get("goal")
        # A runtime objective can contain the owner's entire supplied context.
        # Keep the grid scannable; the full objective belongs to the source job.
        title = next((line.strip() for line in str(title or "").splitlines() if line.strip()), "")
        title = title[:117].rstrip() + "…" if len(title) > 120 else title
        components = ", ".join(dict.fromkeys(row["component_label"] for row in lines if row["charge_kind"] != "reservation")) or "Held only"
        result.append({"id": job_id or "unallocated:" + str(agent_id), "job_id": job_id, "run_id": job_id,
            "agent_id": agent_id, "agent_name": lines[0].get("agent_name", "Agent"),
            "job_name": title or ("Recorded job " + job_id.removeprefix("runtime:")[:8] if job_id else "Setup / unallocated work"),
            "started_at": job.get("scheduled_at") or job.get("scheduled_for") or job.get("created_at") or min(row.get("occurred_at") or row.get("created_at") or "" for row in lines),
            "status": job.get("status") or job.get("state") or ("recorded" if job_id else "unallocated"),
            "job_reference": job_id.removeprefix("runtime:")[:8] if job_id else "Unallocated",
            "settled_usd": summary["settled_micro_usd"] / 1_000_000,
            "estimated_usd": summary["estimated_micro_usd"] / 1_000_000,
            "total_usd": summary["total_micro_usd"] / 1_000_000,
            "held_usd": summary["held_micro_usd"] / 1_000_000,
            "components": components, "coverage": summary["coverage_note"], "cost_summary": summary,
            "evidence_url": "/audit/jobs/" + quote(job_id, safe="") + "#cost-breakdown" if job_id else lines[0].get("evidence_url"),
            "line_count": len(lines)})
    return sorted(result, key=lambda row: (-row["total_usd"], row["agent_name"], row["id"]))


def project_costs(rows, jobs=()):
    lines = [cost_line(row) for row in rows]
    return {"cost_rows": lines, "cost_summary": cost_summary(lines), "cost_jobs": cost_jobs(lines, jobs)}
