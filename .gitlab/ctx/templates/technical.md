# Feature technical design

## Contracts

Name each contract, owner ticket, consumers and proposed/existing source location.
Define typed fields or method signatures, request/results/errors, authorization,
idempotency, transaction boundaries and recovery behavior. No secret values.

## Process topology

For each component: runtime process, state owner, construction/entry point,
authenticated channel to consumers, and failure behavior. State explicitly when
there is no cross-process boundary. Name the wiring ticket and observable smoke.

## Configuration

Setting, service owner, working default or required-unset value, secret reference,
startup check and .env.example location. Unknown provider facts stay disabled.

## Decisions and verification

Open question, owner, affected tickets and exact condition for resolution.
Independent design-review SHA/note and structural CI evidence when actually obtained.
