# Joboolo Talent Stream — Business Rules

**Status:** Binding business invariants for Talent Stream  
**Applies to:** All Phase A-E Talent Stream work  
**Priority:** These rules override implementation convenience.

> The current GitHub issue remains the only authorized implementation scope. This document defines rules that any implementation must respect.

---

## 1. Fundamental separation rules

1. `Professional Match != Intent`.
2. `Intent != Permission`.
3. `Permission != Trust`.
4. `Trust != Match`.
5. `Opportunity Fit != Professional Match`.
6. A ranking may combine signals internally, but the underlying dimensions must remain separately explainable.
7. Do not replace these dimensions with one opaque authoritative “Talent Score”.

---

## 2. Candidate intent and consent

1. A private favorite is not consent to share a profile.
2. A job view is not consent to share a profile.
3. A click is not consent to share a profile.
4. An external redirect click is not consent to reveal identity.
5. A good Match is not permission to contact.
6. A completed application to Company A is not automatic permission to share with Company B.
7. Declared discovery/interest may authorize a controlled introduction only within the candidate’s current policy.
8. Candidate refusal must not reduce Professional Match or punish the candidate in unrelated hiring flows.
9. Absence of recent intent must not automatically exclude a candidate who explicitly enabled discovery.

---

## 3. Discovery Pool

1. Talent Stream must support candidates who are passive/open to opportunities.
2. Discovery Pool eligibility requires explicit discovery authorization and compatible preferences.
3. Intent may raise/lower priority but is not required for every Discovery Pool candidate.
4. Candidate search state such as “paused” does not necessarily mean “do not contact” if discovery remains explicitly enabled.
5. Discovery State and active-search intensity are separate concepts.

---

## 4. Role DNA and Opportunity Specification

1. Role DNA describes the professional role.
2. Opportunity Specification describes the particular recruiting opportunity.
3. Salary, location, remote policy and contract must not be treated as universal attributes of Role DNA.
4. `Role DNA + Opportunity Specification = Stream Requirement`.
5. A reference job may help derive Role DNA but does not authorize copying proprietary audience/data.
6. An existing Stream is bound to a version/snapshot of its Stream Requirement.
7. A source job changing later must not silently mutate the Stream requirement.

---

## 5. Reference jobs and competitor boundaries

1. `Reference Job != Audience Ownership`.
2. Using another public job as a model does not transfer that company’s candidates.
3. A recruiter must not gain access to another recruiter’s application list because their Role DNA is similar.
4. A partner/feed/CPC source is not automatically an authorized recruiter.
5. `traffic_partner != authorized_recruiter`.
6. The source company’s proprietary performance/audience information must not be exposed to a competitor.

---

## 6. Cross-Offer Intent

1. Cross-Offer relevance is role-level relevance, not transfer of a source employer’s audience.
2. Internal Cross-Offer retrieval and recruiter-facing exposure are distinct stages.
3. A candidate may be internally relevant but still not be revealable/contactable.
4. Recruiter exposure requires all applicable source, trust, permission, exclusion and anti-spam policies.
5. The recruiter must never see the exact competitor/source job that produced the signal.
6. Allowed communication is generic, e.g. “recent interest in similar opportunities”.
7. Forbidden communication is source-specific, e.g. “saved Company X’s job yesterday”.
8. Company Intent must not automatically become transferable competitor Role Intent.

---

## 7. Independent Signal Rule

1. One isolated behavior from another employer’s job must not automatically create a nominative competitor lead.
2. Cross-Offer eligibility should require explicit discovery/permission and/or sufficiently independent role-level evidence.
3. Independent evidence may include multiple role-consistent interactions from different sources, declared similar-opportunity interest, or direct candidate acceptance.
4. The final policy must be versioned and auditable.

---

## 8. Source Protection

1. Joboolo must avoid the perception that Recruiter A’s paid acquisition is immediately resold to Recruiter B.
2. Provenance may be retained internally to enforce source protection.
3. Provenance must not become competitor intelligence visible to recruiters.
4. Source Protection may consider source organization, campaign, timing, signal strength and independent evidence.
5. Source Protection must not imply that employers own candidates.
6. Source Protection policy is a trust rule, not a candidate-ownership rule.

---

## 9. Recruiter and organization trust

1. `user_type=employer` alone is insufficient for nominative Talent Stream access.
2. Organization/company identity must be verifiable.
3. Recruiter identity and organization relationship must be verifiable.
4. Agency/RPO use may require a recruiting mandate to the hiring company.
5. Talent Stream access may distinguish requesting organization from hiring company.
6. Unverified or unauthorized recruiting actors must not receive nominative candidate access.
7. Verification state must be checked at sensitive-action time when relevant.

---

## 10. Candidate exclusions

1. Candidate may exclude current employer.
2. Candidate may exclude specific companies and, where supported, agencies/groups.
3. Current-employer exclusion is a security/privacy rule, not a cosmetic preference.
4. Exclusions apply before recruiter contact/reveal.
5. Stale projections must not bypass newly added exclusions.

---

## 11. Contact Governor

1. Contact Governor executes before a real recruiter invitation.
2. Do not send first and check limits later.
3. Contact Governor may enforce:
   - frequency caps;
   - deduplication;
   - minimum eligibility;
   - prior decline/refusal protection;
   - current employer/company exclusions;
   - recruiter trust threshold;
   - salary/location compatibility;
   - saturation/repeat-company constraints.
4. Cross-Offer expansion must not increase recruiter spam.
5. A retry must not create duplicate invitations.

---

## 12. Progressive reveal

1. Talent Stream uses progressive disclosure.
2. Aggregate market data may be shown without identity.
3. Anonymous cards must be privacy-safe, not merely name-redacted.
4. Profile Preview, identity and CV are distinct reveal scopes.
5. `Profile Access != Identity Access` where product states differ.
6. `Profile Access != CV Access`.
7. A candidate must not be tricked into broad sharing through a narrow consent action.

---

## 13. CV/document access

1. Preserve the current strict document ACL philosophy.
2. Candidate owner may access own document.
3. Authorized admin may access according to policy.
4. Employer access through an application requires the valid application/job relationship and exact referenced CV.
5. Talent Stream adds only an active scoped Talent Stream CV grant path.
6. Never introduce broad `if employer: allow` behavior.
7. CV grant must be scoped to the appropriate candidate/document/recruiter or organization/Stream/purpose.
8. Expired or revoked CV grant must deny access immediately.

---

## 14. Current authorization

1. Cached projection data is not an authorization source of truth.
2. Before a sensitive action, evaluate current state.
3. Sensitive actions include at least:
   - reveal identity;
   - reveal detailed profile;
   - reveal contact details;
   - access CV;
   - request introduction;
   - open recruiter-to-candidate messaging.
4. Permission snapshots are for audit/explanation, not present authorization.

---

## 15. Privacy lifecycle

1. Grants/consents must support versioning where required.
2. Relevant records must support expiry and revocation semantics.
3. Revocation must affect future access immediately.
4. TTL deletion is cleanup only; it is not an authorization mechanism.
5. Retention rules must be explicit by data category/purpose.
6. Anonymization/redaction is required where retention of identifiable data is no longer justified.
7. Audit evidence may follow a distinct retention rule from candidate-facing visibility data.

---

## 16. Anonymous Talent privacy

1. Removing a candidate’s name is insufficient anonymization.
2. The anonymous card must avoid trivially identifying combinations.
3. Exact current employer should be hidden before permission unless explicitly justified/authorized.
4. Exact location may require generalization.
5. Rare credentials or unique experience combinations may require redaction/generalization.
6. Market analytics should enforce cohort-size/privacy thresholds where necessary.

---

## 17. CPC and Intent separation

1. CPC/billing events and candidate intent events are separate domains.
2. Do not turn the CPC click ledger into a nominative Talent Stream database.
3. Financial events must remain auditable independently of candidate-discovery events.
4. Candidate intent provenance may reference source context in its own domain where permitted.
5. Partner billing rights do not imply candidate-data rights.

---

## 18. Intent dimensions

1. Keep Job Intent, Role Intent, Company Intent and Market Intent separate.
2. Job Intent refers to one specific job.
3. Role Intent refers to similar roles/Role Cluster.
4. Company Intent refers to one company and is not automatically transferable.
5. Market Intent refers to general employment-market activity.
6. Intent confidence/recency may decay over time.
7. Intent must not be presented as a perfect psychological truth.

---

## 19. Matching and AI

1. Talent Stream matching must be explainable.
2. LLM output may enrich Role DNA, semantic interpretation or explanations.
3. An LLM must not be the sole authority for permission, trust, hard filters or CV access.
4. An LLM should not be the sole authoritative determinant of Role Similarity or Candidate Match when reproducible structured logic is available.
5. Professional Match must not be increased merely because a candidate clicks often.
6. Intent must not be interpreted as competence.
7. No final hiring/rejection decision should be fully automated solely from Talent Stream ranking.
8. Model/policy versions must be auditable.

---

## 20. Idempotency and financial safety

1. Sensitive write commands must tolerate retries safely.
2. One accepted introduction must not consume two credits because of a retry.
3. One contact request must not send duplicate invitations.
4. One candidate acceptance must not create duplicate grants.
5. One intent event retry must not create duplicate canonical events where idempotency applies.
6. Billing and permission state are separate: payment does not itself grant candidate consent.

---

## 21. Derived data

1. `talent_stream_candidates` and similar read models are reconstructible projections.
2. A projection must not be the sole source of permission/trust truth.
3. Derived Role Clusters and Intent aggregates must be versionable/recomputable.
4. If a projection is lost or corrupted, authoritative source data must allow rebuild.

---

## 22. Versioning

1. Candidate profile and preference changes must be version-aware where required for explainability.
2. Role DNA and Opportunity Specification must support versioning.
3. Match/Intent/policy engines must have identifiable versions.
4. Event schemas must be versioned.
5. Consent/policy text versions must be recordable for relevant grants.
6. Existing Streams do not silently inherit incompatible source changes.

---

## 23. No-posting Talent Stream

1. Talent Stream must not require publishing a Joboolo job.
2. Own job, allowed reference job and natural-language need must converge to one canonical Stream Requirement.
3. External URL support must use the same downstream Talent Stream engine.
4. Do not create separate Talent Stream engines per entry source.
5. Confidential Stream may hide the hiring company from the candidate initially only when Joboolo itself has verified the recruiting actor/company and the policy allows the flow.

---

## 24. External tracking red line

1. Do not implement generalized browser surveillance as the default Cross-Offer strategy.
2. Do not monitor unrelated job-site navigation without an explicit, legally/privacy-reviewed product decision.
3. Prefer Joboolo-native events, redirects, explicit candidate actions and ATS integrations.
4. External integrations must preserve source/privacy boundaries.

---

## 25. Reputation rules

Every feature must pass three conceptual tests.

### Candidate Surprise Test

Would a reasonable candidate be surprised by this use of their data?

### Screenshot Test

Would Joboolo be comfortable if this UI/behavior were publicly screenshotted and widely discussed?

### Recruiter Fairness Test

Would a source recruiter reasonably believe Joboolo is unfairly repurposing their investment for a competitor?

When these tests fail, redesign the behavior before release.

---

## 26. Reputation red lines

Do not implement or market Talent Stream as:

- “see who clicked competitors’ jobs”;
- “buy competitor CVs”;
- “unlock everyone who viewed an offer”;
- “download a list of all interested candidates”.

Do not ship:

- automatic CV sharing after click;
- automatic reveal after private favorite;
- exact competitor-source disclosure;
- unverified recruiter access;
- current-employer exposure contrary to candidate settings;
- generalized cross-site surveillance;
- opaque automated rejection.

---

## 27. Product terminology

Preferred language:

- Talent Stream;
- verified recruiter;
- compatible talent;
- recent interest in similar opportunities;
- controlled/consented introduction;
- Professional Match;
- Opportunity Fit;
- Potential Talent;
- Warm/High-Intent Talent.

Avoid dehumanizing or surveillance-oriented language such as:

- “spy on clicks”;
- “steal candidates”;
- “buy CV”;
- “competitor audience”.

“Hot Talent” may be used internally with care, but candidate/recruiter-facing wording should remain professional and human.

---

## 28. Commercial rules

1. Do not position the product as selling personal data.
2. Prefer subscription/Stream access and controlled introductions.
3. “Pay per Accepted Introduction” is an allowed future commercial pattern.
4. Candidate decline must not be treated as accepted-introduction success.
5. Commercial billing logic must be idempotent.
6. Monetization must not weaken privacy/permission gates.

---

## 29. Development governance

1. `TALENT_STREAM_SPEC.md`, `ARCHITECTURE.md` and this file are mandatory context for all Talent Stream Phase A-E work.
2. Documentation describes the target system; it does not authorize broad implementation.
3. The current GitHub issue is the only implementation scope.
4. PLAN must be read-only unless the workflow explicitly enters BUILD mode.
5. OpenCode must not implement future phases opportunistically.
6. Large refactors require their own issue and explicit approval.
7. Every sensitive-policy change requires tests.
8. ChatGPT architecture/review approval is required before the workflow moves from PLAN to BUILD in the agreed process.

---

## 30. Final invariant

Talent Stream must preserve the following truth throughout all phases:

> **A good Match is not a permission. Strong Intent is not a permission. A reference job is not ownership of its audience. A recruiter sees or contacts a talent only when relevance, opportunity compatibility, trust, privacy and current authorization are all coherent.**
