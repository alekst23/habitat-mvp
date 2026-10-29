# Public research inside AICL

Status: local web-access policy and public-only research implementation, October
27, 2026. This is not a claim of whole-application AICL compliance. Apply the
[project ethos](../../AGENTS.md#aicl-ethos) and the existing
[data trust contract](agent-data-trust.md).

## Owner controls

The owner chooses **Off**, **Only selected sites**, **All except selected sites**,
or **All public sites**, separately for **Web search (Brave Search)** and
**Web access (page reads)**. The two list modes accept domains and include their
subdomains. Public HTTPS, address validation and transport restrictions apply to
every level; “all” never enables private networks, credentialed browsing or uploads.
Search and page permissions are independent: finding a result does not authorize
opening it. Search site rules filter results; page site rules control requests to
websites. The UI does not require manual queries or source URLs. Old bundled
policies retain their original scope until edited; loading a workspace never
rewrites its approval or grants.

Applying enabled access explicitly releases the visible **goal** for public
research. Context/inputs, files, conversation history, internal IDs and analysis
outputs are excluded. The owner reviews the same goal they already entered; no
separate duplicate research brief is required. Changed goal, access scope or
recipient contract needs a fresh digest-bound approval. Editing a draft never
grants authority. Historical exact-query releases remain exact; selecting and
approving a new level is required to widen them, and Off revokes them.

## Enforced execution

- Before private analysis, a fresh research planner receives only the approved
  goal, destination policy and filtered public evidence. It chooses focused
  searches and useful pages. The context is constructed by a trusted service;
  private model output and owner follow-up messages cannot add hidden inputs.
- The planner uses a fixed bounded inference adapter, no provider-native tools,
  stored conversation, retries or model-selected credentials. Its processor/model
  contract is included in the owner release. The private task model has no public
  web tools. A new public goal requires review and a new run.
- `research_policy.py` checks current scoped grants and seals each proposed
  request. `research_service.py` owns run binding, public context and reservations.
  `research_broker.py` alone dispatches network requests. It checks policy before
  DNS and HTTP, pins public IP addresses, and denies redirects, cookies, arbitrary
  headers/bodies, scripts and subresources. No application identifiers are added
  to outbound headers or URLs.
- Search-result domains are filtered by the search policy before further planning
  or private analysis; page destinations independently pass the page access policy.
  Provider-side domain scoping supplements these local checks and cannot replace
  them. Neither source text nor planner output can alter policy or release data.
- Public-response parsing and exact-plan verification run inside inspected Docker
  containers using an immutable local image, no network, mounts, credentials,
  capabilities or writable root. The trusted network and inference adapters stay
  outside those workers. This is not a claim that the existing private inference
  path or the entire server is sandboxed.
- Public page evidence preserves bounded article-link candidates, without opening
  them. Candidates are filtered by the site policy, remain untrusted evidence,
  and require fresh AICL authorization before any request. A later public planning
  round can follow relevant links or choose an alternative to an inaccessible page.
- Each public phase permits at most three planning calls, two raw Brave searches,
  and five page requests. The upper bound is reserved before any call: 48,000
  input tokens, 4,500 output tokens and two $0.005 searches, currently **$0.151**.
  That reservation is a ceiling, not a charge. Measured usage settles once; a
  durable one-shot claim prevents replay. Known failures settle known usage.
  Unknown provider outcomes retain their hold and cannot be retried automatically.
  The v2 planner contract requires renewed owner approval for existing agent-mode
  releases. Private analysis receives the saved research and its completion status;
  it cannot initiate another research phase or send private feedback to the planner.
  Search Off reserves no search calls and cannot dispatch them. Page access Off
  prevents opening search results. The disabled feature's remaining action count
  is zero in public planning and the gate independently rejects that action kind.

A destination grant permits contacting public resources for the approved task;
GET alone cannot prove a remote endpoint has no side effects. This design protects
private context through separation, rather than trusting a model to sanitize it.
Broader processor policy, secure production storage and whole-application compute
containment remain separate milestones.

### Provider search scoping

Selected and excluded domains become deterministic inline Brave Goggles rules;
the model's query remains unchanged. Allowlist rules use a generic discard plus
site boosts, while blocklist rules use site-specific discards. Only normalized
owner domains enter the fixed rule templates. No model-supplied DSL, hosted rule
URL, account identifier or metadata is accepted. The scope contract is included
in the approval binding. Brave documents these [inline rules](https://api-dashboard.search.brave.com/documentation/resources/goggles)
and the [allowlist pattern](https://github.com/brave/goggles-quickstart/blob/main/getting-started.md#how-can-i-exclude-any-result-not-matched-by-my-goggle);
its [CLI documentation](https://github.com/brave/brave-search-cli#why-agents-should-use-goggles)
also describes converting `site:` operators into Goggles. Local URL filtering is
authoritative for exact hosts and their subdomains, even if provider filtering
returns an out-of-policy result.

Queries retain the provider's 600-character/75-word limit. The complete encoded
search URL also has a 6,000-character bound, including domain rules. The public
planner receives the remaining encoded query budget; an oversized proposal is
rejected before DNS or search dispatch. A long domain list can therefore require
a shorter query. Any preceding measured planning usage still settles normally.

### Provider security explanation

The UI names Brave Search and describes AICL's actual protections: HTTPS requests
through the broker, current owner site rules and spending limits, public-goal-only
planning, and untrusted search results. It links Brave's
[security documentation](https://api-dashboard.search.brave.com/documentation/resources/security),
which reports SOC 2 Type II attestation. This provider attestation does not certify
Habitat or make retrieved content trustworthy. Brave's
[API privacy notice](https://api-dashboard.search.brave.com/app/documentation/general/privacy-policy)
allows query retention for up to 90 days and offers zero retention for enterprise
clients; the UI does not assume the configured account has that option.

## Operator configuration

The local launcher accepts `--research-worker-image sha256:<local-image-id>`.
Use a reviewed local Python 3.12 image; the application never pulls an image.
Without verified containment, public research is unavailable. Agent-directed
access requires both the raw search connection and the inference connection.
Legacy exact-page releases can still operate without a search connection.

Search additionally requires `--search-key-file /absolute/private/brave.env`,
`--search-account <operator-account-label>` and
`--search-credential-binding <credential-version>`. The mode-0600 file contains
one literal `BRAVE_SEARCH_API_KEY=...` entry. Do not paste credentials into chat.
The account label identifies the operator's secret slot, not a provider-verified
account identity. Key rotation also changes a keyed internal fingerprint, so old
approvals cannot silently authorize a replacement credential.
Environment equivalents are `BRAVE_SEARCH_API_KEY`, `AICL_RESEARCH_WORKER_IMAGE`,
`AICL_RESEARCH_PROVIDER_ACCOUNT`, and `AICL_RESEARCH_CREDENTIAL_BINDING`.

Provider configuration selects the local operator account. Verification uses
offline fixtures and does not send paid search or inference requests. The Brave
adapter is replaceable; changes to its approved binding and price contract still
require owner review.

## What the withdrawn implementation missed

The former `web.search` adapter checked identity, lifecycle, tool grants, and funding,
but makes its own provider request and holds the provider key. It does not pass
through the shared destination/disclosure/credential boundary. Its bounded query
is model-generated from potentially private context; length is not a release rule.
Hosted search makes further queries or retrieval decisions without a Habitat
checkpoint before each request. The reservation is an estimate, not an enforceable
aggregate cost maximum. Treat this path as noncompliant with the project ethos.

Existing `web.read` has useful exact-host, public-address, DNS-pinning, redirect,
cookie, and response-size controls. It still permits arbitrary paths and queries
on approved domains. That is SSRF protection, not permission to disclose data.
Merely routing search through the old gate is insufficient: it lacks a search
destination policy, content-disclosure policy, and a real general-purpose broker.

## One authorization and execution boundary

All UI actions, embedded assistant tools, scheduled workers, and adapters submit
typed proposals to the same AICL authorization service:

```text
Scoped proposal + data/context lineage + current owner policy
    -> authorize operation, recipient, purpose, and disclosed data
    -> bind exact request + policy versions + deadline + idempotency + cost hold
    -> broker rechecks authority, injects credentials, and executes
    -> protected receipt, actual usage, and durable continuation
```

Reuse the current identity, grant, budget, confirmation, and accounting contracts;
extend them instead of creating another tool-specific gate. Authorize recipients
and provider account/resource identity as well as host, method, and endpoint.
The broker constructs the final request from typed fields and immutable content
references; adapters cannot substitute arbitrary URLs, headers, bodies, or keys.
This includes broker/SDK-added telemetry, tracing headers, diagnostics, and provider
history/continuation state. Private tenant/run identifiers cannot be appended after
the disclosure check; permit only the metadata explicitly required by the approved
provider contract. Keep private histories and caches out of public research.
Resolve internal source/content references inside AICL; never forward them as
external tracking identifiers.
Redirects and retries require new checks. A request bound to one approval cannot
change after authorization. Revocation blocks new dispatch, not an already sent
request or its necessary accounting receipt.

Workers and arbitrary tool code must lack direct public sockets, DNS, provider
keys, and unrelated filesystem mounts. Only designated brokers can reach approved
services. This needs process/network isolation, not just a Python convention.
If an execution environment cannot prove that containment, the corresponding live
capability stays unavailable. Static dependency checks supplement enforcement.

## Useful search without unrestricted disclosure

1. **Owner-approved public brief.** A visible, versioned research brief defines
   what may leave the workspace, the approved provider, purpose, scope, and limits.
   For an AI digest, this can be public topics and a time range. Do not include
   account/run identifiers, private chat history, internal files, or diagnostics.
   Standing grants permit routine work within scope; changed disclosures need
   a policy-authorized deterministic release or specific owner approval.
2. **Separate research context.** A research worker receives only that released
   brief and public evidence, with fresh provider history/cache scope. Private
   analysis can consume its findings but has no public egress tools. Outputs of
   private/mixed contexts inherit their input restrictions, even if the model
   calls them sanitized. Do not allow private context to steer public queries or
   URL selection through an unreviewed side channel.
3. **Application-owned search.** A search broker sends the exact authorized query
   to an approved search API/index with known bounded pricing and receives raw
   results. It does not give a hosted model an autonomous search/fetch loop.
   Provider selection and configuration remain a separate implementation decision.
4. **Controlled retrieval.** The model selects scoped source references, not
   freely rewritten URLs. AICL resolves and checks the complete address, provenance,
   endpoint behavior, and disclosure before any DNS or HTTP operation. References
   identify candidates; they do not grant authority. Prefer exact URLs independently
   observed by a public index, with owner-controlled exceptions for other sources.
   Never send a suspicious URL to an external checker to discover whether it is safe.
5. **Constrained reads.** Preserve public-IP checks and DNS pinning. Authorize
   every redirect; disallow ambient cookies, referrers, model-controlled headers,
   arbitrary bodies, uploads, scripts, and subresources in the initial research
   profile. GET alone does not prove a request is harmless; endpoint profiles
   must exclude action/collection endpoints. Future browsing must mediate every
   page-initiated request, including images, frames, workers, and WebSockets.

URL provenance, domain lists, query restrictions, secret scanners, and classifiers
reduce risk but do not prove confidentiality individually. Public URL choices,
request timing, and encoded data can still carry information. Context separation
and authorized release are the main information-flow boundary. Public retrieval
still reveals the approved research interest and request metadata; disclose this
to the owner rather than promise anonymous or leak-proof browsing.

## Concrete attack outcomes required

| Attempt | Required AICL result |
| --- | --- |
| A page requests a diagnostic upload | Page text grants nothing; research has no private-file access or upload capability. |
| Identifier embedded in URL path, query, hostname, header, or search terms | Unreleased data cannot enter public research; reject unbound request fields before DNS or HTTP. |
| Upload to an attacker's account on an approved provider domain | Deny wrong account/resource, method, payload, or credential binding. Domain approval is insufficient. |
| Redirect, shortener, telemetry, image, or link preview used as a relay | Reauthorize or suppress the secondary request; no automatic output rendering or preview fetch bypass. |
| Private analyst selects public URLs to encode private information | No public tool path from private context; require an authorized release into a new research brief. |
| Hosted tool makes hidden follow-up requests | Unavailable under the per-request AICL profile unless every effect can be mediated. |
| Permission changes after approval or a response is lost | Recheck before dispatch; preserve unknown holds and never blindly retry paid work. |

## Acceptance and sequence

First withdraw the noncompliant live search path from availability while preserving
saved drafts, receipts, and charges. Then implement the shared request/disclosure
contract and broker, a public research profile, and UI controls exposing the
approved brief and actual boundaries. Audit inference and existing page-reading
paths too; the new policy must not apply only to search.

Use adversarial fixtures with canary private data and observed outbound traffic:
same-host and encoded URL leaks, search-query leaks, diagnostic uploads, hostile
credentials, DNS/redirect tricks, remote previews, private-to-public context
contamination, stale grants, request substitution, unknown outcomes, and cost
overruns. Tests must assert that prohibited traffic never leaves the boundary,
even when the model follows the injected instruction. Prove network containment
in the actual execution environment before enabling it; mock tests alone do not.

## Supporting research

- [OpenAI, URL-based exfiltration and independently observed public URLs](https://openai.com/index/ai-agent-link-safety/), January 28, 2026.
- [Oasis Security, Claudy Day](https://www.oasis.security/blog/claude-ai-prompt-injection-data-exfiltration-vulnerability): an approved provider domain was used to upload to an attacker-controlled account.
- [Anthropic, unintended model actions](https://www.anthropic.com/research/investigating-unintended-model-actions), October 9, 2026: observed URL-shortener workarounds and unintended website actions.

These reports motivate controls; they do not establish that Habitat implements
them or that prompt injection can be eliminated.
