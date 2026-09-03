# Joboolo Architecture — Talent Stream Reference

**Status:** Canonical architecture reference  
**Version:** 1.1  
**Last architecture review:** 2026-09-03  
**Architecture style:** Modular Monolith (FastAPI + MongoDB)  
**Strategic product:** Talent Stream  
**Applies to:** Talent Stream Phases A through E

> This file defines architectural boundaries, dependencies, sequencing and Gates. It does not authorize out-of-scope implementation. The active GitHub issue/PR is always the only authorized implementation scope.

---

## 1. Architecture goals

Joboolo must evolve from its current job-board-oriented backend into a Talent Platform without introducing premature distributed-system complexity.

Primary goals:

1. Make Talent Stream the signature product without coupling it permanently to `job_id`.
2. Reuse the current FastAPI/MongoDB application while creating clear domain boundaries.
3. Separate Professional Match, Opportunity Fit, Discovery, Intent, Trust and Permission.
4. Preserve strict CV/document access control.
5. Allow own-job, reference-job, external-job and free-text sourcing to converge to one canonical Stream Requirement.
6. Make ranking/projection data reconstructible.
7. Make sensitive actions idempotent, auditable, versioned and authorization-checked at action time.
8. Build Cross-Offer Intent without exposing competitor-source behavior.
9. Treat privacy, recruiter fairness and anti-spam as architecture, not post-processing.
10. Support passive/open candidates via Discovery Pool without requiring recent intent.

---

## 2. Program model: Circles, Phases and Gates

These are complementary axes.

### Circles = strategic proximity to Talent Stream

| Circle | Meaning | Examples |
|---|---|---|
| **C0 — Signature** | Talent Stream core behavior | Stream, introductions, Cross-Offer, No-Posting |
| **C1 — Vital foundation** | Required for quality/safety | Role DNA, Profile, Match, Trust, Permission, Privacy, Opportunity Fit |
| **C2 — Multipliers** | Strongly increases Talent Stream value | Recommendations, Analytics, Market Intelligence, Semantic Search, Rediscovery, Responsible AI, ATS |
| **C3 — Ecosystem expansion** | Extends the talent network | CRM, Reverse Marketplace, Skills Passport, Skill Gap, Candidate Agent, Train-to-Hire |
| **C4 — Peripheral workflow** | Useful but must not delay signature path | CV Assistant, Interview Coach, Employer Pages, Scheduling, WhatsApp/QR, job-writing copilot |

Circle is **not** implementation order by itself.

### Phases = construction sequence

- **Phase A — Talent Engine & Trust Foundation**
- **Phase B — Talent Stream MVP**
- **Phase C — Cross-Offer Intent & Moat**
- **Phase D — No-Posting Talent Stream**
- **Phase E — Intelligence & Scale**

### Gates = permission to progress

- **G0** — Baseline
- **GA** — Talent Engine & Trust Ready
- **GB** — Talent Stream MVP Ready
- **GC** — Cross-Offer Safe & Effective
- **GD** — No-Posting Ready
- **GE** — Talent Platform Ready

Macro phases are sequential at Gate level, but independent lots inside a phase may execute in parallel after their dependencies are satisfied.

---

## 3. Chosen architecture style

### Modular Monolith

Keep one deployable backend for now.

Do **not** introduce microservices merely to create conceptual separation.

Reasons:

- current maturity does not justify distributed-system cost;
- one codebase simplifies atomic authorization/privacy changes;
- MongoDB transactions/outbox/workers are sufficient for current workflows;
- modular boundaries can later be extracted if scale and organization justify it.

Target conceptual structure:

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
    recruiter_os/
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

Routes should progressively become thin HTTP adapters; domain logic should not be duplicated across routes.

---

## 4. Bounded contexts

### profiles
Owns Candidate Professional Profile, Candidate Preferences, Discovery State and their versioning.

### roles
Owns Role DNA, occupation/skill taxonomy, role normalization, role-similarity inputs and Role Clusters as derived data.

### opportunities
Owns Opportunity Specification, job/need-specific constraints and composition of Stream Requirement from Role DNA + Opportunity Specification.

### matching
Owns Professional Match, hard eligibility, Opportunity Fit, reason codes and match-engine versioning. Does not own permission/trust.

### intent
Owns intent event contracts/provenance, Job/Role/Company/Market Intent, recency/aggregation and intent-engine versioning. Discovery is **not** owned here.

### talent_stream
Owns Stream aggregate/lifecycle, retrieval orchestration, Stream Requirement binding, candidate projections/read models, contact-request orchestration and introduction lifecycle. It consumes policy outcomes; it must not redefine Match, Trust or Permission locally.

### trust
Owns organization/company verification, recruiter verification, memberships, recruiting mandates, source protection, Contact Governor policy/state and recruiter eligibility.

### permissions
Owns discovery/contact authorization, scoped grants, company/employer exclusions and current authorization decisions. Cached projection state is never the authorization source of truth.

### privacy
Owns retention, expiry/revocation semantics, anonymous rendering/redaction, re-identification safeguards, deletion/anonymization lifecycle and privacy/audit policy.

### recruiter_os
Owns application/pipeline/CRM workflow integrations once a relationship is authorized. Existing application semantics remain preserved.

### analytics
Owns Talent Stream funnel, market/trust aggregates, quality metrics and derived reporting. Analytics must never become an authorization bypass.

---

## 5. Allowed dependency direction

Preferred dependency direction:

```text
profiles ───────┐
roles ──────────┼──> matching ───────┐
opportunities ──┘                    │
                                     │
intent ──────────────────────────────┤
trust ───────────────────────────────┤
permissions ─────────────────────────┤──> talent_stream ──> recruiter_os
privacy ─────────────────────────────┤
analytics <──────── events/projections┘
```

Avoid circular dependencies such as:

- `talent_stream -> matching -> talent_stream`;
- `permissions -> talent_stream -> permissions`;
- `trust -> routes -> trust`.

Shared primitive IDs/value objects may live in a small neutral shared layer when necessary; do not create a giant “common” module that becomes a dumping ground.

---

## 6. Core domain relationships

### Candidate

```text
Candidate
  ├── Professional Profile
  ├── Preferences
  └── Discovery State
```

### Recruiter need

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

### Evaluation

```text
Professional Profile ↔ Role DNA
        = Professional Match

Candidate Preferences ↔ Opportunity Specification
        = Opportunity Fit
```

### Retrieval paths

```text
DISCOVERY PATH
Discovery enabled
  + Match/Fit

INTENT PATH
Eligible Role/Market Intent
  + Match/Fit
  + provenance/source policy
```

Both converge into Trust, current Permission, Contact Governor and recruiter-facing projection.

---

## 7. Talent Stream policy pipeline

Canonical orchestration:

```text
Stream Requirement
      │
      ├── Discovery Retrieval
      └── Intent Retrieval
              │
              ▼
      Professional Match
              ▼
      Hard Eligibility
              ▼
      Opportunity Fit
              ▼
      Evidence/Provenance Policy
              ▼
      Independent Signal Rule (Cross-Offer)
              ▼
      Origin Neutralization / Source Protection
              ▼
      Recruiter/Organization Trust
              ▼
      Current Candidate Permission / Exclusions
              ▼
      Contact Governor
              ▼
      Privacy-safe Stream Projection
              ▼
      Contact Request
              ▼
      Candidate Decision
              ▼
      Scoped Grant / Reveal / Messaging
```

A denied Trust/Permission/Source-Protection decision cannot be overridden by a high Match score.

---

## 8. Authoritative data versus projections

### Authoritative / source-of-truth targets

- `candidate_profiles`
- `candidate_preferences`
- `role_dnas`
- `opportunity_specs`
- `talent_streams`
- `talent_intent_events`
- `talent_stream_contact_requests`
- `talent_stream_grants`
- `organizations` (or approved canonical equivalent)
- `organization_memberships`
- `recruiter_verifications`
- `recruiting_mandates`
- `source_protection_records` when persistent evidence is required
- outbox/idempotency records as required

### Derived / reconstructible targets

- `role_clusters`
- `role_intent_aggregates`
- `talent_stream_candidates`
- `market_intelligence_aggregates`
- ranking/read-model caches

If a projection is lost, authoritative source data must support rebuild.

A read model is never the sole source of truth for current Permission, Trust or consent.

---

## 9. Stream candidate projection

A future `talent_stream_candidates` read model may contain:

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

Rules:

- snapshots support audit/explanation;
- current authorization is recalculated before sensitive actions;
- do not duplicate unnecessary email, phone, CV or exact sensitive attributes in projections;
- a projection may rank/order candidates but must not silently become a permanent candidate record.

---

## 10. Authorization architecture

Sensitive actions include at least:

- request recruiter introduction;
- reveal detailed profile;
- reveal identity/contact information;
- access/download CV;
- open recruiter-to-candidate messaging.

Canonical policy decision:

```text
Requested action
      ↓
Current discovery/preference state
Current grant state
Current exclusions
Recruiter/company/mandate state
Source-protection state
Contact-Governor state
      ↓
Central policy decision
      ↓
ALLOW / DENY
```

Never authorize from cached Stream projection alone.

---

## 11. Existing CV ACL integration

Preserve the current restrictive document-access philosophy.

Target extension:

```text
ALLOW CV IF
  owner
  OR authorized admin
  OR exact authorized application relationship
  OR active scoped Talent Stream CV grant
```

Never introduce `if employer: allow` or an equivalent broad recruiter bypass.

Profile access, identity access and CV access are distinct scopes.

---

## 12. Organization / recruiter / mandate model

`user_type=employer` is insufficient for nominative Talent Stream access.

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

A Stream must be capable of distinguishing:

- `recruiter_user_id`;
- `requesting_organization_id`;
- `hiring_company_id`;
- `mandate_id` when applicable.

Confidential recruiting may hide company identity from the candidate temporarily under product policy, but Joboolo must still internally verify these entities.

---

## 13. Intent event architecture and provenance

CPC/billing click events and candidate-intent events are separate domains.

Do not add Talent Stream identity semantics directly to the CPC ledger.

Future intent event envelope conceptually supports:

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

Provenance may be retained internally for source-protection/evidence policy but must never become recruiter-visible competitor intelligence.

Discovery enablement is a preference/permission event/state, not Role Intent itself.

---

## 14. Event/outbox and async strategy

Do not introduce Kafka or microservices in initial Talent Stream phases.

Preferred pattern:

```text
MongoDB transaction where required
  + domain event/outbox record
  + idempotent worker
```

Async examples:

- recompute affected Streams;
- Role DNA enrichment;
- Role Cluster refresh;
- Intent aggregation;
- analytics rollups.

Eligibility computation and invitation sending are separate operations.

Workers must be retryable, idempotent, version-aware and observable.

---

## 15. Idempotency requirements

Sensitive commands must tolerate retries.

Examples:

- record/process intent event;
- refresh/recompute Stream;
- create contact request;
- accept/decline contact request;
- create/activate/revoke grant;
- consume accepted-introduction credit;
- process ATS callback.

Retries must not produce duplicate invitations, grants, canonical events or charges.

Use explicit command/event/idempotency keys where appropriate.

---

## 16. Versioning and snapshots

Version at minimum where applicable:

- Candidate Professional Profile;
- Candidate Preferences/Discovery State;
- Role DNA;
- Opportunity Specification;
- Match Engine;
- Intent Engine;
- authorization/privacy/source-protection policy;
- consent policy/text;
- event schema.

A Stream binds to a version/snapshot of its requirement.

A source job changing later must not silently redefine an existing Stream. Updating a Stream requirement is an explicit operation.

---

## 17. Matching and Role Cluster architecture

The existing LLM-based matching may remain during migration, but authoritative Talent Stream decisions should become reproducible/versioned.

Target Professional Match combines:

- structured fields;
- normalized role/skill taxonomy;
- semantic embeddings where useful;
- deterministic hard filters;
- explicit scores/reason codes;
- LLM enrichment/explanation as supporting functionality.

Role Similarity / Role Clusters use a hybrid approach:

- occupation taxonomy;
- structured Role DNA similarity;
- skills/seniority/business constraints;
- semantic embeddings;
- versioned thresholds/rules;
- reason/evidence output.

Do not use an opaque LLM-only clustering decision as the canonical source of Cross-Offer eligibility.

Offer Similarity, Candidate Match and Candidate Intent remain separate.

---

## 18. Anonymous Talent and privacy architecture

Removing a name is insufficient anonymization.

Anonymous cards may generalize/remove:

- exact location;
- exact current employer;
- rare identifying credentials;
- unusual attribute combinations;
- overly precise experience details.

Market analytics should apply minimum cohort/privacy thresholds where small segments could reveal individuals.

Anonymous rendering policy must be versioned/testable enough to support regression checks.

---

## 19. Cross-Offer boundary and Source Protection Window

Cross-Offer has two distinct stages.

### Internal retrieval
Backend may compute that a candidate is relevant to a similar role.

### Recruiter exposure
Candidate must not appear in recruiter-facing Cross-Offer results until applicable safeguards are satisfied:

- Independent Signal Rule;
- origin neutralization;
- Source Protection;
- candidate discovery/Cross-Offer permission;
- recruiter/company/mandate trust;
- exclusions;
- Contact Governor;
- Opportunity Fit.

Source-protection policy must support configurable timing/cooling behavior such as a **Source Protection Window** for source-sensitive/paid acquisition signals. Duration is a versioned policy, not a hardcoded business constant.

Internal relevance is not authorization to expose.

---

## 20. Index and migration strategy

Do not put all future Talent Stream schema/index changes into startup mutation code.

Rules:

- simple startup-safe non-destructive indexes may be acceptable;
- sensitive unique indexes require explicit migration/preflight;
- migrations must handle existing data safely;
- startup must fail safely when required invariants are not met;
- TTL indexes are cleanup mechanisms only.

If `grant.expires_at` has passed, authorization denies immediately even if MongoDB TTL has not physically removed the document.

---

# 21. Canonical delivery map

The IDs below are the canonical roadmap identifiers. Individual issues may further split a lot, but must not silently merge future lots into current scope.

## Phase A — Talent Engine & Trust Foundation

| Lot | Circle | Execution | Capability | Dependencies | Gate contribution |
|---|---:|---|---|---|---|
| **A0** | C1 | SEQ | Domain contracts, IDs, versioning, transaction boundaries | G0 | foundation contract |
| **A1** | C1 | // | Candidate Professional Profile | A0 | Talent Graph v1 |
| **A2** | C1 | // | Candidate Preferences + Discovery State | A0 | discovery/preferences |
| **A3** | C1 | // | Role DNA + taxonomy | A0 | Role Graph v1 |
| **A4** | C1 | after A3 | Opportunity Specification | A3 | Stream Requirement input |
| **A5** | C1 | after A1+A3 | Explainable Match Engine v2 | A1+A3 | Candidate↔Role Match |
| **A6** | C1 | after A2+A4 | Hard Eligibility / Opportunity Fit v1 | A2+A4 | compatibility guard |
| **A7** | C1 | // | Organization/Company Verification | A0 | organization trust |
| **A8** | C1 | after A7 | Recruiter Membership + Verification + Mandate | A7 | recruiter eligibility |
| **A9** | C0/C1 | after A2+A8 | Authorization / Grant Engine | A2+A8 | current policy decisions |
| **A10** | C1 | after A9 | Privacy Lifecycle | A9 | expiry/revoke/retention |
| **A11** | C0 | // | Intent Event Contract + Provenance | A0 | Intent foundation |
| **A12** | C1/C2 | // | Audit + Reason Codes | A0 | explainability/audit |
| **A13** | C1 | // | Mongo migration/index strategy | A0 | schema safety |
| **A14** | C1 | // | Async job/outbox/idempotency contract | A0 | worker safety |

### GA — Talent Engine & Trust Ready

GA requires enough of A0-A14 to safely support Phase B, including canonical profile/preferences/discovery, Role DNA/Opportunity Spec, explainable Match, organization/recruiter/mandate trust, authorization/privacy, preserved CV ACL, Intent/provenance contract, audit/versioning and migration safety.

## Phase B — Talent Stream MVP

| Lot | Circle | Execution | Capability | Dependencies |
|---|---:|---|---|---|
| **B1** | C0 | SEQ | Talent Stream Aggregate Root / lifecycle | GA |
| **B2** | C0 | after B1 | Own-job Stream Requirement adapter | B1+A3+A4 |
| **B3** | C0 | // | Application source adapter | B1 |
| **B4** | C0 | // | “I’m interested” declared intent | B1+A11 |
| **B5** | C0 | // | Explicitly shared favorite/interest | B1+A11 |
| **B6** | C0 | // | Discovery Pool retrieval | B1+A2+A5+A6 |
| **B7** | C0 | after B3-B6 | Stream candidate projection/read model | B3+B4+B5+B6 |
| **B8** | C0/C1 | after B7 | Privacy-safe Anonymous Talent cards | B7+A10 |
| **B9** | C0/C1 | after B7 | Contact Governor v1 | B7+A8+A9 |
| **B10** | C0 | after B8+B9 | Contact Request Engine | B8+B9 |
| **B11** | C0 | after B10 | Candidate invitation + accept/decline/ignore | B10 |
| **B12** | C0/C1 | after B11 | Current authorization check + Grant Activation | B11+A9+A10 |
| **B13** | C0 | after B12 | Progressive profile/identity reveal | B12 |
| **B14** | C0 | after B12 | Specific CV grant/access path | B12 + existing ACL |
| **B15** | C0 | after B12 | Messaging authorization adapter | B12 |
| **B16** | C2 | // | Talent Stream Analytics v1 | B1 |

Non-blocking multipliers such as Recommendations v2 or Kanban integration may run in parallel if they do not delay GB.

### GB — Talent Stream MVP Ready

Verified own-job Stream works end to end using Applications, Declared Interest, Shared Interest and Discovery Pool, with anonymous/privacy-safe exposure, Contact Governor, candidate decision, current authorization, optional CV grant and messaging. Recruiter-visible observed Cross-Offer is still disabled.

## Phase C — Cross-Offer Intent & Moat

| Lot | Circle | Capability | Dependencies |
|---|---:|---|---|
| **C1** | C1 | Role Similarity Engine | GB+A3 |
| **C2** | C0/C1 | Role Clustering | C1 |
| **C3** | C0 | Observed Intent Collection | GB+A11 |
| **C4** | C0 | Job/Role/Company/Market Intent aggregation | C2+C3 |
| **C5** | C0 | Cross-Offer Retrieval **INTERNAL ONLY** | C4+A5 |
| **C6** | C1 | Independent Signal Rule | C5 |
| **C7** | C1 | Origin Neutralization | C5 |
| **C8** | C1 | Source Protection + configurable Window | C6+C7 |
| **C9** | C1 | Cross-Offer Permission/Evidence Policy | C6+A9 |
| **C10** | C0/C1 | Contact Governor v2 | C6+C8+C9 |
| **C11** | C1 | Opportunity Fit v2 / richer constraints | C5+A6 |
| **C12** | C2 | Salary Intelligence v1 | C11 |
| **C13** | C2 | Semantic Search / Role Graph retrieval | C1 |
| **C14** | C2 | Talent Rediscovery | C4 |
| **C15** | C2 | Responsible AI Center v1 | C4+A12 |
| **C16** | C0 | Cross-Offer Recruiter Projection **SAFE EXPOSURE** | C6+C7+C8+C9+C10+C11 |

### GC — Cross-Offer Safe & Effective

No recruiter-facing Cross-Offer exposure before C16 and all relevant safeguards. Exact competitor/source behavior remains internal.

## Phase D — No-Posting Talent Stream

| Lot | Circle | Capability | Dependencies |
|---|---:|---|---|
| **D1** | C0 | Own Job -> editable Stream template | GC |
| **D2** | C0 | Other allowed Joboolo Job -> Role DNA model | GC |
| **D3** | C2 | Natural Language Need -> Role DNA/Opportunity Spec | GC+A3+A4 |
| **D4** | C0 | Common No-Posting Stream Wizard | D1+D2+D3 |
| **D5** | C0 | Confidential Stream policy/UX | D4+A8+A9 |
| **D6** | C2 | Market/Talent Availability Preview | C2+C4+D4 |
| **D7** | C0/C2 | External URL -> safe Role DNA extraction | D4 |
| **D8** | C2 | Talent Stream packaging/billing | D4+B16 |
| **D9** | C3 | Reverse Marketplace v1 | D4 |

### GD — No-Posting Ready

Own job, allowed reference Joboolo job and natural-language need converge to the same Stream Requirement and engine. External URL uses the same pipeline when enabled. Reference jobs transfer role semantics, never audience rights.

## Phase E — Intelligence & Scale

Phase E is deliberately parallelized into tracks.

### E1 — Recruiter OS

- Mini ATS v2
- CRM talent pools/nurturing
- Structured interviews/scorecards
- Scheduling/reminders
- Rejection feedback
- recruiter SLA/quality controls

### E2 — External Recruitment Network

- ATS postbacks
- ATS/API/webhooks
- ATS integrations
- external apply attribution
- status sync

### E3 — Market & Data Intelligence

- Market Intelligence v2
- Salary Intelligence v2
- Talent Availability
- Recruiter Analytics
- Quality-of-Hire
- Talent Supply Forecast

### E4 — Skills & Career Graph

- Skills Passport
- Micro-assessments / Proof-of-Skill
- Skill Gap
- Career Explorer
- Train-to-Hire

### E5 — Candidate Experience

- Candidate Agent
- CV Assistant
- Interview Coach
- WhatsApp/SMS/QR channels

### E6 — Employer Experience

- job-writing/compliance/salary copilot
- enriched employer/company pages

### GE — Talent Platform Ready

Scale, integrations, observability, intelligence and ecosystem capabilities meet production/platform requirements without weakening the earlier Trust/Permission Gates.

---

## 22. Parallel delivery lanes

Recommended permanent lanes once contracts are stable:

| Lane | Responsibility |
|---|---|
| **Lane 1 — Talent Engine** | Profile, Role DNA, Opportunity Spec, Match, Role Clusters |
| **Lane 2 — Trust & Privacy** | Verification, mandates, permissions, exclusions, Source Protection, Contact Governor |
| **Lane 3 — Product UX** | Candidate/recruiter Stream, invitations, progressive reveal, workflows |
| **Lane 4 — Data & Intelligence** | Intent events, projections, workers, analytics, monitoring |

Parallel work starts only after shared contracts/IDs are defined. Two lanes must not invent separate representations of Role DNA, Permission or Intent.

---

## 23. Gate testing philosophy

Gates are testable release conditions, not documentation labels.

Examples of future policy tests:

```text
test_private_favorite_never_grants_sharing()
test_click_alone_never_reveals_identity()
test_discovery_and_intent_are_separate()
test_current_employer_exclusion_blocks_contact()
test_unverified_recruiter_cannot_request_intro()
test_declined_intro_never_reveals_profile()
test_cv_requires_exact_active_grant()
test_cross_offer_never_exposes_source_job()
test_source_protection_window_policy()
test_contact_governor_prevents_duplicates_and_overcontact()
test_talent_stream_opt_in_not_required_to_apply()
```

If a Gate-critical test fails, the corresponding behavior must not be released.

---

## 24. Strategic graph model

Conceptually Talent Stream builds/reuses:

- Job Graph;
- Role Graph;
- Talent Graph;
- Intent Graph.

This is a conceptual data architecture, not a requirement to introduce a graph database. MongoDB remains valid while access patterns and scale justify it.

---

## 25. Architectural red lines

Do not:

- introduce microservices/Kafka without a dedicated approved architecture decision;
- silently mutate existing Streams when source jobs change;
- treat Discovery as Intent;
- turn CPC click ledger into nominative Intent storage;
- authorize from stale projections;
- bypass CV ACL for employers/recruiters;
- expose internal Cross-Offer retrieval before GC safeguards;
- use an opaque LLM-only decision for canonical Match/Role Cluster/permission;
- create separate Talent Stream engines for own jobs, reference jobs, external URLs and natural language;
- implement cross-site surveillance as a shortcut;
- create fake jobs for candidate harvesting.

---

## 26. Final architecture invariant

> **Talent Stream orchestrates relevance; it does not manufacture permission.**

The architecture must preserve separate sources of truth for professional relevance, opportunity compatibility, discovery/intent, recruiter trust, candidate permission and source protection throughout Phases A-E.
