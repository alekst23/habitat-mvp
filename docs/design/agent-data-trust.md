# Agent data, confidentiality and trust

Status: proposed, October 25, 2026. Security requirements for the
[durable execution plan](durable-agent-execution.md), based on a read-only code
review. These controls are not yet implemented or verified in deployment.

## Trust boundary

Preserve existing tenets: authenticated tenant identity, owner-controlled
authority, least privilege, broker-held credentials, reservation before paid
dispatch, retained holds for unknown outcomes, and append-only control/accounting
history. Add an explicit information-flow rule: permission to read information
does not authorize disclosing it to a model processor, website, tool or audience.

The threat model includes another tenant, an overprivileged same-owner agent, a
compromised worker, malicious retrieved content, accidental logging/backups and
unapproved external processing. Encryption at rest does not protect plaintext
from a compromised process that is legitimately authorized to decrypt it.

An owner-controlled policy must select approved processing boundaries. The model
cannot select a processor outside that policy. Support approved cloud processors
or organization-controlled execution as policy profiles; neither is approved
merely by being listed here. Missing policy denies sensitive processing. A strict
profile fails unavailable if no compliant adapter is installed, rather than
falling back to a public model endpoint.

If the requirement is secrecy from Habitat operators or the execution host itself,
ordinary server-side encryption is insufficient. That requires a separate
client-controlled or independently isolated execution/key-custody design. Do not
promise end-to-end encryption while our server and a model provider receive
plaintext. Hosting, operator access, backups and processor terms are part of the
trust boundary.

## Separate confidentiality, authority and provenance

Do not use a single `trusted` boolean.

| Dimension | Meaning |
| --- | --- |
| Confidentiality | Example levels: public, internal, confidential, restricted; unclassified owner content defaults confidential with no public export or processor access until granted |
| Authority | Application control, authenticated owner directive, external evidence or model-derived proposal; only authorized control operations change grants |
| Access scope | Tenant, principal, instance/run, explicitly granted resources and purpose |
| Processing/disclosure policy | Permitted processors, regions/features, tool destinations, audiences and export rules |
| Provenance | Source identity/version, ingestion origin, producing attempt/context and transformation lineage |
| Lifecycle | Retention deadline, deletion state, encryption/key version and allowed replicas |

A public page remains untrusted instructions. An owner document may be confidential
evidence without being an owner directive. Quoted text and uploaded documents do
not acquire instruction authority from their uploader. Model output can propose
work but never becomes an approval or security policy.

Unknown labels or missing lineage fail closed under the restrictive policy until
a trusted control operation resolves them. The model cannot classify an object
as public to make a blocked action executable.

## Data model

Separate small operational records, protected content objects and credentials.
Policy and grant records are writable only through authenticated control services.
The model submits content/proposals, not security metadata.

| Record | Security contract |
| --- | --- |
| `agent_definition` (logical model) | Existing instance identity plus versioned work configuration; protected goal/input/output descriptions, policy reference and explicit resource selections |
| `agent_run` | Tenant/owner/instance, immutable definition snapshot reference, approved input references, policy/version evidence, checkpoint reference, lease and execution limits |
| `content_object` | Opaque ID/version, tenant/scope, classification, policy reference, provenance, encrypted payload reference, key version, retention/deletion state |
| `context_manifest` | Exact object versions/excerpts supplied to a model, processor/feature configuration, policy decisions and resulting restrictions; protect sensitive associations too |
| `agent_step` / `agent_attempt` | Protected input/result references, context manifest, authorization record, provider identity and canonical cost receipt; no raw prompts in operational rows |
| `data_grant` | Principal, resource selector, purpose, permitted operations/destinations, issuer, expiry and revocation/version; possession of an ID grants no access |
| `disclosure_record` | Source/context references, destination/audience, policy/grant versions, exact payload binding and outcome; content retained separately under its policy |
| Audit/accounting | Minimal IDs, transitions, approvals, reason codes, usage and settlement; access controlled even when content-free |

These are logical contracts; reuse existing records without requiring one table
per abstraction. Add a protected-content service and policy evaluation seam before
accumulating new durable text stores.

A plan item is protected content too. Its title, criteria, findings and blockers
can reveal a confidential objective. Store the versioned plan JSON encrypted;
operational rows can carry an opaque item ID and state when necessary. The same
applies to agent names, owner questions/answers, summaries, source URLs, search
queries, screenshots, tool arguments, model responses and output drafts. Labels
alone do not protect these values.

Use opaque artifact IDs resolved through the content service. Never accept an
agent-supplied filesystem path, object-store key or arbitrary URL as authority to
read stored content. Composite tenant/parent constraints and scoped repository
queries reject cross-tenant references. Same-owner cross-run reuse requires an
explicit input grant. Indexes, caches and future embeddings follow the same rules;
filter before retrieval and never deduplicate confidential content across tenants
by a public plaintext hash.

## Enforcement at every boundary

Authorize reading and disclosure outside the model:

```text
principal + run + resource/purpose + current policy
    -> authorized context manifest
    -> approved model processor
    -> proposed action with inherited disclosure restrictions
    -> destination/payload authorization + cost reservation
    -> brokered execution and protected receipt
```

Effective authority is the intersection of current workspace/instance policy, the
run's explicit grants, the worker's delegated scope and the tool's constraints.
Record the policies used, but recheck current controls before decryption/context
assembly, dispatch, export and resume. A checkpoint cannot restore revoked access.
Late-result handling may preserve authorized accounting evidence without advancing
work. If content retention has been revoked, discard that content rather than
restoring it to the run. Quarantine is retention and requires separate applicable
authority; a deletion request must not silently become quarantine.

Replace the shared worker bearer with short-lived service credentials bound to
tenant, run, slice, fence, operations, audience and expiry. Bootstrap workload
identity must be trusted; a worker cannot choose another tenant/run in its token
request. Scheduler identity can offer work, not decrypt arbitrary content. Queue
payloads contain opaque IDs. Workers receive only needed context; connection,
model and payment credentials stay with designated brokers.

A worker that receives plaintext must also have externally enforced containment:
network access only to scoped broker/control-plane endpoints, no direct public
egress, no KMS/provider credentials or unrelated host mounts, and no arbitrary
process/network tools. The worker cannot alter these restrictions. Prefer keeping
the scheduler/worker interface to IDs and executing sensitive processing inside
the approved boundary. Browser proxy rules do not constrain a Render worker's own
network. This deployment capability is not yet verified; a profile requiring it
must remain unavailable until proven. These measures limit a compromised worker's
reach, but cannot guarantee secrecy from compromise of the authorized processing
service or host that can read the plaintext.

The egress check covers query strings, URL paths, headers, bodies, referrers,
uploads, generated links, telemetry and plugins. An allowed hostname and HTTPS are
network controls, not authorization to disclose data. Bind approvals to the actual
payload, destination, purpose, policy version and expiry. Use protected digests or
keyed bindings where low-entropy plaintext hashes would reveal information. The
final broker checks these bindings immediately before dispatch.

## Public research and private analysis

For confidential work, use separate contexts in the same durable run:

1. A public research context receives an explicitly releasable brief and public
   observations. It can search and inspect public pages.
2. A private analysis context receives authorized private inputs plus public
   findings, using an approved processor with public network tools unavailable.
3. Further public research is a proposed disclosure. Its brief/query must satisfy
   an existing release policy or obtain a specific authorized release.

The first context must not receive a model-written summary of private data merely
because the model called it sanitized. Deterministic permitted-field transforms
or an authorized human release can approve a particular export; classifiers and
secret regexes are supplemental detection, not the sole security boundary.

Derive output restrictions from all context actually exposed to a model call,
including prior conversation and opaque continuation state, not just citations
the model chooses to report. Derivatives inherit the most restrictive applicable
classification and the intersection of permitted recipients/purposes. An empty
intersection blocks dispatch. Plans, summaries and tool arguments cannot downgrade
themselves. Track exact lineage where possible and conservatively over-approximate
it when uncertain. Provider histories/caches must not reintroduce private context
into a public call.

Hosted search executes internal queries without an application approval checkpoint.
It therefore receives public/released context only under this design. App-owned
search is necessary when every outbound query needs application authorization.
Separating public research from private analysis and screening generated links
also follows [OpenAI's prompt-injection guidance](https://developers.openai.com/api/docs/guides/deep-research#prompt-injection-and-exfiltration).

Public browsing uses fresh unauthenticated contexts without account cookies/storage.
Browser policy covers redirects, subresources, scripts and page-initiated requests,
not only the first navigation. Removing click/type tools does not make a
credentialed browser read-only: page JavaScript can still issue requests. Prefer
constrained provider read APIs for sensitive authenticated access; authenticated
browser adapters need explicit request/effect controls.

## Storage, operational access and deletion

Use reviewed authenticated encryption and managed key custody. Envelope encryption
separates content keys from tenant wrapping keys, with object identity/version and
tenant bound as authenticated metadata. Keep keys out of database exports, queues,
logs and model context. Define rotation, recovery and least-privilege KMS access.
Disk encryption protects volumes, temporary files and backups but does not replace
content access checks or limit an application with decryption authority.

Protect database journals/WAL, backups, screenshots, indexes, temporary files,
crash dumps and caches. Do not restore an old backup into service without replaying
deletion/revocation records. Restrict operator access; use separate administrative
roles and audited, time-limited emergency access where required by policy.

Logs and audit events use an allowlisted schema with safe value types, not arbitrary
strings under approved field names. Keep prompt/tool tracing off for confidential
runs unless separately approved. Render content inertly; prevent executable HTML
and automatic external image/link previews. Downloads and progress streams require
the same authorization as their artifacts. Content pages avoid shared caches,
external analytics and referrer disclosure.

Retention applies to every copy and derivative, including definitions, checkpoints,
owner messages and content-bearing receipts. Active references prevent routine
garbage collection but do not override explicit deletion or retention policy.
Deletion tombstones affected objects, invalidates derived context as required and
blocks dependent runs. Keep minimal accounting evidence separately. An immutable
snapshot means immutable while retained, not retained forever.

Deleting a row or overwriting ciphertext does not prove erasure from WAL, backups
or provider copies. Cryptographic erasure requires removing every usable copy of
the relevant key, including wrapped/backup copies; verify the key hierarchy supports
the claimed deletion granularity. Record asynchronous provider deletion/retention
limits honestly. Revocation cannot recall previously disclosed plaintext.

## Provider policy

Processing approval names the provider/account or project, endpoint/features,
data classes, region requirements, retention and subcontracted tools. Recheck
compatibility on configuration changes; do not infer account eligibility from
public documentation. A provider without the required controls is unavailable for
that data, even if public work can use it.

Current calls set `store: false`; this is not verified Zero Data Retention. OpenAI
documents separate abuse-monitoring retention, approval requirements for additional
controls, and endpoint/feature limitations. API data is not used for training by
default unless sharing is opted into. Training use, retention and permission to
send data are separate questions. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

## Current gaps and implementation order

The review found useful tenant/owner checks, encrypted credential/browser-state
storage, disabled SDK tracing, bounded audit detail fields and brokered provider
keys. It did not verify deployment volumes, backup encryption, operator controls,
provider account settings or contracts.

| Confirmed gap | Required change |
| --- | --- |
| Work config, chat, owner answers, browser observations and cached results use ordinary database TEXT/JSON | Protect content across existing and new paths, with migration and retention policy |
| Hosted search shares the complete work context | Separate public/released research from private analysis; enforce disclosure before outbound calls |
| Worker auth is a shared bearer plus caller-supplied task identifiers | Issue verifiable expiring run/slice authority and receipt-only late-result authority |
| Browser initial URL checks do not establish method/domain limits for all page traffic | Isolate public contexts and constrain authenticated adapters; do not claim unrestricted browsing is read-only |
| No general work-content deletion lifecycle was found | Add retention, derivative invalidation, backup/provider handling and deletion evidence |

Implement scope/policy/content interfaces in the first runtime package, before
persisting new checkpoints. Prove them with fake adapters. Add protected storage,
context manifests, worker identity and egress enforcement before confidential live
execution. Apply policy to existing assistant and workflow paths too; protecting
only the new runtime would leave bypasses. Legacy content migration needs an
explicit restrictive policy and must not silently classify existing data as public.

Minimum security evidence: cross-tenant and same-owner cross-run reference probes;
forged/expired worker scope; revocation during a call and stale-checkpoint resume;
malicious evidence trying to export a private canary via search/URL/link; compaction
that retains restrictions; browser subrequest policy; absence of sensitive content
in logs/queues; encrypted payload/backup inspection; and deletion/restore that does
not resurrect access. Browser/UI checks cover inert rendering and remote image/link
behavior. These checks establish specific controls, not a claim that prompt
injection or host compromise is impossible.
