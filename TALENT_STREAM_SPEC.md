# Talent Stream — Canonical Product Specification

**Status:** Canonical reference for Joboolo Talent Stream  
**Version:** 1.1  
**Last architecture review:** 2026-09-03  
**Scope:** Product behavior, user journeys, terminology, trust/privacy constraints, phased capability model  
**Applies to:** All Talent Stream work from Phase A through Phase E

> This document describes the complete target product. Its presence does **not** authorize an implementation agent to build everything described here. The current GitHub issue/PR is always the only authorized implementation scope.

---

## 1. Product position

Talent Stream is the signature service of Joboolo.

It is **not**:

- a CV database sold to recruiters;
- a competitor-audience extraction tool;
- a way to reveal who clicked or saved a competitor job;
- a feature limited to jobs posted on Joboolo;
- a surveillance product following candidates across unrelated sites.

Talent Stream is a continuous sourcing engine that transforms a recruiter need into a structured requirement, identifies professionally compatible talents, interprets role-level intent when available, respects candidate preferences and discovery settings, applies trust/privacy/source-protection rules, and creates controlled introductions.

Canonical value proposition:

> **Find the job that represents your need. Joboolo finds the talents.**

Talent Stream must progressively support four entry modes:

1. Recruiter’s own Joboolo job.
2. Another allowed public Joboolo job used only as a role model.
3. An allowed external job URL used only as a role model.
4. A natural-language recruiter need.

A recruiter must eventually be able to source without publishing a Joboolo job.

---

## 2. Superior trust rule

Joboolo must never give a candidate the impression that they are secretly monitored, sold or transferred, and must never give a recruiter the impression that traffic or acquisition they financed is secretly and immediately resold to competitors.

Talent Stream growth must never be achieved at the expense of trust in Joboolo.

Every product decision must pass three tests:

### Candidate Surprise Test
Would a reasonable candidate be surprised by this use of their data? If yes, obtain clearer permission, anonymize, or do not ship the behavior.

### Screenshot Test
Would Joboolo be comfortable if a screenshot of the behavior became public and widely shared?

### Recruiter Fairness Test
Would a source recruiter reasonably believe Joboolo is unfairly repurposing their investment for a competitor? If yes, apply origin neutrality, source protection, independent-signal rules, or redesign the behavior.

---

## 3. Canonical model

Talent Stream must preserve distinct dimensions rather than hiding them in one opaque score.

Conceptual ranking inputs may include:

`Role DNA × Professional Match × Opportunity Fit × Discovery/Intent × Recency × Trust × Permission`

For Cross-Offer sourcing, the role dimension also uses:

`Role Similarity × Role Clusters × Cross-Offer Evidence`

The arithmetic notation is conceptual only. Permission and Trust are not “scores” that can be traded against Match. A denied authorization remains denied even when Match is excellent.

Canonical separation:

- `Professional Match != Intent`
- `Discovery != Intent`
- `Intent != Permission`
- `Permission != Trust`
- `Opportunity Fit != Professional Match`
- `Reference Job != Audience Ownership`

---

## 4. Candidate Professional Profile / Talent Graph

Represents professional facts useful for matching, progressively including:

- normalized occupations and role history;
- skills and skill evidence;
- experience and seniority;
- certifications;
- languages;
- industry exposure;
- management experience;
- education where relevant;
- portfolio/proofs where candidate chooses to provide them.

The platform should encourage candidates to enrich their profile because better data improves recommendations and opportunities, without making unnecessary disclosure a condition for applying.

---

## 5. Candidate Preferences and Discovery State

Candidate Preferences represent what the candidate wants or accepts, progressively including:

- target roles;
- salary expectations/minimum;
- location, mobility and radius;
- remote/hybrid/on-site preferences;
- contract types;
- industries;
- availability/notice period;
- contact frequency;
- selected-company exclusions;
- current employer exclusion;
- former-employer exclusions where supported;
- agency exclusions;
- willingness to receive similar opportunities.

### Discovery State

Discovery is a separate candidate-controlled state. A candidate may explicitly allow verified recruiters to request introductions for compatible opportunities even when the candidate is not actively searching.

This creates the **Discovery Pool**.

Important rules:

- `Discovery != Intent`.
- Absence of recent observed intent does not mean absence of potential interest.
- “Search paused” and “Discovery enabled” may coexist.
- Refusing or disabling Talent Stream must never reduce the candidate’s chances in an application already submitted.
- Talent Stream activation must never be required to apply to a job.

Candidate-facing discovery controls should progressively support:

- disabled;
- enabled for compatible/similar opportunities;
- ask before reveal/contact;
- anonymous-only preview where supported;
- profile reveal after acceptance;
- CV never automatically shared;
- salary/location/contract/remote filters;
- contact-frequency controls;
- company/agency/current-employer exclusions;
- revocation at any time.

---

## 6. Role DNA, Opportunity Specification and Stream Requirement

### Role DNA

Role DNA describes the professional role itself, not the commercial conditions of one particular opportunity.

It may contain:

- canonical occupation and role family;
- seniority;
- hard skills;
- secondary/transferable skills;
- responsibilities;
- experience requirements;
- certifications;
- management dimension;
- language requirements.

### Opportunity Specification

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

A reference job may inform Role DNA, but its proprietary commercial conditions must not be blindly copied into the recruiter’s Opportunity Specification.

A Stream binds to a version/snapshot of its Stream Requirement. A source job changing later must not silently redefine an existing Stream.

---

## 7. Professional Match and Opportunity Fit

### Professional Match

Measures candidate professional compatibility with Role DNA.

It should provide structured, explainable reasons such as:

- required skills matched;
- experience/seniority alignment;
- relevant role history;
- missing or uncertain requirements;
- evidence to verify.

### Opportunity Fit

Measures compatibility between candidate preferences and the Opportunity Specification.

Examples:

- salary compatibility;
- location/mobility;
- remote policy;
- contract;
- availability.

A candidate with a 96% professional Match may still be a poor opportunity fit if salary, location or working model are incompatible.

Intent must never be treated as proof of competence or used to inflate Professional Match.

---

## 8. Intent Graph

Intent is distinct from Discovery and contains four dimensions.

### Job Intent
Interest in one specific job.

### Role Intent
Interest in a family/cluster of sufficiently similar roles. This is the principal intent dimension for Cross-Offer Talent Stream.

### Company Intent
Interest in one company. Company Intent must not automatically be transferred to competitors as Role Intent.

### Market Intent
Evidence that the candidate is active in the employment market more generally.

Intent evidence may be **declared** or **observed**.

### Declared intent examples

- “I’m interested” for a role/opportunity;
- explicitly shared favorite/interest;
- candidate accepts an introduction;
- candidate submits an application.

**Discovery enablement is not an intent event.** It is a separate permission/preference state.

### Observed intent examples

- job view;
- repeat views;
- Joboolo-controlled external click;
- recent exploration of several sufficiently similar roles.

Observed signals may support ranking, aggregation and Role Intent inference but do not automatically grant recruiter access to identity, contact details or CV.

Observed/inferred intent is probabilistic. Recruiter-facing language must avoid falsely claiming psychological certainty. Prefer “recent activity/interest on similar roles” rather than “the candidate definitely wants this job”.

---

## 9. Talent sources and recruiter views

Talent Stream supports at least three conceptual talent categories.

### Applicants
Candidates who explicitly applied to the recruiter’s own job/opportunity. Existing application rights remain governed by the application workflow and document ACL.

### Warm / High-Intent Talents
Candidates with strong professional compatibility plus meaningful recent Role Intent and enough policy permission to be considered for a controlled introduction.

### Potential Talents / Discovery Pool
Candidates with strong Match and Opportunity Fit who explicitly enabled Discovery, even when recent intent is weak or unknown.

Intent enriches priority; it is not a mandatory condition for existence in the Stream.

A recruiter UX may expose these as separate tabs/filters such as Applicants, Warm Talents and Potential Talents without exposing prohibited source behavior.

---

## 10. Candidate actions

### Save / Favorite

A favorite is private by default.

`favorite != consent`

Do not change the semantic meaning of the existing private saved-job feature. After saving, Joboolo may separately ask whether the candidate also wants to signal interest or be discovered for similar opportunities.

### “I’m interested”

A lightweight explicit-interest action between save and full application.

### Discovery for similar opportunities

Candidate setting concept:

> “I want verified recruiters to be able to discover me for opportunities similar to those that interest me.”

It remains separable from applying to a job.

---

## 11. Progressive reveal

Talent Stream uses progressive disclosure.

### Level 0 — Market Aggregate
Counts and market information only.

### Level 1 — Anonymous Talent
Professional summary with privacy-safe generalization and no trivially identifying combination of attributes.

### Level 2 — Profile Preview
More detail only when candidate policy permits.

### Level 3 — Identity
Identity revealed only when current authorization permits it.

### Level 4 — CV
A specific CV/document is shared only under an active scoped grant.

Important rules:

- removing a name is not sufficient anonymization;
- profile permission is not identity permission where the product distinguishes them;
- profile/identity permission is not CV permission;
- every sensitive action checks current authorization, never a stale projection snapshot;
- rare credentials, exact employer/location or unusual experience combinations may require redaction/generalization.

---

## 12. Recruiter introduction flow

Canonical controlled flow:

1. Recruiter and organization/mandate are verified and eligible.
2. Candidate is retrieved by Match plus Discovery and/or eligible Intent.
3. Candidate exclusions, source protection and current discovery/contact policies run.
4. Contact Governor verifies limits and anti-spam rules.
5. Recruiter may request an introduction.
6. Candidate receives sufficient opportunity context to make a meaningful choice: role, location, salary/contract when available, and company identity unless an approved confidential-recruiting policy applies.
7. Candidate may accept, decline or ignore.
8. Acceptance creates/activates the appropriate scoped grant.
9. Profile/identity becomes visible only to the authorized extent.
10. CV remains optional and separately authorized.
11. Messaging becomes available only through an accepted application relationship or active Talent Stream contact grant.

A declined/ignored introduction must not reveal additional personal data and must not punish the candidate in unrelated matching/application flows.

---

## 13. Recruiter / organization trust

Talent Stream nominative access is for verified recruiting actors only.

The architecture must distinguish:

- organization/company identity;
- organization membership;
- recruiter identity;
- requesting organization;
- hiring company;
- agency/RPO mandate when applicable.

A traffic partner, XML partner, feed partner or CPC partner is not automatically an authorized recruiter.

`traffic_partner != authorized_recruiter`

Trust controls may include professional email/domain validation, company verification, membership checks, stronger identity/KYB for sensitive access, mandate verification for agencies, audit history, abuse reports and suspension state.

---

## 14. Candidate protections

Candidate protections include progressively:

- Talent Stream on/off;
- similar opportunities allowed/not allowed;
- ask before reveal/contact;
- anonymous-only state where supported;
- salary/location/contract/remote boundaries;
- maximum contact frequency;
- current employer exclusion;
- selected-company/former-employer exclusions;
- agency exclusions;
- CV-specific grants;
- revocation/expiry.

Current-employer exclusion is a security/privacy rule, not merely an interface preference.

An accidental current-employer exposure is a critical trust incident and must be observable/auditable.

---

## 15. Contact Governor

Contact Governor runs before any real recruiter invitation.

It must progressively enforce:

- maximum invitations over time;
- duplicate/repeat protection;
- minimum eligibility/match constraints;
- salary/location compatibility where applicable;
- recruiter trust threshold;
- current-employer/company exclusions;
- prior rejection/decline history;
- per-company cooling rules;
- saturation controls.

A retry must not create duplicate contact requests or invitations.

Talent Stream must never become recruiter spam infrastructure.

---

## 16. Role Similarity and Role Clusters

Role Clusters should not be an opaque LLM-only grouping.

Target strategy is hybrid and explainable:

- normalized occupation taxonomy;
- structured Role DNA fields;
- skills/seniority/business constraints;
- semantic embeddings where useful;
- explicit thresholds/rules;
- versioned reason codes/evidence.

Offer Similarity, Candidate Match and Candidate Intent remain separate concepts.

Recruiters may eventually control Stream breadth through policies such as:

- **Precise** — narrow cluster/similarity;
- **Balanced** — default trade-off;
- **Exploratory** — wider adjacent roles, still subject to Match/Fit/permission.

Breadth must never weaken privacy, source protection or trust gates.

---

## 17. Cross-Offer Intent

Cross-Offer Intent is a defining Talent Stream capability.

If Job A and Job B have sufficiently similar Role DNA, a candidate interacting with Job B may be relevant to a Stream created from Job A, subject to Match, Opportunity Fit, provenance/evidence policy, source protection, privacy and candidate permission.

Canonical pipeline:

1. Build Role DNA for the Stream Requirement.
2. Find sufficiently similar Role DNA / Role Cluster members.
3. Retrieve candidates connected through Discovery and/or eligible intent evidence.
4. Re-score candidate against the Stream’s own Role DNA.
5. Apply Opportunity Fit.
6. Apply provenance/evidence policy.
7. Apply Independent Signal Rule.
8. Apply origin neutralization and Source Protection.
9. Apply Trust, exclusions and current Permission.
10. Apply Contact Governor.
11. Produce a privacy-safe recruiter projection.

### Origin neutrality

Recruiters must never be told the precise competitor/source job that created a candidate signal.

Allowed:

> “Strong recent interest in similar Systems Engineering opportunities.”

Forbidden:

> “This candidate saved Company X’s job yesterday.”

### Independent Signal Rule

A single isolated interaction generated by another company must not automatically transfer a candidate to a competitor as a nominative lead.

Eligibility requires explicit discovery/permission and/or sufficiently independent evidence such as multiple role-consistent signals from independent sources or a direct candidate acceptance.

A candidate’s application to another company may be strong Role Intent evidence, but it does **not** create a cross-company CV/profile grant.

---

## 18. Source Protection and Source Protection Window

Joboolo must avoid the perception that one recruiter’s paid acquisition is immediately repurposed to solicit the same candidate for a competitor.

Source-protection policy may consider:

- provenance;
- source organization/campaign;
- paid versus organic acquisition context;
- signal strength;
- timing/recency;
- independent signals;
- explicit candidate discovery permission.

The architecture must support a configurable **Source Protection Window** or equivalent cooling rule for paid/source-sensitive signals. The exact duration is a versioned product/trust policy and must not be hardcoded into the domain model.

Source Protection protects recruiter trust without treating candidates as owned by employers.

---

## 19. Reference jobs and no-posting sourcing

A public job can be used as a semantic/model reference, not as a transfer of audience rights.

Correct architecture:

`reference job -> Role DNA -> Opportunity Specification/Stream Requirement -> Talent/Intent retrieval -> policies -> Talent Stream`

Forbidden architecture:

`reference job -> its candidates -> competitor`

The no-posting wizard must support a common downstream pipeline for:

- own Joboolo job;
- another allowed Joboolo job;
- natural-language need;
- later, an allowed external URL.

All sources converge to the same canonical Stream Requirement and one Talent Stream engine.

Using another company’s job as a model must not unnecessarily retain or rebroadcast its full text when derived Role DNA is sufficient.

---

## 20. Confidential recruiting

Confidential recruiting is a valid Talent Stream use case.

A company may be hidden from the candidate at an early stage only under a deliberate product policy. Joboolo itself must still know and verify the recruiter, recruiting organization, hiring company and mandate when applicable.

“Confidential” must never mean “unverified”. The candidate must receive enough information to make an informed decision before identity/CV sharing or meaningful progression.

---

## 21. External jobs / ATS and attribution certainty

Progressive external coverage:

1. Joboolo redirect attribution.
2. ATS postback for apply-started/apply-completed where supported.
3. ATS/API/webhook integrations.
4. External job URL -> safe Role DNA extraction.
5. Optional deeper Joboolo Connect capabilities only after trust/privacy review.

Certainty rule:

- Joboolo can know a redirect/click it generated.
- Joboolo cannot claim that an external application was completed unless an integration/postback or explicit candidate action confirms it.
- Direct activity on LinkedIn, Google, a career site or another platform that never passes through Joboolo is not observable by default and must not be pretended to be known.

Do not begin with generalized browser-extension/cross-site surveillance.

---

## 22. Matching and AI architecture expectations

The existing LLM matching capability may remain useful for semantic enrichment and explanations, but Talent Stream’s authoritative decisions must be reproducible, versioned and testable.

Target approach:

- structured features;
- normalized taxonomy;
- semantic embeddings where useful;
- deterministic rules/hard filters;
- explainable scoring;
- LLM enrichment/explanation as supporting functionality, not sole decision maker.

Do not use Intent as proof of competence.

No final hiring/rejection decision should be fully automated solely from Talent Stream ranking.

Responsible-AI requirements such as model/policy versioning, reason codes, human oversight and auditability are horizontal requirements, not a late cosmetic feature.

---

## 23. Market/Talent Intelligence

Before or alongside activation, a Stream may progressively show privacy-safe market availability such as:

- compatible pool count;
- high-match count;
- Discovery-enabled/invitable count;
- warm/recent-intent count;
- geographic distribution;
- salary distribution/median where sufficiently aggregated;
- scarce skills;
- competition/availability indicators;
- estimated time to useful introductions, clearly presented as an estimate rather than certainty.

Job diagnostics may suggest hypotheses such as missing salary, too-narrow constraints or external-apply friction. Wording must remain probabilistic (“may indicate”), not falsely causal.

Market intelligence must use privacy/cohort thresholds so small groups do not re-identify candidates.

---

## 24. Commercial model principles

Do not market Talent Stream as “buy CVs”, “unlock contacts” or competitor candidate resale.

Preferred concepts:

- Talent Stream access/subscription;
- verified recruiter sourcing;
- controlled/consented introductions;
- accepted-introduction credits.

A strong future charging model is **Pay per Accepted Introduction**:

- recruiter requests introduction;
- candidate declines/ignores -> no accepted-introduction charge;
- candidate accepts -> credit may be consumed according to commercial policy.

Commercial charging must be idempotent and separated from permission itself. Payment never creates candidate consent.

Subscription/package names or limits (for example Start/Pro/Team and number of active Streams) are commercial configuration, not hardcoded canonical domain rules.

---

## 25. Analytics and Trust Dashboard

Business/product analytics should progressively cover:

- Stream activation;
- eligible pool depth;
- anonymous talent depth;
- contact requests;
- acceptance/decline/ignore;
- Stream -> application;
- Stream -> interview;
- Stream -> hire;
- time to first useful talent;
- recruiter repeat usage;
- revenue/credits per Stream.

Trust metrics must be first-class and include where feasible:

- candidate opt-outs after invitation;
- grant revocations;
- “I never authorized this” complaints;
- excessive-contact/blocked invitation rates;
- recruiter abuse/fake-recruiter reports;
- recruiter suspensions;
- current-employer exposure incidents;
- candidate deletion/privacy requests;
- negative feedback/reviews mentioning surveillance or data sale;
- source-protection/fairness incidents.

Do not optimize primarily for number of CVs revealed.

---

## 26. Explicit no-go list

Do not implement or ship the following as Talent Stream behavior:

1. Auto-share a CV/profile because a candidate clicked.
2. Auto-share because a candidate privately saved/favorited a job.
3. Tell a recruiter exactly which competitor job/company a candidate viewed, clicked, saved or applied to.
4. Let recruiters query a candidate’s precise browsing/company-interest history.
5. Sell/export bulk personal candidate lists or mass CV downloads as the product proposition.
6. Use generalized browser surveillance/extensions to track unrelated job-site activity by default.
7. Require Talent Stream discovery activation to apply for a job.
8. Penalize an application because the candidate refuses Talent Stream discovery or an introduction.
9. Reveal job-search activity to the candidate’s current employer against exclusion settings.
10. Grant candidate access rights to a traffic/feed/CPC partner merely because it supplied the job/traffic.
11. Fully automate final hiring/rejection decisions based solely on Talent Stream ranking.
12. Create fake/placeholder jobs whose primary purpose is harvesting candidates or intent for a pool.
13. Treat a reference job as ownership of its audience.
14. Bypass current CV ACLs with a broad employer/recruiter role check.

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

Avoid surveillance/dehumanizing language such as:

- “spy on clicks”;
- “steal competitor candidates”;
- “buy CVs”;
- “recover competitor audience”;
- “track candidates everywhere”.

“Hot Talent” may be used internally with care, but external wording should remain professional and human.

---

## 28. Strategic data graphs

Talent Stream progressively reuses four related data assets:

- **Job Graph** — jobs, companies, locations, salary, sectors, requirements;
- **Role Graph** — normalized roles, skills, relationships and Role Clusters;
- **Talent Graph** — candidate professional profile, evidence and preferences;
- **Intent Graph** — Job/Role/Company/Market intent evidence.

These graphs are conceptual data products within the modular monolith; this terminology does not require a graph database or microservices.

The strategic flywheel is trust-first:

more quality jobs/roles -> better Role DNA/Clusters -> better interactions and discovery -> better matching/Streams -> more useful introductions -> more recruiter/candidate value.

Hidden surveillance or uncontrolled disclosure would create reputational debt rather than a defensible moat.

---

## 29. Product phases

### Phase A — Talent Engine & Trust Foundation

Build canonical profile, preferences/discovery, Role DNA, Opportunity Specification, Match, hard eligibility, organization/recruiter trust, permissions, privacy, intent contracts/provenance, audit/versioning and migration foundations.

### Phase B — Talent Stream MVP

Own-job Stream using applications, declared interest, shared favorites and Discovery Pool; anonymous talent view; Contact Governor; contact request; candidate decision; progressive reveal; CV grant; messaging; basic analytics.

Observed Cross-Offer behavior is not recruiter-visible in Phase B.

### Phase C — Cross-Offer Intent & Moat

Role similarity, Role Clusters, observed intent, intent dimensions, internal Cross-Offer retrieval, independent-signal policy, origin neutralization, Source Protection/Window, Cross-Offer permission, Contact Governor v2, Opportunity Fit and safe recruiter projection.

### Phase D — No-Posting Talent Stream

Own job, another Joboolo job and natural-language need converge to a common Stream Requirement. Add confidential Stream, market preview and later safe external URL sourcing.

### Phase E — Intelligence & Scale

ATS integrations, recruiter OS/CRM, Market/Salary Intelligence, Talent Rediscovery expansion, skills/career graph, Skill Gap, Skills Passport, assessments, Train-to-Hire, candidate agent and other ecosystem capabilities.

---

## 30. Gate definitions

### G0 — Baseline
Current Joboolo baseline/security integrity is stable enough to begin Talent Stream foundations.

### GA — Talent Engine & Trust Ready
Required before MVP candidate exposure. Canonical profile/preferences/discovery, Role DNA/Opportunity Spec, explainable Match, organization/recruiter/mandate model, authorization/grants, privacy lifecycle, preserved CV ACL, intent/provenance contract, audit/versioning and migration/index safety must be ready to the depth required by Phase B.

### GB — Talent Stream MVP Ready
End-to-end own-job controlled flow works from verified recruiter/need through safe retrieval, Contact Governor, candidate decision, current authorization, profile/CV grant and messaging. No recruiter-visible Cross-Offer observed behavior yet.

### GC — Cross-Offer Safe & Effective
Cross-Offer retrieval is not exposed until origin neutrality, independent-signal policy, Source Protection/Window, permission, trust, anti-spam, Opportunity Fit and privacy protections are proven.

### GD — No-Posting Ready
Own job, another allowed Joboolo job and natural-language need converge to one canonical Stream Requirement and one Talent Stream engine; external URLs use the same pipeline when enabled.

### GE — Talent Platform Ready
Scale, integrations, intelligence, observability, privacy/trust metrics and ecosystem capabilities meet platform requirements.

---

## 31. Canonical final principle

Talent Stream must always preserve this truth:

> **A good Match is not a permission. Strong Intent is not a permission. Discovery is not Intent. A reference job is not ownership of its audience. A recruiter sees or contacts a talent only when professional relevance, opportunity compatibility, trust, privacy and current authorization are coherent.**

**Joboolo must never grow Talent Stream at the expense of candidate or recruiter trust.**
