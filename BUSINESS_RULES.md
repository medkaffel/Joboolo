# Joboolo Talent Stream — Business Rules

**Status:** Binding business invariants for Talent Stream  
**Version:** 1.1  
**Last architecture review:** 2026-09-03  
**Applies to:** All Phase A-E Talent Stream work  
**Priority:** These rules override implementation convenience.

> The current GitHub issue/PR remains the only authorized implementation scope. This document defines rules that any implementation must respect.

---

## 1. Fundamental separation rules

1. `Professional Match != Intent`.
2. `Discovery != Intent`.
3. `Intent != Permission`.
4. `Permission != Trust`.
5. `Trust != Match`.
6. `Opportunity Fit != Professional Match`.
7. `Reference Job != Audience Ownership`.
8. A ranking may combine signals internally, but underlying dimensions must remain separately explainable.
9. Do not replace these dimensions with one opaque authoritative “Talent Score”.
10. A denied permission/trust/source-protection decision cannot be overridden by a high Match score.

---

## 2. Candidate intent, discovery and consent

1. A private favorite is not consent to share a profile.
2. A job view is not consent to share a profile.
3. A click is not consent to share a profile.
4. An external redirect click is not consent to reveal identity.
5. A good Match is not permission to contact.
6. A completed application to Company A is not automatic permission to share with Company B.
7. An application to another company may contribute to Role Intent evidence, but never creates a cross-company CV/profile grant.
8. Discovery enablement is a preference/permission state, not an Intent event.
9. Declared interest and Discovery may authorize a **controlled introduction request** only within current candidate policy; they do not automatically authorize full identity/CV reveal.
10. Candidate refusal/ignore must not reduce Professional Match or punish the candidate in unrelated hiring flows.
11. Absence of recent Intent must not exclude a candidate who explicitly enabled Discovery.
12. Talent Stream activation/discovery must never be required to apply to a job.
13. Refusing Talent Stream must not reduce the candidate’s chances in an application already submitted.

---

## 3. Discovery Pool

1. Talent Stream supports passive/open candidates.
2. Discovery Pool eligibility requires explicit Discovery authorization and compatible preferences.
3. Intent may alter priority but is not required for every Discovery Pool candidate.
4. “Search paused” may coexist with “Discovery enabled”.
5. Discovery State and active-search intensity are separate concepts.
6. Candidate can revoke Discovery and future eligibility must reflect current state promptly.

---

## 4. Role DNA and Opportunity Specification

1. Role DNA describes the professional role.
2. Opportunity Specification describes the particular recruiting opportunity.
3. Salary, location, remote policy and contract are not universal Role DNA attributes.
4. `Role DNA + Opportunity Specification = Stream Requirement`.
5. A reference job may help derive Role DNA but does not authorize copying audience/candidate rights.
6. An existing Stream is bound to a version/snapshot of its Stream Requirement.
7. A source job changing later must not silently mutate the Stream Requirement.
8. Derived Role DNA should be preferred over unnecessary long-term retention/rebroadcast of third-party job text when that text is not needed.

---

## 5. Reference jobs and competitor boundaries

1. `Reference Job != Audience Ownership`.
2. Using another public job as a model does not transfer that company’s candidates.
3. A recruiter must not gain access to another recruiter’s application list because Role DNA is similar.
4. A traffic/feed/XML/CPC partner is not automatically an authorized recruiter.
5. `traffic_partner != authorized_recruiter`.
6. Source company performance/audience information must not become competitor intelligence.
7. Do not create fake/placeholder jobs whose primary purpose is harvesting candidates or Intent for a pool.

---

## 6. Cross-Offer Intent

1. Cross-Offer relevance is role-level relevance, not transfer of a source employer’s audience.
2. Internal Cross-Offer retrieval and recruiter-facing exposure are distinct stages.
3. A candidate may be internally relevant but still not be revealable/contactable.
4. Recruiter exposure requires all applicable source, trust, permission, exclusion, Opportunity Fit and anti-spam policies.
5. Recruiter must never see the exact competitor/source job that produced the signal.
6. Allowed wording is generic, e.g. “recent interest/activity on similar opportunities”.
7. Forbidden wording is source-specific, e.g. “saved Company X’s job yesterday”.
8. Company Intent must not automatically become transferable competitor Role Intent.
9. Observed/inferred Intent is probabilistic and must not be presented as certain psychological truth.
10. Recruiters must not be given a query/API that exposes a candidate’s precise browsing, click, save or company-interest history.

---

## 7. Independent Signal Rule

1. One isolated behavior from another employer’s job must not automatically create a nominative competitor lead.
2. Cross-Offer eligibility requires explicit Discovery/Permission and/or sufficiently independent role-level evidence.
3. Independent evidence may include multiple role-consistent interactions from different sources, declared similar-opportunity interest, or direct candidate acceptance.
4. The final policy must be versioned and auditable.
5. A single paid/source-sensitive signal alone must not bypass Source Protection simply because Match is high.

---

## 8. Source Protection / Window

1. Joboolo must avoid the perception that Recruiter A’s paid acquisition is immediately resold to Recruiter B.
2. Provenance may be retained internally to enforce source protection.
3. Provenance must not become competitor intelligence visible to recruiters.
4. Source Protection may consider source organization, campaign, paid/organic context, timing, signal strength and independent evidence.
5. Source Protection must not imply that employers own candidates.
6. The architecture must support a configurable **Source Protection Window** or equivalent cooling policy for source-sensitive signals.
7. Source Protection duration/thresholds are versioned policy, not hardcoded domain constants.

---

## 9. Recruiter, organization and mandate trust

1. `user_type=employer` alone is insufficient for nominative Talent Stream access.
2. Organization/company identity must be verifiable.
3. Recruiter identity and organization relationship must be verifiable.
4. Agency/RPO use may require a recruiting mandate to the hiring company.
5. Talent Stream distinguishes requesting organization from hiring company where necessary.
6. Unverified/unauthorized recruiting actors must not receive nominative candidate access.
7. Verification/suspension state must be checked at sensitive-action time when relevant.
8. Confidential recruiting must not mean unverified recruiting; Joboolo must know/verify the recruiter, organization, hiring company and mandate.

---

## 10. Candidate exclusions

1. Candidate may exclude current employer.
2. Candidate may exclude specific companies and, where supported, former employers/agencies/groups.
3. Current-employer exclusion is a security/privacy rule, not a cosmetic preference.
4. Exclusions apply before recruiter contact/reveal.
5. Stale projections must not bypass newly added exclusions.
6. Accidental current-employer exposure is a critical trust/security incident and must be auditable.

---

## 11. Contact Governor

1. Contact Governor executes before a real recruiter invitation.
2. Do not send first and check limits later.
3. Contact Governor may enforce frequency caps, deduplication, minimum eligibility, prior-decline protection, company exclusions, recruiter-trust threshold, salary/location compatibility, cooling and saturation constraints.
4. Cross-Offer expansion must not increase recruiter spam.
5. A retry must not create duplicate invitations/contact requests.
6. A recruiter must not repeatedly re-request the same candidate in a way that bypasses prior refusal/cooling rules.

---

## 12. Progressive reveal

1. Talent Stream uses progressive disclosure.
2. Aggregate market data may be shown without identity.
3. Anonymous cards must be privacy-safe, not merely name-redacted.
4. Profile Preview, identity/contact and CV are distinct reveal scopes.
5. `Profile Access != Identity Access` where product states differ.
6. `Profile Access != CV Access`.
7. Candidate must not be tricked into broad sharing through a narrow consent action.
8. Candidate must receive enough opportunity context to make a meaningful decision before accepting an introduction.

---

## 13. CV/document access

1. Preserve the current strict document ACL philosophy.
2. Candidate owner may access own document.
3. Authorized admin may access according to policy.
4. Employer access through an application requires valid application/job relationship and exact referenced CV.
5. Talent Stream adds only an active scoped Talent Stream CV-grant path.
6. Never introduce broad `if employer: allow` behavior.
7. CV grant is scoped to the relevant candidate/document/recruiter or organization/Stream/purpose.
8. Expired/revoked CV grant denies access immediately.
9. Payment/subscription never itself grants CV access.

---

## 14. Current authorization

1. Cached projection data is not an authorization source of truth.
2. Before a sensitive action, evaluate current state.
3. Sensitive actions include at least introduction request, identity/profile reveal, contact reveal, CV access and recruiter-to-candidate messaging.
4. Permission snapshots are audit/explanation evidence, not present authorization.
5. TTL cleanup delays must never extend an expired permission.

---

## 15. Privacy lifecycle

1. Grants/consents support policy/text versioning where required.
2. Relevant records support expiry/revocation semantics.
3. Revocation affects future access immediately.
4. TTL deletion is cleanup only; not authorization.
5. Retention rules are explicit by data category/purpose.
6. Anonymization/redaction applies when identifiable retention is no longer justified.
7. Audit evidence may follow a distinct retention policy from candidate-facing visibility data.
8. Data minimization applies to projections: do not duplicate email, phone or CV when references are sufficient.

---

## 16. Anonymous Talent / anti-reidentification

1. Removing a candidate’s name is insufficient anonymization.
2. Anonymous cards must avoid trivially identifying attribute combinations.
3. Exact current employer should be hidden before permission unless explicitly justified/authorized.
4. Exact location may require generalization.
5. Rare credentials/experience combinations may require redaction/generalization.
6. Market analytics enforce cohort-size/privacy thresholds where necessary.

---

## 17. CPC and Intent separation

1. CPC/billing events and candidate-intent events are separate domains.
2. Do not turn the CPC click ledger into a nominative Talent Stream database.
3. Financial events remain auditable independently of discovery/Intent events.
4. Candidate Intent provenance may reference source context only in its own governed domain where permitted.
5. Partner billing/traffic rights do not imply candidate-data rights.

---

## 18. Intent dimensions

1. Keep Job Intent, Role Intent, Company Intent and Market Intent separate.
2. Job Intent refers to one specific job.
3. Role Intent refers to sufficiently similar roles/Role Cluster.
4. Company Intent refers to one company and is not automatically transferable.
5. Market Intent refers to general employment-market activity.
6. Intent confidence/recency may decay over time.
7. Intent must not be presented as perfect psychological truth.
8. Discovery remains separate from all four Intent dimensions.

---

## 19. Matching, Role Clusters and AI

1. Talent Stream matching must be explainable.
2. LLM output may enrich Role DNA, semantic interpretation or explanations.
3. An LLM must not be sole authority for permission, trust, hard filters or CV access.
4. An LLM should not be sole authoritative determinant of Role Similarity/Candidate Match where reproducible structured logic is available.
5. Professional Match must not increase merely because a candidate clicks often.
6. Intent is not competence.
7. No final hiring/rejection decision should be fully automated solely from Talent Stream ranking.
8. Model/policy versions must be auditable.
9. Role Clustering should combine normalized taxonomy, structured Role DNA, skills/seniority constraints, semantic similarity and versioned thresholds/reasons.
10. Stream breadth (Precise/Balanced/Exploratory or equivalent) may alter retrieval breadth but never weaken Trust/Permission/Source Protection.

---

## 20. Idempotency and financial safety

1. Sensitive write commands tolerate retries safely.
2. One accepted introduction must not consume two credits because of retry.
3. One contact request must not send duplicate invitations.
4. One candidate acceptance must not create duplicate grants.
5. One Intent event retry must not create duplicate canonical events where idempotency applies.
6. Billing and Permission are separate: payment does not create candidate consent.

---

## 21. Derived data and versioning

1. `talent_stream_candidates` and similar read models are reconstructible projections.
2. Projection is never sole Permission/Trust truth.
3. Role Clusters and Intent aggregates are versionable/recomputable.
4. If a projection is lost/corrupted, authoritative data supports rebuild.
5. Candidate profile/preferences, Role DNA, Opportunity Specification, Match/Intent/policy engines and event schemas are version-aware where required.
6. Existing Streams do not silently inherit incompatible source changes.

---

## 22. No-posting Talent Stream

1. Talent Stream must not require publishing a Joboolo job.
2. Own job, allowed reference job and natural-language need converge to one canonical Stream Requirement.
3. External URL support uses the same downstream engine.
4. Do not create separate Talent Stream engines per source.
5. Confidential Stream may hide hiring-company identity initially only under approved policy while Joboolo internally verifies the recruiting actor/company/mandate.

---

## 23. External attribution/tracking

1. Do not implement generalized browser surveillance as the default Cross-Offer strategy.
2. Do not monitor unrelated job-site navigation without an explicit reviewed product/legal/privacy decision.
3. Prefer Joboolo-native events, redirects, explicit candidate actions and ATS integrations.
4. Joboolo must not claim an external application completed without a reliable integration/postback or explicit candidate confirmation.
5. External integrations preserve source/privacy boundaries.

---

## 24. Market/Talent Intelligence

1. Market/Talent availability statistics must be aggregated and privacy-safe.
2. Estimated supply/time-to-introduction outputs are estimates, not guarantees.
3. Diagnostics are phrased as hypotheses, not unsupported causal conclusions.
4. Small-cohort analytics must not reveal individuals.
5. Market Intelligence must never become a route to query individual protected behavior.

---

## 25. Reputation tests

Every feature passes:

- Candidate Surprise Test;
- Screenshot Test;
- Recruiter Fairness Test.

When any test fails, redesign before release.

---

## 26. Explicit reputation / product red lines

Do not implement or market Talent Stream as:

- “see who clicked competitors’ jobs”;
- “buy competitor CVs”;
- “unlock everyone who viewed an offer”;
- “download all interested candidates”.

Do not ship:

- automatic CV/profile sharing after click;
- automatic reveal after private favorite;
- exact competitor-source disclosure;
- a recruiter query exposing precise individual browsing/company history;
- bulk export/mass CV sale as Talent Stream proposition;
- unverified recruiter nominative access;
- current-employer exposure contrary to candidate settings;
- generalized cross-site surveillance;
- opaque fully automated rejection;
- Talent Stream opt-in as a condition for applying;
- fake jobs created primarily to harvest candidates/Intent;
- partner candidate-data rights merely from traffic/feed/CPC status.

---

## 27. Product terminology

Preferred language:

- Talent Stream;
- verified recruiter;
- compatible talent;
- recent activity/interest on similar opportunities;
- controlled/consented introduction;
- Professional Match;
- Opportunity Fit;
- Potential Talent;
- Warm/High-Intent Talent.

Avoid surveillance/dehumanizing wording such as “spy on clicks”, “steal candidates”, “buy CV”, “competitor audience”, or “track candidates everywhere”.

“Hot Talent” may be used internally with care, but external wording remains professional and human.

---

## 28. Commercial rules

1. Do not position Talent Stream as selling personal data.
2. Prefer subscription/Stream access and controlled introductions.
3. “Pay per Accepted Introduction” is an allowed future commercial pattern.
4. Candidate decline/ignore is not accepted-introduction success.
5. Billing logic is idempotent.
6. Monetization never weakens privacy/permission gates.
7. Product-package limits are configuration, not embedded permission logic.

---

## 29. Trust Dashboard rules

Trust health is measured alongside conversion. Where feasible track:

- candidate opt-outs after invitations;
- grant revocations;
- “I never authorized this” complaints;
- over-contact/blocked-invitation rates;
- fake-recruiter/abuse reports and suspensions;
- current-employer exposure incidents;
- privacy/deletion requests;
- negative feedback mentioning surveillance/data sale;
- source-protection/fairness incidents.

Do not optimize Talent Stream primarily for number of CVs exposed.

---

## 30. Development governance

1. `TALENT_STREAM_SPEC.md`, `ARCHITECTURE.md`, this file and `AGENTS.md` are mandatory context for all Talent Stream Phase A-E work.
2. Documentation describes the target system; it does not authorize broad implementation.
3. Current GitHub issue/PR is the only implementation scope.
4. PLAN is read-only unless workflow explicitly enters BUILD.
5. OpenCode must not opportunistically implement future phases.
6. Large refactors require their own issue and explicit approval.
7. Every sensitive-policy change requires tests.
8. ChatGPT architecture/review approval is required before PLAN -> BUILD in the agreed workflow.
9. A Gate-critical failed test blocks release of the corresponding behavior.

---

## 31. Final invariant

> **A good Match is not a permission. Strong Intent is not a permission. Discovery is not Intent. A reference job is not ownership of its audience. A recruiter sees or contacts a talent only when relevance, opportunity compatibility, recruiter trust, source protection, candidate privacy and current authorization are coherent.**
