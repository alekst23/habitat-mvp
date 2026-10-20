# Habitat owner-control MVP

Habitat's Configurable AI Control Layer lets an owner create and manage a Default
agent instance through a wizard or built-in chat. The owner controls capabilities,
daily/monthly inference and compute budgets, connections, network domains and
per-action confirmations. The application shows usage, gating and redacted history.

This E11 implementation is a control-plane prototype: chat is scripted, OAuth
providers and work execution are simulated, and no model call or Gmail/Reddit
action is performed. SMTP sign-in delivery is the one configurable real outbound
edge. PayPal, a running autonomous agent and deployment are outside E11.

The stable baseline includes the responsive E11-6 owner UI and the proposed PayPal
funding/purchase designs. See the [itemized implementation backlog](docs/paypal-mvp-backlog.md)
for the next release. PayPal and real inference remain unimplemented.

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

E11-1 through E11-5 are integrated and verified at
`ca4e172241a484c174ce37e4a8642aabd511945a`. All eleven mandatory jobs passed in
[pipeline 2959718088](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2959718088),
with a separate [whole-epic review](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/issues/11#note_4036886044).
That pipeline records the five-ticket baseline before E11-6. The
[E11 evidence record](docs/plan/E11/completion.md) preserves the integration history.

The separately requested [E11-6 UI refinement](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/work_items/19)
was developed on `codex/e11-ui-polish`. It adds responsive navigation, workspace
cards and status summaries, grouped owner controls, readable activity, and explicit
pending/uncertain request feedback. Application source `419e77b` passed its separate
review and [pipeline 2960426331](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/pipelines/2960426331),
including 73 backend tests and four browser journeys. The combined stable-main
integration is tracked by [MR !45](https://gitlab.com/gitlab-ai-hackathon/transcend-october-2026/43066631/showcase/-/merge_requests/45).
Its current pipeline records integration evidence; no deployment is implied.

In the owner UI, use **Budgets**, **Capabilities** and **Activity** to jump between
controls. **Simulated work request** sends the selected capability and compute
minutes; it does not accept model tokens or an email body. After a result, use its
reload link to see persisted usage, gates or pending confirmations. An uncertain
result disables repeat submission until the page is reloaded and activity checked.

## Repository guide

- [Stable baseline and itemized PayPal MVP updates](docs/paypal-mvp-backlog.md)
- [Current E11 scope and decisions](docs/plan/E11/_epic.md)
- [Design index and contracts](docs/design/README.md)
- [Application setup and operation](docs/aicl-mvp.md)
- [PayPal target demo script and implementation gaps](docs/hackathon-demo-script.md)
- [PayPal funding design for agent inference and resources](docs/design/paypal-funding/spec.md)
- [Agent purchases through PayPal](docs/design/agent-purchases/spec.md)
- [PayPal demo readiness and control rehearsal findings](docs/hackathon-demo-rehearsal.md)
- [Development and evidence workflow](docs/development/ctx-contract.md)
- [Historical marketing-agent proposal](docs/habitat-mvp.md)

This repository is the Transcend Hackathon Showcase workspace. The earlier E2
PayPal/marketing proposal remains for traceability; it is not the implemented
E11 scope.
