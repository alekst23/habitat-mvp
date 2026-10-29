-- A broker entry is a one-shot claim, distinct from a budget reservation.
-- A process dying after this insert cannot prove absence of remote effects.
CREATE TABLE public_research_dispatch (
 hold_id TEXT PRIMARY KEY REFERENCES budget_hold(id),
 run_id TEXT NOT NULL REFERENCES agent_run(id),
 claimed_at TEXT NOT NULL
);
CREATE TRIGGER public_research_dispatch_no_update BEFORE UPDATE ON public_research_dispatch
BEGIN SELECT RAISE(ABORT, 'research dispatch claims are immutable'); END;
CREATE TRIGGER public_research_dispatch_no_delete BEFORE DELETE ON public_research_dispatch
BEGIN SELECT RAISE(ABORT, 'research dispatch claims must be retained'); END;
