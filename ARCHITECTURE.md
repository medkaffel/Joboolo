# Joboolo Architecture — Talent Stream Reference

**Status:** Canonical architecture reference  
**Architecture style:** Modular Monolith (FastAPI + MongoDB)  
**Strategic product:** Talent Stream  
**Applies to:** Talent Stream Phases A through E

> This file defines architectural boundaries and sequencing. It does not authorize out-of-scope implementation. The active GitHub issue is always the only authorized implementation scope.

---

## 1. Architecture goals

Joboolo must evolve from its current job-board-oriented backend into a Talent Platform without introducing premature microservices or distributed-system complexity.

Primary goals:

1. Make Talent Stream the signature product without coupling it permanently to `job_id`.
2. Reuse the current FastAPI/MongoDB application while creating clear domain boundaries.
3. Separate professional Match, Intent, Trust and Permission.
4. Preserve strict CV/document access control.
5. Allow own-job, reference-job, external-job and free-text sourcing to converge to one canonical Stream Requirement.
6. Make derived ranking/projection data reconstructible.
7. Make sensitive actions idempotent, auditable and authorization-checked at action time.
8. Build Cross-Offer Intent without exposing competitor-source behavior.
9. Protect Joboolo’s reputation by making privacy/trust mechanisms part of the product architecture, not post-processing.

---

## 2. Chosen architecture style

### Modular Monolith

Keep one deployable backend for now.

Do **not** introduce microservices merely to create conceptual separation.

Reasons:

- current product maturity does not justify distributed-system cost;
- MongoDB transactions/outbox/workers are sufficient for current workflows;
- one codebase simplifies atomic authorization and privacy changes;
- modular boundaries can be extracted later if scale and organization justify it.

Target conceptual modules:

```text
backend/
  domains/
    profiles/
    roles/
    opportunities/
    matching/
    intent/
    talent_stream/
    trust/
    permissions/
    privacy/
    analytics/
  integrations/
    ats/
    partner_feeds/
    payments/
    notifications/
  workers/
  routes/
```

This is a progressive target. Do not perform a global file move/refactor unless a dedicated issue explicitly authorizes it.

---

## 3. Bounded contexts

### profiles

Owns:

- Candidate Professional Profile;
- Candidate Preferences;
- Discovery State;
- candidate profile/preference versioning.

Does not own recruiter authorization or Talent Stream ranking.

### roles

Owns:

- Role DNA;
- occupation/skill taxonomy;
- role normalization;
- role similarity inputs;
- Role Clusters as derived data.

### opportunities

Owns:

- Opportunity Specification;
- job/need-specific constraints;
- Stream Requirement composition from Role DNA + Opportunity Specification.

### matching

Owns:

- Professional Match;
- hard eligibility filters;
- Opportunity Fit;
- reason codes;
- match engine versioning.

Does not own candidate consent or recruiter trust.

### intent

Owns:

- intent event contract;
- event provenance;
- Job Intent;
- Role Intent;
- Company Intent;
- Market Intent;
- recency/aggregation;
- intent engine versioning.

Does not grant recruiter access to the candidate.

### talent_stream

Owns:

- Stream aggregate/lifecycle;
- retrieval orchestration;
- Stream Requirement binding;
- candidate projections/read models;
- contact request orchestration;
- introductions.

Talent Stream consumes Match/Intent/Trust/Permission outcomes; it must not redefine them locally.

### trust

Owns:

- organization/company verification;
- recruiter verification;
- organization membership;
- recruiting mandates;
- source protection;
- Contact Governor policy inputs;
- recruiter eligibility.

### permissions

Owns:

- candidate discovery authorization;
- scoped grants;
- exclusions;
- current authorization decision;
- profile versus identity versus CV scope.

A projection snapshot is never an authorization source of truth.

### privacy

Owns:

- retention;
- revocation/expiry semantics;
- privacy-safe anonymous rendering policy;
- anonymization/redaction;
- audit policy;
- deletion/anonymization lifecycle.

### analytics

Owns:

- Talent Stream funnel metrics;
- recruiter/market aggregates;
- quality and conversion metrics;
- derived reporting models.

Analytics data must not become an alternate authorization path.

---

## 4. Core domain relationships

### Candidate side

```text
Candidate
  ├── Professional Profile
  ├── Preferences
  └── Discovery State
```

### Recruiter need side

```text
Need Source
  ├── Own Job
  ├── Reference Job
  ├── External Job (later)
  └── Natural Language Need
        ↓
      Role DNA
        +
  Opportunity Specification
        ↓
  Stream Requirement
```

### Evaluation side

```text
Professional Profile ↔ Role DNA
        = Professional Match

Candidate Preferences ↔ Opportunity Specification
        = Opportunity Fit
```

### Talent Stream orchestration

```text
Stream Requirement
      │
      ├── Discovery Retrieval
      └── Intent Retrieval
              │
              ↓
      Professional Match
              ↓
      Hard Eligibility
              ↓
      Opportunity Fit
              ↓
      Evidence/Provenance Policy
              ↓
      Source Protection
              ↓
      Trust
              ↓
      Current Permission
              ↓
      Contact Governor
              ↓
      Stream Projection / Contact Request
```

---

## 5. Critical architectural separation

The following dimensions must remain separately queryable and explainable:

- Professional Match;
- Opportunity Fit;
- Job Intent;
- Role Intent;
- Company Intent;
- Market Intent;
- Recruiter Trust;
- Candidate Permission;
- Source Protection state;
- Contact eligibility.

Do not create one authoritative opaque `talent_score` that replaces these concepts.

An internal ordering/ranking function may combine factors, but underlying components and reason codes must remain available.

---

## 6. Discovery and Intent are parallel retrieval paths

Talent Stream must not require recent intent for every talent.

### Discovery path

```text
Discovery enabled
  + Professional Match
  + Opportunity Fit
  + Trust/Permission
```

### Intent path

```text
Eligible Role/Market Intent
  + Professional Match
  + Opportunity Fit
  + provenance/source policy
  + Trust/Permission
```

Both paths converge before recruiter contact.

---

## 7. Authoritative data versus projections

### Authoritative / source-of-truth collections

Target conceptual collections:

- `candidate_profiles`
- `candidate_preferences`
- `role_dnas`
- `opportunity_specs`
- `talent_streams`
- `talent_intent_events`
- `talent_stream_contact_requests`
- `talent_stream_grants`
- `organizations` or equivalent canonical company/organization representation
- `organization_memberships`
- `recruiter_verifications`
- `recruiting_mandates`
- `source_protection_records` where persistence is required

### Derived / reconstructible collections

- `role_clusters`
- `role_intent_aggregates`
- `talent_stream_candidates`
- `market_intelligence_aggregates`

A read model must never become the sole source of truth for permission, trust or consent.

---

## 8. Stream candidate projection

A future `talent_stream_candidates` projection may contain fields such as:

```text
stream_id
candidate_id
candidate_profile_version
candidate_preferences_version
role_dna_version
opportunity_spec_version
match_engine_version
intent_engine_version
policy_version

professional_match
opportunity_fit
role_intent
market_intent

eligibility_state
visibility_hint
reason_codes

permission_snapshot_id
trust_snapshot_id

computed_at
expires_at
```

Important:

- snapshots support audit/explanation;
- current authorization is recalculated before a sensitive action;
- do not duplicate unnecessary email, phone, CV or exact sensitive attributes in projections.

---

## 9. Authorization architecture

Sensitive actions include at least:

- reveal identity;
- reveal detailed profile;
- access/download CV;
- request introduction;
- send recruiter-to-candidate message;
- expose contact information.

Canonical pattern:

```text
Requested action
      ↓
Current candidate state
Current grant state
Current exclusions
Recruiter/company/mandate state
Source protection state
Contact Governor state
      ↓
Central policy decision
      ↓
ALLOW / DENY
```

Never authorize from a cached Stream projection alone.

---

## 10. Existing CV ACL integration

The current restrictive document access model must remain the baseline.

Target policy extension:

```text
ALLOW CV IF
  owner
  OR admin
  OR exact authorized application relationship
  OR active scoped Talent Stream CV grant
```

Never introduce `if employer: allow` or an equivalent broad recruiter bypass.

Profile access and CV access are distinct permissions.

---

## 11. Organization and recruiter model

Talent Stream requires more than a user role such as `employer`.

Canonical concepts:

```text
User
  ↓
Organization Membership
  ↓
Recruiter Verification
```

Agency/RPO case:

```text
Recruiting Organization
  ↓
Recruiting Mandate
  ↓
Hiring Company
```

A Stream should be capable of distinguishing:

- `recruiter_user_id`;
- `requesting_organization_id`;
- `hiring_company_id`;
- `mandate_id` when applicable.

---

## 12. Intent event architecture

CPC/billing click events and candidate intent events are separate domains.

Do not add Talent Stream identity semantics directly to the CPC ledger.

Future intent event envelope should conceptually support:

```text
event_id
schema_version
candidate_id or allowed pseudonymous identifier
event_type
occurred_at
job_id
role_dna_id
source_type
source_organization_id
source_campaign_id
consent_context
privacy_context
retention_until
created_at
```

Provenance may be stored internally to apply source protection. It must not be exposed to recruiters as competitor intelligence.

---

## 13. Event/outbox strategy

Do not introduce Kafka or microservices in the initial Talent Stream phases.

Preferred pattern:

```text
MongoDB transaction where required
  + domain event/outbox record
  + idempotent worker
```

Examples of async work:

- recompute affected Streams;
- Role DNA enrichment;
- Role Cluster refresh;
- Intent aggregation;
- analytics rollups.

The action “candidate is eligible for a Stream” and the action “send an invitation” must remain separate operations.

---

## 14. Idempotency requirements

Sensitive commands must be designed to tolerate retries.

Examples:

- record/process intent event;
- refresh/recompute Stream;
- create contact request;
- accept/decline contact request;
- create/activate/revoke grant;
- consume accepted-introduction credit;
- process ATS callback.

Retries must not produce duplicate invitations, duplicate grants, duplicate charges or duplicate canonical events.

Use explicit unique/idempotency keys where appropriate.

---

## 15. Versioning

Version at minimum where applicable:

- candidate professional profile;
- candidate preferences/discovery state;
- Role DNA;
- Opportunity Specification;
- Match Engine;
- Intent Engine;
- authorization/privacy policy;
- consent policy/text;
- event schema.

A Stream binds to a version/snapshot of its requirement.

A source job changing later must not silently redefine an existing Stream. Updating a Stream requirement is an explicit operation.

---

## 16. Matching architecture

The existing LLM-based matching may remain available during migration.

Target authoritative Talent Stream matching should combine:

- structured fields;
- normalized role/skill taxonomy;
- embeddings/semantic similarity where useful;
- deterministic hard filters;
- explicit scoring/reason codes;
- LLM enrichment and human-readable explanation as supporting functionality.

The LLM must not be the sole source of truth for:

- hard eligibility;
- recruiter authorization;
- candidate permission;
- CV access;
- final Role Similarity;
- Cross-Offer source-protection decisions.

---

## 17. Anonymous Talent architecture

Removing a name is not sufficient anonymization.

Anonymous recruiter cards require a privacy/redaction policy that may generalize or remove:

- exact location;
- exact current employer;
- rare identifying credentials;
- unusual combinations of attributes;
- overly precise experience details.

Market analytics should also apply minimum cohort thresholds where small segments could reveal individuals.

---

## 18. Role Similarity and Cross-Offer boundary

Cross-Offer is implemented in two distinct stages.

### Internal retrieval

The backend may compute that a candidate is relevant to a similar role.

### Recruiter exposure

The candidate must not appear in recruiter-facing Cross-Offer results until all of the following are satisfied:

- Independent Signal Rule;
- origin neutralization;
- Source Protection;
- candidate Cross-Offer/discovery permission;
- recruiter/company trust;
- exclusions;
- Contact Governor;
- Opportunity Fit as required.

Internal relevance is not authorization to expose.

---

## 19. Index and migration strategy

Do not put all future Talent Stream schema/index changes into startup mutation code.

Rules:

- startup-safe non-destructive index creation may remain acceptable for simple cases;
- sensitive unique indexes require explicit migration/preflight;
- migrations must handle existing data safely;
- startup must fail safely when a required invariant is not met;
- TTL indexes are cleanup mechanisms only.

Example:

If `grant.expires_at` has passed, authorization must deny immediately even if MongoDB’s TTL monitor has not physically removed the document.

---

## 20. Phase architecture

### Phase A — Talent Engine & Trust Foundation

Canonical work areas:

- A0 domain contracts, versioning, idempotency and migration strategy;
- candidate professional profile;
- preferences/discovery;
- Role DNA;
- Opportunity Specification;
- Match Engine v2;
- hard eligibility / Opportunity Fit v1;
- organization verification;
- recruiter membership/mandate;
- authorization/grants;
- privacy lifecycle;
- intent event/provenance contract;
- audit/reason codes.

### Phase B — Talent Stream MVP

Use only safe sources initially:

- applications;
- “I’m interested”;
- explicitly shared favorite;
- Discovery Pool.

Then:

- Stream aggregate;
- candidate projection;
- privacy-safe anonymous cards;
- Contact Governor;
- contact request;
- candidate accept/decline;
- current authorization check;
- progressive reveal;
- CV grant;
- messaging adapter;
- analytics.

### Phase C — Cross-Offer Intent & Moat

- Role Similarity;
- Role Clusters;
- observed intent;
- four intent dimensions;
- internal Cross-Offer retrieval;
- provenance/evidence evaluation;
- Independent Signal Rule;
- origin neutralization;
- Source Protection;
- Cross-Offer permission;
- Contact Governor v2;
- safe recruiter projection;
- Opportunity Fit v2;
- Salary Intelligence / Semantic Search / Rediscovery / AI governance as parallel multipliers.

### Phase D — No-Posting Talent Stream

- own job as template;
- another Joboolo job as role model;
- natural-language requirement;
- one common no-posting wizard;
- confidential Stream;
- market preview;
- later safe external URL -> Role DNA;
- commercial packaging.

### Phase E — Intelligence & Scale

Parallel tracks:

- Recruiter OS / CRM;
- ATS/postback/webhook network;
- Market & Salary Intelligence;
- Skills/Career Graph;
- Candidate Agent and candidate tools;
- employer experience.

---

## 21. Gates

### G0 — Baseline

Current Joboolo baseline/security integrity is stable enough to begin Talent Stream foundations.

### GA — Talent Engine & Trust Ready

Requires, at minimum:

- canonical profile/preferences/discovery;
- Role DNA and Opportunity Specification;
- explainable Match;
- organization/recruiter/mandate model;
- grants/authorization;
- privacy lifecycle;
- CV ACL preserved;
- intent contract/provenance;
- audit/versioning.

### GB — Talent Stream MVP Ready

Requires end-to-end controlled flow from verified recruiter/own need through candidate retrieval, Contact Governor, candidate decision, grant, optional CV and messaging.

No observed Cross-Offer behavior is recruiter-visible yet.

### GC — Cross-Offer Safe & Effective

Requires Role Clusters/Intent plus all source/privacy/trust/anti-spam safeguards before recruiter exposure.

### GD — No-Posting Ready

Own job, another allowed Joboolo job and natural language all converge to the same Stream Requirement and Talent Stream engine. External URL is layered safely.

### GE — Platform & Scale Ready

Integrations, observability, reliability, intelligence and ecosystem capabilities meet platform-grade requirements.

---

## 22. Dependency rules

Preferred high-level dependency direction:

```text
profiles ──────┐
roles ─────────┼──> matching ─────┐
opportunities ─┘                  │
                                  ├──> talent_stream
intent ───────────────────────────┤
trust ────────────────────────────┤
permissions ──────────────────────┤
privacy ──────────────────────────┘

analytics consumes domain events/read models but does not grant permissions.
```

Avoid circular dependencies such as:

- `talent_stream -> permissions -> talent_stream`;
- `talent_stream -> matching -> talent_stream`;
- `trust -> talent_stream -> trust`.

Use domain-neutral IDs/contracts/events where a dependency inversion is needed.

---

## 23. Route/service rule

FastAPI route handlers should progressively become thin adapters.

Do not place long-lived Talent Stream business policy directly inside HTTP route functions.

Preferred separation:

```text
route
  ↓
application/domain service
  ↓
policy / repository / domain model
```

This must be introduced incrementally; no global rewrite without a dedicated issue.

---

## 24. Development governance

All Talent Stream lots follow:

```text
GitHub issue
  ↓
OpenCode PLAN (read-only)
  ↓
ChatGPT architecture review
  ↓
OpenCode BUILD on workflow-owned branch
  ↓
Tests
  ↓
ChatGPT PR review
  ↓
Explicit merge decision
```

OpenCode must read `TALENT_STREAM_SPEC.md`, `ARCHITECTURE.md` and `BUSINESS_RULES.md` for all Talent Stream Phase A-E work.

The issue scope always wins over the broader roadmap: documentation explains the target system, but an agent must never implement a future phase merely because it is described here.
