# Talent Stream — Canonical Product Specification

**Status:** Canonical reference for Joboolo Talent Stream  
**Scope:** Product behavior, user journeys, terminology, trust/privacy constraints, phased capability model  
**Applies to:** All Talent Stream work from Phase A through Phase E

> This document describes the complete target product. Its presence does **not** authorize an implementation agent to build everything described here. The current GitHub issue is always the only authorized implementation scope.

---

## 1. Product position

Talent Stream is the signature service of Joboolo.

It is not a CV database, not a competitor-audience extraction tool, and not a feature limited to jobs posted on Joboolo.

Talent Stream is a continuous sourcing engine that transforms a recruiter need into a structured role requirement, finds compatible talents, interprets role-level intent when available, applies candidate preferences and trust/privacy rules, and creates controlled introductions.

Canonical value proposition:

> **Find the job that represents your need. Joboolo finds the talents.**

Talent Stream must progressively support four entry modes:

1. Recruiter’s own Joboolo job.
2. Another public Joboolo job used only as a role model.
3. An allowed external job URL used only as a role model.
4. A natural-language recruiter need.

A recruiter must eventually be able to source without publishing a Joboolo job.

---

## 2. Canonical formula

Talent Stream is conceptually:

`Role DNA × Candidate Match × Opportunity Fit × Discovery/Intent × Recency × Trust × Permission`

For Cross-Offer sourcing, the role dimension also uses:

`Role Similarity × Role Clusters × Cross-Offer Intent`

These dimensions must remain distinguishable. They must not be collapsed into one opaque score that hides their meaning.

---

## 3. Core domain concepts

### 3.1 Candidate Professional Profile

Represents professional facts useful for matching, such as:

- normalized occupations;
- professional skills;
- experience;
- seniority;
- certifications;
- languages;
- industry exposure;
- management experience;
- evidence/proofs when available.

### 3.2 Candidate Preferences

Represents what the candidate wants or accepts, including progressively:

- target roles;
- salary expectations/minimum;
- location and mobility;
- remote/hybrid/on-site preferences;
- contract types;
- industries;
- availability;
- contact frequency;
- companies/agencies to exclude;
- current employer exclusion;
- willingness to receive similar opportunities.

### 3.3 Discovery State

A candidate may explicitly allow verified recruiters to request introductions for compatible opportunities even when the candidate is not actively searching.

This creates a **Discovery Pool**.

Important rule:

> Absence of recent observed intent does not mean absence of potential interest.

A passive/open candidate may be a Potential Talent if Match, Opportunity Fit, Trust and Permission allow it.

### 3.4 Role DNA

Role DNA describes the professional role itself, not the commercial conditions of one specific job.

It may contain:

- canonical occupation;
- role family;
- seniority;
- hard skills;
- secondary/transferable skills;
- responsibilities;
- experience requirements;
- certifications;
- management dimension;
- language requirements.

### 3.5 Opportunity Specification

Opportunity Specification describes the constraints of one specific recruiting need, such as:

- salary/budget;
- location/radius;
- remote policy;
- contract;
- schedule;
- sector/company constraints;
- must-have versus nice-to-have requirements;
- target availability.

Canonical relationship:

`Role DNA + Opportunity Specification = Stream Requirement`

A reference job from another company may inform Role DNA, but its proprietary commercial conditions must not be blindly copied into the recruiter’s Opportunity Specification.

### 3.6 Professional Match

Measures candidate professional compatibility with Role DNA.

Professional Match must be explainable with structured reasons such as:

- required skills matched;
- experience/seniority alignment;
- relevant role history;
- missing or uncertain requirements.

### 3.7 Opportunity Fit

Measures compatibility between candidate preferences and the Opportunity Specification.

Examples:

- salary compatibility;
- location/mobility;
- remote policy;
- contract;
- availability.

Professional Match and Opportunity Fit are separate.

---

## 4. Intent model

Talent Stream distinguishes four intent dimensions.

### Job Intent

Interest in one specific job.

### Role Intent

Interest in a family of sufficiently similar roles. This is the principal intent dimension for Cross-Offer Talent Stream.

### Company Intent

Interest in one company. Company Intent must not automatically be treated as transferable Role Intent toward competitors.

### Market Intent

Overall evidence that the candidate is active in the employment market.

Intent may be **declared** or **observed**.

### Declared intent examples

- “I’m interested”;
- explicitly shared favorite;
- candidate accepts an introduction;
- candidate enables discovery for similar opportunities;
- completed application to the relevant employer/job.

### Observed intent examples

- view;
- repeat views;
- external click;
- recent exploration of several similar roles.

Observed intent may improve ranking/aggregation but does not automatically grant recruiter access to identity or CV.

---

## 5. Talent sources

Talent Stream supports three primary talent categories.

### Applicants

Candidates who explicitly applied to the recruiter’s job or opportunity.

### Warm / High-Intent Talents

Candidates with strong professional compatibility plus meaningful recent Role Intent and sufficient permission.

### Potential Talents / Discovery Pool

Candidates with strong Match and Opportunity Fit who have enabled discovery, even if recent intent is weak or unknown.

Intent enriches priority; it is not a mandatory condition for existence in the Stream.

---

## 6. Candidate actions

### Save / Favorite

A favorite is private by default.

`favorite != consent`

After saving, Joboolo may separately ask whether the candidate also wants to signal interest or be discovered for similar opportunities.

### “I’m interested”

A lightweight explicit-interest action between save and full application.

### Discovery for similar opportunities

Candidate setting concept:

> “I want verified recruiters to be able to discover me for opportunities similar to those that interest me.”

It must remain separable from the act of applying to a job.

---

## 7. Progressive reveal

Talent Stream must use progressive disclosure.

### Level 0 — Aggregate

Counts and market information only.

### Level 1 — Anonymous Talent

Professional summary with privacy-safe generalization and no trivially identifying combination of attributes.

### Level 2 — Profile Preview

More detail only when allowed by candidate policy.

### Level 3 — Identity

Identity revealed only when current authorization allows it.

### Level 4 — CV

A specific CV/document is shared only under an active scoped grant.

Important rules:

- profile permission is not CV permission;
- identity permission is not CV permission;
- every sensitive action checks current authorization, not a stale projection snapshot.

---

## 8. Recruiter introduction flow

Canonical controlled flow:

1. Recruiter is verified and authorized for the hiring organization/mandate.
2. Candidate is retrieved by Match plus Discovery and/or Intent.
3. Trust, candidate exclusions, source protection and permission policies run.
4. Contact Governor verifies limits and anti-spam rules.
5. Recruiter may request an introduction.
6. Candidate may accept, decline or ignore.
7. Acceptance creates/activates the appropriate scoped grant.
8. Profile/identity becomes visible only to the extent authorized.
9. CV remains optional and separately authorized.
10. Messaging becomes available only through an accepted application relationship or active Talent Stream contact grant.

A declined introduction must not reveal additional personal data.

---

## 9. Trust and recruiter eligibility

Talent Stream nominative access is for verified recruiting actors only.

The architecture must distinguish:

- organization/company identity;
- organization membership;
- recruiter identity;
- hiring company;
- agency/RPO mandate when applicable.

A traffic partner, XML partner or CPC partner is not automatically an authorized recruiter.

`traffic_partner != authorized_recruiter`

---

## 10. Candidate protections

Candidate controls must progressively include:

- Talent Stream on/off;
- similar opportunities allowed/not allowed;
- ask before reveal;
- anonymous-only state where supported;
- salary, location, contract and remote boundaries;
- maximum contact frequency;
- current employer exclusion;
- selected-company exclusions;
- agency exclusions;
- CV-specific grants;
- revocation.

Current-employer exclusion is a security/privacy rule, not merely an interface preference.

---

## 11. Contact Governor

The Contact Governor runs before any recruiter invitation.

It must progressively enforce:

- maximum invitations over time;
- duplicate/repeat protection;
- minimum eligibility/match constraints;
- salary/location compatibility where applicable;
- recruiter trust threshold;
- current-employer/company exclusions;
- prior rejection/decline history;
- saturation controls.

Talent Stream must never become recruiter spam infrastructure.

---

## 12. Cross-Offer Intent

Cross-Offer Intent is a defining Talent Stream capability.

If Job A and Job B have sufficiently similar Role DNA, a candidate interacting with Job B may be relevant to a Stream created from Job A, subject to Match, Opportunity Fit, source protection, privacy and candidate permission.

Canonical pipeline:

1. Build Role DNA for the Stream requirement.
2. Find sufficiently similar Role DNA / Role Cluster members.
3. Retrieve candidates connected to those roles through Discovery and/or eligible intent evidence.
4. Re-score the candidate against the Stream’s own Role DNA.
5. Apply Opportunity Fit.
6. Apply provenance/evidence policy.
7. Apply source protection.
8. Apply Trust and Permission.
9. Apply Contact Governor.
10. Produce a privacy-safe recruiter projection.

### Origin neutrality

The recruiter must never be told the precise competitor/source job that created a candidate signal.

Allowed wording:

> “Strong recent interest in similar Systems Engineering opportunities.”

Forbidden wording:

> “This candidate saved Company X’s job yesterday.”

### Independent Signal Rule

A single isolated interaction generated by another company must not automatically transfer a candidate to a competitor as a nominative lead.

Eligibility must rely on explicit discovery/permission and/or sufficiently independent evidence.

### Source Protection

Joboolo must avoid creating the perception that one recruiter’s paid acquisition is immediately resold to a competitor.

Source-protection policy may consider:

- provenance;
- campaign/source organization;
- signal strength;
- timing;
- independent signals;
- explicit candidate discovery permission.

Source Protection protects trust without treating candidates as owned by employers.

---

## 13. Reference jobs and no-posting sourcing

A public job can be used as a semantic/model reference, not as a transfer of audience rights.

Correct architecture:

`reference job -> Role DNA -> Stream Requirement -> Talent Graph/Intent Graph -> policies -> Talent Stream`

Forbidden architecture:

`reference job -> its candidates -> competitor`

The final no-posting wizard must support a common downstream pipeline for:

- own Joboolo job;
- another allowed Joboolo job;
- natural-language need;
- later, allowed external URL.

All sources must converge to the same canonical Stream Requirement.

---

## 14. External jobs / ATS

Progressive external coverage:

1. Joboolo redirect attribution.
2. ATS postback for apply started/completed where supported.
3. ATS/API/webhook integrations.
4. External job URL -> safe Role DNA extraction.
5. Optional deeper Joboolo Connect capabilities only after trust/privacy review.

Do not begin with generalized cross-site browser surveillance or an extension that observes candidates across unrelated job sites.

---

## 15. Matching architecture expectations

The existing LLM matching capability may remain useful for semantic enrichment and explanations, but Talent Stream’s authoritative decisions must be reproducible and versioned.

Target approach:

- structured features;
- normalized taxonomy;
- semantic embeddings where useful;
- deterministic rules/hard filters;
- explainable scoring;
- LLM enrichment/explanation as a supporting component, not sole decision maker.

No fully automated final hiring/rejection decision should be based solely on Talent Stream ranking.

---

## 16. Reputation-first requirements

Before introducing any new Talent Stream behavior, apply these tests.

### Surprise Test

Would a reasonable candidate be surprised to learn that Joboolo uses this data in this way?

If yes, obtain clearer permission, anonymize, or do not ship the behavior.

### Screenshot Test

Would Joboolo be comfortable if a screenshot of this feature became public and widely shared?

### Recruiter Fairness Test

Would the source recruiter reasonably believe Joboolo is using their investment or audience to serve competitors unfairly?

### Reputation red lines

Do not ship:

- automatic CV sharing after a click;
- automatic profile sharing after a private favorite;
- exact disclosure of competitor-source behavior;
- downloadable mass CV lists as the Talent Stream proposition;
- generalized cross-site surveillance;
- access for unverified recruiters;
- exposure to current employer against candidate settings;
- a single opaque “Talent Score” that hides Match, Intent, Trust and Permission;
- automatic final hiring/rejection decisions.

---

## 17. Commercial model principles

Do not market Talent Stream as “buy CVs”.

Preferred model language:

- Talent Stream access/subscription;
- verified recruiter sourcing;
- controlled introductions;
- accepted-introduction credits.

A strong future charging model is **Pay per Accepted Introduction**:

- recruiter requests introduction;
- candidate declines -> no accepted-introduction charge;
- candidate accepts -> credit may be consumed according to commercial policy.

Commercial charging must be idempotent and separated from permission itself.

---

## 18. Analytics and quality metrics

Talent Stream analytics should progressively cover:

- Stream activation;
- number of eligible talents;
- anonymous talent pool depth;
- contact requests;
- candidate acceptance/decline;
- Stream -> application;
- Stream -> interview;
- Stream -> hire;
- time to first useful talent;
- opt-out rate;
- recruiter report/abuse rate;
- candidate complaints;
- excessive-contact rate;
- revenue/credits per Stream.

Do not optimize primarily for number of CVs revealed.

---

## 19. Product phases

### Phase A — Talent Engine & Trust Foundation

Build the canonical profile, preference/discovery, Role DNA, Opportunity Specification, Match, hard eligibility, organization/recruiter trust, permissions, privacy, intent contracts, audit/versioning and migration foundations.

### Phase B — Talent Stream MVP

Own-job Stream using applications, declared interest, shared favorites and Discovery Pool; anonymous talent view; Contact Governor; contact request; candidate decision; progressive reveal; CV grant; messaging; basic analytics.

### Phase C — Cross-Offer Intent & Moat

Role similarity, Role Clusters, observed intent, intent dimensions, internal Cross-Offer retrieval, independent-signal policy, origin neutralization, Source Protection, Cross-Offer permission, Contact Governor v2, Opportunity Fit and safe recruiter projection.

### Phase D — No-Posting Talent Stream

Own job, another Joboolo job and natural-language need converge to a common Stream Requirement. Add confidential Stream and later allowed external URL sourcing.

### Phase E — Intelligence & Scale

ATS integrations, recruiter OS/CRM, Market Intelligence, Salary Intelligence, Talent Rediscovery expansion, skills/career graph, Skill Gap, Skills Passport, assessments, Train-to-Hire, candidate agent and other ecosystem capabilities.

---

## 20. Gate definitions

### GA — Talent Engine & Trust Ready

Required before the MVP can safely expose candidates.

### GB — Talent Stream MVP Ready

End-to-end own-job Stream works with declared/discovery sources, Contact Governor, candidate decision, current authorization, profile/CV grants and messaging.

### GC — Cross-Offer Safe & Effective

Cross-Offer retrieval is not exposed until origin neutrality, independent-signal policy, Source Protection, permission, trust and anti-spam protections are proven.

### GD — No-Posting Ready

Different recruiter need sources converge to one canonical Stream Requirement and one Talent Stream engine.

### GE — Talent Platform Ready

Scale, integrations, intelligence, observability and ecosystem capabilities meet platform requirements.

---

## 21. Canonical product principle

Talent Stream must always preserve this separation:

`Good Match != Permission`  
`Strong Intent != Permission`  
`Reference Job != Audience Ownership`

A talent becomes revealable/contactable only when professional relevance, opportunity compatibility, trust, privacy and current permission are coherent.

**Joboolo must never grow Talent Stream at the expense of candidate or recruiter trust.**
