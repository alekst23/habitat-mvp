---
name: ctx-ticket-close
description: Integrate an independently reviewed ticket into its epic and reconcile its actual completion state.
---

Verify candidate SHA, independent ticket review and mandatory CI/AC/browser evidence.
Reconcile current epic HEAD before integration. Merge only under repository policy,
using ordinary non-force git operations. If the target moved, rebase/merge as policy
allows and rerun affected verification before claiming integration.

Run sufficient integration checks on the resulting epic SHA. Record source and
integration SHAs, passing pipeline and review links in state.json before marking
done. A ticket MR alone is not completion. Partial work cannot unlock dependents.
Return the verified integration receipt to the supervisor so it selects the next
ready ticket in the SAME invocation. Only a real blocker/budget boundary requires
a durable resume handoff. Do not let an integration token certify whole-epic completion.
