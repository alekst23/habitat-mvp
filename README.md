# Habitat AICL MVP

Habitat's Configurable AI Control Layer lets an owner create and manage a Default
agent instance through a wizard or built-in chat. The owner controls capabilities,
daily/monthly inference and compute budgets, connections, network domains and
per-action confirmations. The application shows usage, gating and redacted history.

This E11 implementation is a control-plane prototype: chat is scripted, OAuth
providers and work execution are simulated, and no model call or Gmail/Reddit
action is performed. SMTP sign-in delivery is the one configurable real outbound
edge. PayPal, a running autonomous agent and deployment are outside E11.

## Run locally

Use Python 3.12 from the repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r backend/requirements.lock
PYTHONPATH=backend python -m aicl.test_server
```

Open <http://127.0.0.1:4173>, request a sign-in link for `demo@example.test`, then
open <http://127.0.0.1:4173/__test__/last-magic-link?email=demo%40example.test>
and follow the captured link. Confirm sign-in to reach the workspace. This local
test composition needs no SMTP account and removes its temporary database on exit.

The [application guide](docs/aicl-mvp.md) covers the full demo, persistent local
configuration, routes, checks and operational limits.

## Implementation and acceptance

E11-1 through E11-4 are integrated into `ctx/epic-i11`. E11-5 has an implemented,
reviewed candidate in MR !76; its integration and the assembled epic's final
acceptance are still pending in this documentation snapshot. See the
[E11 evidence record](docs/plan/E11/completion.md) for source identities and the
remaining gates. A ticket's passing checks do not certify the entire epic or a
deployment.

## Repository guide

- [Current E11 scope and decisions](docs/plan/E11/_epic.md)
- [Design index and contracts](docs/design/README.md)
- [Application setup and operation](docs/aicl-mvp.md)
- [Development and evidence workflow](docs/development/ctx-contract.md)
- [Historical marketing-agent proposal](docs/habitat-mvp.md)

This repository is the Transcend Hackathon Showcase workspace. The earlier E2
PayPal/marketing proposal remains for traceability; it is not the implemented
E11 scope.
