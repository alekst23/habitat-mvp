-- AI processing is intrinsic to canonical workspace agents. Upgrade existing
-- non-archived agents once, under the product policy change, without changing
-- lifecycle, schedules, disclosures, spending limits or financial history.
-- Legacy instances outside the unified workspace keep their existing controls.
CREATE TEMP TABLE workspace_intrinsic_inference AS
SELECT w.id AS workspace_id, i.id AS instance_id, i.tenant_id, i.owner_id,
       i.version AS instance_version,
       strftime('%Y-%m-%dT%H:%M:%f000Z','now') AS changed_at
FROM agent_workspace w JOIN agent_instance i ON i.id=w.instance_id
LEFT JOIN capability_grant g ON g.instance_id=i.id AND g.capability='inference'
WHERE i.lifecycle != 'archived' AND COALESCE(g.enabled,0)=0;

INSERT INTO capability_grant(instance_id,capability,enabled)
SELECT instance_id,'inference',1 FROM workspace_intrinsic_inference WHERE 1
ON CONFLICT(instance_id,capability) DO UPDATE SET enabled=1;

UPDATE agent_instance
SET version=version+1,
    updated_at=(SELECT changed_at FROM workspace_intrinsic_inference m WHERE m.instance_id=agent_instance.id)
WHERE id IN (SELECT instance_id FROM workspace_intrinsic_inference);

-- Only advance an up-to-date source version. Existing stale drafts must still
-- report their external conflict instead of accepting unrelated control edits.
UPDATE agent_workspace
SET source_instance_version=CASE
      WHEN source_instance_version=(SELECT instance_version FROM workspace_intrinsic_inference m WHERE m.workspace_id=agent_workspace.id)
      THEN source_instance_version+1 ELSE source_instance_version END,
    version=version+1,
    updated_at=(SELECT changed_at FROM workspace_intrinsic_inference m WHERE m.workspace_id=agent_workspace.id)
WHERE id IN (SELECT workspace_id FROM workspace_intrinsic_inference);

INSERT INTO audit_event(id,event_type,actor_kind,outcome,tenant_id,owner_id,instance_id,reason,details,occurred_at)
SELECT lower(hex(randomblob(16))),'instance.capability_changed','system','committed',
       tenant_id,owner_id,instance_id,'workspace_intrinsic_inference',
       json_object('action','workspace_intrinsic_inference','capability','inference',
                   'enabled',json('true'),'version',instance_version+1),changed_at
FROM workspace_intrinsic_inference;

DROP TABLE workspace_intrinsic_inference;
