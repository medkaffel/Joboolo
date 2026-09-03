# PLAN — TS-A0-001: Domain Contracts & Business Invariants (Corrected)

**Status:** PLAN ONLY — read-only, no modifications  
**Phase:** A — Talent Engine & Trust Foundation  
**Circle:** C1 — Vital Foundation  
**Gate contribution:** Foundation Contract  
**Dependencies:** G0 (Baseline)

---

## Executive Summary

This plan defines the **minimal domain contracts, type definitions, enum declarations, protocol interfaces, and invariant tests** for Talent Stream Phase A within the existing Joboolo Modular Monolith FastAPI. **Zero runtime features** are implemented — only the architectural boundaries and business invariants that subsequent lots (A1–A14, B1+) will build against.

All corrections from the mandatory review have been applied:
- Discovery ≠ Intent enforced at contract level
- Private favorite ≠ Intent; only explicit declared interest creates Intent events
- Scope strictly limited to contracts/types/tests — no repository implementations, outbox, migrations, or engine behavior
- Persistence targets are conceptual; no premature collection freezing
- Idempotency contracts support explicit delivery IDs; dedup policy deferred
- Embeddings marked as derived/recomputable support data
- Current authorization re-evaluation stated as invariant
- Contact flow: request → acceptance → grant (not grant → request)
- All red-line invariants preserved explicitly

---

## (a) Exact A0-001 BUILD Deliverables

### 1. Domain Package Skeletons (empty `__init__.py` + structure)
```
backend/domains/
  profiles/          # Candidate Professional Profile, Preferences, Discovery State
  roles/             # Role DNA, taxonomy, Role Clusters (derived)
  opportunities/     # Opportunity Specification, Stream Requirement
  matching/          # Professional Match, Hard Eligibility, Opportunity Fit
  intent/            # Intent Event Contracts, Provenance, Intent Dimensions
  talent_stream/     # Stream Aggregate Root, Contact Request, Grants
  trust/             # Organization, Recruiter Verification, Mandate, Source Protection
  permissions/       # Authorization, Grants, Exclusions, Current Policy Decision
  privacy/           # Retention, Expiry, Anonymous Rendering, Re-identification Safeguards
```

### 2. Shared Kernel (neutral, minimal)
```
backend/domains/shared/
  kernel/
    __init__.py
    ids.py                    # NewType/TypedDict for all canonical IDs
    enums.py                  # All canonical enums (see §3 below)
    value_objects.py          # Version, Timestamp, Money, Location, etc.
    events.py                 # Base event envelope (event_id, causation_id, correlation_id, schema_version, occurred_at, source)
    commands.py               # Base command envelope (command_id, idempotency_key, timestamp, actor)
    protocols.py              # Protocol interfaces (Repository, Engine, Policy, Governor) — NO implementations
    invariants.py             # Pure invariant functions (see §4 below)
    versioning.py             # VersionedEntity protocol, snapshot metadata
```

### 3. Canonical Enum Definitions (`shared/kernel/enums.py`)
**IntentEventType** — only declared/explicit events:
- `DECLARED_INTEREST` (explicit "I'm interested")
- `SHARED_FAVORITE` (explicitly shared favorite/interest)
- `APPLICATION_SUBMITTED`
- `INTRODUCTION_ACCEPTED`
- `INTRODUCTION_DECLINED`

**NOT included:** `DISCOVERY_ENABLED`, `SAVE`, `VIEW`, `CLICK`, `EXTERNAL_REDIRECT` — these are NOT Intent events. Discovery state changes belong to `profiles` domain events (e.g., `candidate.discovery.changed`). Observed signals are Phase C concerns.

**DiscoveryState** (profiles domain):
- `DISABLED`
- `ENABLED_COMPATIBLE`
- `ENABLED_ASK_BEFORE_REVEAL`
- `ENABLED_ANONYMOUS_ONLY`

**PermissionScope** (permissions domain):
- `PROFILE_PREVIEW`
- `IDENTITY_REVEAL`
- `CONTACT_REVEAL`
- `CV_GRANT`
- `MESSAGING`

**TrustLevel** (trust domain):
- `UNVERIFIED`
- `VERIFIED`
- `VERIFIED_ENHANCED`
- `SUSPENDED`

**StreamBreadth** (talent_stream domain):
- `PRECISE`
- `BALANCED`
- `EXPLORATORY`

**SourceProtectionAction** (trust domain):
- `ALLOW`
- `DELAY`
- `DENY`

**GrantState** (permissions domain):
- `ACTIVE`
- `EXPIRED`
- `REVOKED`
- `CONSUMED`

**ContactRequestState** (talent_stream domain):
- `PENDING`
- `ACCEPTED`
- `DECLINED`
- `IGNORED`
- `EXPIRED`

**RoleClusterMethod** (roles domain):
- `TAXONOMY_STRUCTURED`
- `SKILLS_SENIORITY`
- `SEMANTIC_EMBEDDING`
- `HYBRID`

### 4. Pure Invariant Functions (`shared/kernel/invariants.py`)
All functions are pure, side-effect-free, and testable in isolation:
```python
# Fundamental separations (raise ValueError if violated)
assert_match_not_intent(match: ProfessionalMatch, intent: IntentEvidence) -> None
assert_discovery_not_intent(discovery: DiscoveryState, intent: IntentEvidence) -> None
assert_intent_not_permission(intent: IntentEvidence, permission: PermissionDecision) -> None
assert_permission_not_trust(permission: PermissionDecision, trust: TrustDecision) -> None
assert_opportunity_fit_not_match(fit: OpportunityFit, match: ProfessionalMatch) -> None
assert_reference_job_not_audience_ownership(ref_job: ReferenceJob) -> None

# Current authorization (snapshots are audit-only)
assert_current_authorization_checked(action: SensitiveAction, context: AuthorizationContext) -> None

# Source protection
assert_source_provenance_internal_only(event: IntentEvent) -> None
assert_no_cross_offer_exposure_before_gc(projection: StreamProjection) -> None

# CV ACL
assert_cv_access_requires_active_grant(cv_access: CVAccessRequest) -> None

# Private favorite ≠ sharing consent
assert_private_favorite_never_grants_sharing(favorite: SavedJob) -> None

# Click/view ≠ sharing consent
assert_click_never_grants_sharing(click: ClickEvent) -> None

# Talent Stream opt-in not required for application
assert_talent_stream_opt_in_not_required_for_application(application: Application) -> None

# Candidate refusal must not penalize
assert_refusal_does_not_penalize_unrelated(refusal: IntroductionRefusal) -> None

# Embeddings are derived support data
assert_embedding_is_derived_support(embedding: RoleEmbedding, role_dna: RoleDNA) -> None
```

### 5. Protocol Interfaces (`shared/kernel/protocols.py`)
**Repository Protocols** (read-only signatures, no implementations):
- `CandidateProfileRepository` — `get(profile_id)`, `get_by_candidate(candidate_id)`
- `CandidatePreferencesRepository` — `get(preferences_id)`, `get_by_candidate(candidate_id)`
- `RoleDNARepository` — `get(role_dna_id)`, `find_by_occupation(occupation)`
- `OpportunitySpecRepository` — `get(spec_id)`
- `StreamRequirementRepository` — `get(req_id)`, `find_by_stream(stream_id)`
- `IntentEventRepository` — `append(event)`, `find_by_candidate(candidate_id, since)`
- `ContactRequestRepository` — `get(request_id)`, `find_by_stream(stream_id)`
- `GrantRepository` — `get(grant_id)`, `find_active_for_candidate(candidate_id)`
- `OrganizationRepository` — `get(org_id)`, `find_by_user(user_id)`
- `RecruiterVerificationRepository` — `get(verification_id)`, `find_by_recruiter(recruiter_id)`
- `MandateRepository` — `get(mandate_id)`, `find_by_hiring_company(company_id)`

**Engine Protocols** (signatures only):
- `MatchEngine` — `match(profile: CandidateProfile, role_dna: RoleDNA) -> ProfessionalMatch`
- `FitEngine` — `fit(preferences: CandidatePreferences, spec: OpportunitySpec) -> OpportunityFit`
- `IntentEngine` — `aggregate(events: list[IntentEvent]) -> IntentProfile`
- `RoleClusterEngine` — `cluster(role_dnas: list[RoleDNA]) -> RoleClusters`

**Policy/Governor Protocols** (signatures only):
- `ContactGovernor` — `check(request: ContactRequest) -> GovernorDecision`
- `AuthorizationPolicy` — `decide(context: AuthorizationContext) -> PermissionDecision`
- `TrustPolicy` — `evaluate(recruiter: Recruiter, org: Organization, mandate: Mandate | None) -> TrustDecision`
- `SourceProtectionPolicy` — `evaluate(event: IntentEvent, context: SourceProtectionContext) -> SourceProtectionAction`
- `PrivacyPolicy` — `render_anonymous(profile: CandidateProfile) -> AnonymousCard`

### 6. Contract Tests Only (`tests/contracts/`)
- `test_invariants_fundamental_separations.py` — all `assert_*` functions from invariants.py
- `test_enums_exhaustiveness.py` — enum coverage, no missing values
- `test_ids_type_safety.py` — NewType prevents accidental mixing
- `test_event_envelope_structure.py` — required fields present, schema_version
- `test_command_envelope_idempotency_key.py` — explicit `command_id`/`idempotency_key` supported
- `test_protocols_are_protocols.py` — all interfaces are `Protocol` classes, no concrete impls
- `test_versioning_metadata.py` — VersionedEntity protocol has version, updated_at, schema_version
- `test_discovery_not_in_intent_events.py` — `DISCOVERY_ENABLED` absent from `IntentEventType`
- `test_private_favorite_not_intent_event.py` — `SAVE` absent from `IntentEventType`
- `test_current_auth_re_evaluated.py` — invariant asserts snapshots are audit-only
- `test_contact_flow_request_then_grant.py` — flow order enforced in protocol signatures
- `test_embeddings_derived_not_authoritative.py` — embedding marked derived in RoleDNA protocol
- `test_cpc_intent_separation.py` — no CPC fields in IntentEvent envelope
- `test_cross_offer_internal_only.py` — CrossOfferRetrieval protocol returns internal-only projection

---

## (b) Exact Files Expected

| Path | Purpose |
|------|---------|
| `backend/domains/profiles/__init__.py` | Package marker |
| `backend/domains/roles/__init__.py` | Package marker |
| `backend/domains/opportunities/__init__.py` | Package marker |
| `backend/domains/matching/__init__.py` | Package marker |
| `backend/domains/intent/__init__.py` | Package marker |
| `backend/domains/talent_stream/__init__.py` | Package marker |
| `backend/domains/trust/__init__.py` | Package marker |
| `backend/domains/permissions/__init__.py` | Package marker |
| `backend/domains/privacy/__init__.py` | Package marker |
| `backend/domains/shared/kernel/__init__.py` | Package marker |
| `backend/domains/shared/kernel/ids.py` | Canonical ID types |
| `backend/domains/shared/kernel/enums.py` | All canonical enums |
| `backend/domains/shared/kernel/value_objects.py` | Version, Timestamp, Money, Location |
| `backend/domains/shared/kernel/events.py` | Base event envelope |
| `backend/domains/shared/kernel/commands.py` | Base command envelope |
| `backend/domains/shared/kernel/protocols.py` | All Protocol interfaces |
| `backend/domains/shared/kernel/invariants.py` | Pure invariant functions |
| `backend/domains/shared/kernel/versioning.py` | VersionedEntity protocol |
| `tests/contracts/test_invariants_fundamental_separations.py` | Invariant tests |
| `tests/contracts/test_enums_exhaustiveness.py` | Enum coverage |
| `tests/contracts/test_ids_type_safety.py` | ID type safety |
| `tests/contracts/test_event_envelope_structure.py` | Event envelope |
| `tests/contracts/test_command_envelope_idempotency_key.py` | Command idempotency |
| `tests/contracts/test_protocols_are_protocols.py` | Protocol verification |
| `tests/contracts/test_versioning_metadata.py` | Versioning metadata |
| `tests/contracts/test_discovery_not_in_intent_events.py` | Discovery ≠ Intent |
| `tests/contracts/test_private_favorite_not_intent_event.py` | Private favorite ≠ Intent |
| `tests/contracts/test_current_auth_re_evaluated.py` | Current authorization |
| `tests/contracts/test_contact_flow_request_then_grant.py` | Contact flow order |
| `tests/contracts/test_embeddings_derived_not_authoritative.py` | Embeddings derived |
| `tests/contracts/test_cpc_intent_separation.py` | CPC ≠ Intent |
| `tests/contracts/test_cross_offer_internal_only.py` | Cross-Offer internal only |

**Total: ~25 files** (9 domain packages + 8 shared kernel + 16 contract tests)

---

## (c) Deferred Items Mapped to Future Lots

| Deferred Item | Target Lot | Reason |
|---------------|------------|--------|
| Repository implementations (MongoDB) | A1, A2, A3, A4, A11, A7, A8, A9 | Each lot owns its authoritative persistence |
| Candidate Professional Profile engine | A1 | Dedicated lot |
| Candidate Preferences + Discovery State | A2 | Dedicated lot |
| Role DNA + taxonomy + normalization | A3 | Dedicated lot |
| Opportunity Specification | A4 | After A3 |
| Professional Match Engine v2 | A5 | After A1+A3 |
| Hard Eligibility / Opportunity Fit v1 | A6 | After A2+A4 |
| Organization/Company Verification | A7 | Dedicated lot |
| Recruiter Membership + Verification + Mandate | A8 | After A7 |
| Authorization / Grant Engine | A9 | After A2+A8 |
| Privacy Lifecycle | A10 | After A9 |
| Intent Event Contract + Provenance (runtime) | A11 | Dedicated lot — A0-001 only defines envelope/enums |
| Audit + Reason Codes | A12 | Dedicated lot |
| Mongo migration/index strategy | A13 | Dedicated lot — A0-001 defines strategy principles only |
| Async job/outbox/idempotency implementation | A14 | Dedicated lot — A0-001 defines command/envelope contracts only |
| Talent Stream Aggregate Root / lifecycle | B1 | Phase B — after GA |
| Stream Requirement adapters (own job, ref job, NL) | B2, B3, D1–D3 | Phase B/D |
| Contact Governor v1/v2 runtime | B9, C10 | Phase B/C |
| Contact Request Engine | B10 | Phase B |
| Candidate invitation + accept/decline | B11 | Phase B |
| Current authorization check + Grant Activation | B12 | Phase B |
| Progressive reveal / CV grant / Messaging | B13, B14, B15 | Phase B |
| Role Similarity / Role Clusters | C1, C2 | Phase C |
| Observed Intent Collection | C3 | Phase C |
| Intent Dimensions aggregation | C4 | Phase C |
| Internal Cross-Offer Retrieval | C5 | Phase C |
| Independent Signal Rule / Origin Neutralization | C6, C7 | Phase C |
| Source Protection + Window | C8 | Phase C |
| Cross-Offer Permission Policy | C9 | Phase C |
| Cross-Offer Recruiter Projection (SAFE EXPOSURE) | C16 | Phase C — **after GC** |
| Semantic Search / Role Graph | C13 | Phase C |
| No-Posting Wizard | D4 | Phase D |
| External URL sourcing | D7 | Phase D |
| Recruiter OS / CRM / ATS | E1, E2 | Phase E |
| Market/Salary Intelligence | E3 | Phase E |
| Skills/Career Graph / Passport | E4 | Phase E |
| Candidate Agent / CV Assistant | E5 | Phase E |

---

## (d) Contract Tests Only

**No integration tests, no runtime tests, no database tests.** Only the 16 contract tests listed in §(b) validating:
- Enum completeness and correctness
- Invariant function behavior (pure, deterministic)
- Protocol interface structure (all `@runtime_checkable` Protocols)
- ID type safety (NewType prevents cross-domain mixing)
- Event/command envelope required fields
- Versioning metadata presence
- Critical business rule encoding (Discovery≠Intent, PrivateFav≠Intent, CurrentAuth, ContactFlow, EmbeddingsDerived, CPC≠Intent, CrossOfferInternalOnly)

---

## (e) Blockers

1. **No architecture decision on Organization/HiringCompany persistence reuse** — A0-001 defines `Organization`/`HiringCompany` as conceptual identities with protocols only. A7/A8 must decide whether to extend existing `Company`/`User` collections or create new ones. **Blocker for A7/A8, not for A0-001.**

2. **No decision on Candidate Profile storage strategy** — whether to extend existing `User`/`CandidateProfile` or create new `candidate_profiles` collection. **Blocker for A1, not for A0-001.**

3. **No decision on Intent Event storage** — `talent_intent_events` collection vs. extending existing event store. **Blocker for A11, not for A0-001.**

4. **Source Protection Window duration policy** — exact cooling period is versioned product policy, not domain constant. A0-001 defines `SourceProtectionPolicy` protocol with configurable window; C8 implements policy. **Not a blocker for A0-001.**

5. **Contact Governor algorithm details** — frequency caps, cooling rules, saturation constraints are product policy. A0-001 defines `ContactGovernor` protocol; B9/C10 implement. **Not a blocker for A0-001.**

---

## Architecture Compliance Checklist

- [x] Modular Monolith — all new code in `backend/domains/`
- [x] No microservices/Kafka/graph DB
- [x] No massive refactor — existing models untouched
- [x] Thin HTTP adapters — routes unchanged, will delegate later
- [x] Authoritative vs Projection — explicitly classified in protocols
- [x] Event provenance — base envelope in `events.py`
- [x] Idempotence + Outbox contracts — `commands.py` supports explicit keys
- [x] Dependency direction respected — protocols only depend on shared kernel
- [x] Cross-Offer internal only — `CrossOfferRetrieval` protocol returns internal projection
- [x] Source Protection Window configurable — protocol accepts policy config
- [x] Current authorization re-evaluation — invariant + protocol signature
- [x] CV ACL preserved — `assert_cv_access_requires_active_grant`
- [x] No fake jobs — not in scope
- [x] Talent Stream opt-in not required — invariant test
- [x] Candidate refusal no penalty — invariant test
- [x] No recruiter surveillance API — CrossOfferRetrieval internal only

---

**End of Corrected Plan**

TESTS=NOT_RUN