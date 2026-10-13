# AICL experience

## Intent

Owners understand and control Default instances through a landing page, authenticated workspace, wizard, built-in chat, connection area, and instance views.

## Scenarios

**F3-S1:** Given a visitor, when they open the landing page, then they see AICL controls and a Create your first agent action.

**F3-S2:** Given a visitor following that action, when they complete email magic-link sign-in, then the server derives their owner and tenant session.

**F3-S3:** Given an empty workspace, when an owner chooses wizard or chat, then both guide creation of the same Default instance model.

**F3-S4:** Given an instance, when the owner views its detail page, then they see lifecycle, `gated` reason if any, instructions, enabled capabilities, budgets, attachments, and redacted audit/usage history.

**F3-S5:** Given an owner, when they change budgets, capabilities, connections, or lifecycle, then the UI shows the committed result or a truthful denial.

## Failures and non-goals

Chat and wizard never receive OAuth credentials or bypass server validation. Another tenant’s instances, connections, usage, or history are never shown.
