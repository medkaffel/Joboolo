# Joboolo Agent Instructions

## Talent Stream mandatory context

Talent Stream is the signature Joboolo service.

For **every GitHub issue or pull request related to Talent Stream or any Phase A-E lot**, an implementation/review agent MUST read **in full**, before planning or modifying code:

1. `TALENT_STREAM_SPEC.md` — canonical product specification.
2. `ARCHITECTURE.md` — canonical architecture, domains, Circles, dependencies, Phases, lots and Gates.
3. `BUSINESS_RULES.md` — binding non-negotiable business, trust, privacy and reputation rules.
4. This `AGENTS.md` file.

If one of these files is missing or unreadable, report the blocker rather than inventing an alternative specification.

## Scope rule

The canonical documents describe the **complete target system**. They are context, not authorization to implement the roadmap.

The **current GitHub issue/PR is always the only authorized implementation scope**.

Do not implement a future Phase, adjacent lot, higher/lower Circle feature, opportunistic refactor or inferred requirement merely because it appears in canonical documentation.

The issue should identify or imply the intended **Phase / Circle / Gate contribution**. If the requested implementation would cross a Gate or require a future lot, stop in PLAN and report the dependency instead of implementing it silently.

When canonical documentation and the issue appear inconsistent:

- do not silently choose one;
- identify the conflict in PLAN/review;
- preserve safety/privacy/trust invariants;
- request/await an explicit architecture decision before implementing conflicting behavior.

## Required engineering principles

For Talent Stream work, preserve at minimum:

- `Professional Match != Intent`;
- `Discovery != Intent`;
- `Intent != Permission`;
- `Permission != Trust`;
- `Opportunity Fit != Professional Match`;
- private favorite != sharing consent;
- click/view/redirect != sharing consent;
- application to Company A != cross-company profile/CV grant to Company B;
- reference job != ownership of its audience;
- profile/identity access != CV access;
- current authorization must be checked before every sensitive action;
- CPC/billing event data stays separate from the Intent domain;
- Cross-Offer source provenance is internal and is not exposed as competitor intelligence;
- Independent Signal Rule applies before Cross-Offer nominative exposure;
- Source Protection and configurable Source Protection Window/cooling policy must be respected where applicable;
- Contact Governor runs before recruiter invitations;
- current-employer/company exclusions are enforced before exposure/contact;
- no broad recruiter bypass of existing CV ACLs;
- no single opaque score replaces Match, Intent, Trust and Permission;
- no generalized cross-site surveillance as an implicit implementation shortcut;
- no fake/placeholder job whose primary purpose is candidate/Intent harvesting;
- Talent Stream opt-in must never be required to apply for a job;
- candidate refusal of Talent Stream must not penalize unrelated applications/matching;
- no recruiter API/UI exposing precise individual competitor-browsing/save/click history.

## Architecture style

Keep the backend as a **Modular Monolith FastAPI + MongoDB** unless a dedicated approved architecture issue explicitly changes that decision.

Do not introduce microservices, Kafka, a graph database or a global repository refactor merely because the conceptual model uses domains/graphs/events.

Prefer:

- incremental domain boundaries;
- thin route adapters over time;
- idempotent commands;
- explicit versioning;
- controlled migrations/indexes;
- authoritative source data + reconstructible projections;
- Mongo transaction + outbox + idempotent worker where asynchronous processing is needed.

## Cross-Offer special rule

Internal Cross-Offer retrieval is not recruiter exposure.

An agent may not make internal Cross-Offer candidates visible/contactable until the issue explicitly authorizes the safe exposure lot and all applicable Gate GC protections exist, including:

- origin neutralization;
- Independent Signal Rule;
- Source Protection / Window;
- candidate current permission/exclusions;
- recruiter/organization/mandate trust;
- Contact Governor;
- Opportunity Fit/privacy safeguards.

## Workflow

Expected workflow for Talent Stream lots:

1. GitHub issue defines the scope and dependencies.
2. OpenCode/agent performs PLAN read-only.
3. ChatGPT/architecture review validates or corrects PLAN.
4. BUILD is explicitly requested.
5. Agent implements only approved issue scope.
6. Relevant tests/typecheck/build are run.
7. PR/diff is reviewed before merge.
8. Gate-critical behavior is not released while its required tests/invariants fail.

In PLAN mode: do not modify repository files, branches or commits.

In BUILD mode: do not expand scope to “complete” future phases or refactor unrelated existing code.
