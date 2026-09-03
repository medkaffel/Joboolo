# Joboolo Agent Instructions

## Talent Stream mandatory context

Talent Stream is the signature Joboolo service.

For **every GitHub issue or pull request related to Talent Stream or any Phase A-E lot**, an implementation/review agent MUST read, before planning or modifying code:

1. `TALENT_STREAM_SPEC.md` — canonical product specification.
2. `ARCHITECTURE.md` — canonical architecture, domains, dependencies, phases and Gates.
3. `BUSINESS_RULES.md` — binding non-negotiable business, trust, privacy and reputation rules.

If one of these files is missing or unreadable, report the blocker rather than inventing an alternative specification.

## Scope rule

The canonical documents describe the **complete target system**. They are context, not authorization to implement the roadmap.

The **current GitHub issue/PR is always the only authorized implementation scope**.

Do not implement a future phase, adjacent feature, opportunistic refactor or inferred requirement merely because it appears in the canonical documentation.

When canonical documentation and the issue appear inconsistent:

- do not silently choose one;
- identify the conflict in PLAN/review;
- preserve safety/privacy invariants;
- request/await an explicit architecture decision before implementing the conflicting behavior.

## Required engineering principles

For Talent Stream work, preserve at minimum:

- `Professional Match != Intent`;
- `Intent != Permission`;
- `Permission != Trust`;
- `Opportunity Fit != Professional Match`;
- private favorite != sharing consent;
- click != sharing consent;
- reference job != ownership of its audience;
- profile access != CV access;
- current authorization must be checked before sensitive actions;
- CPC/billing event data stays separate from the Intent domain;
- Cross-Offer source provenance is not exposed as competitor intelligence;
- Contact Governor runs before recruiter invitations;
- current-employer/company exclusions are enforced before exposure/contact;
- no broad recruiter bypass of existing CV ACLs;
- no single opaque score replaces Match, Intent, Trust and Permission;
- no generalized cross-site surveillance as an implicit implementation shortcut.

## Architecture style

Keep the backend as a **Modular Monolith FastAPI + MongoDB** unless a dedicated approved architecture issue explicitly changes that decision.

Do not introduce microservices, Kafka or a global repository refactor as an incidental implementation detail.

Prefer incremental domain boundaries, idempotent commands, explicit versioning, controlled migrations/indexes and reconstructible projections.

## Workflow

Expected workflow for Talent Stream lots:

1. GitHub issue defines the scope.
2. OpenCode/agent performs PLAN read-only.
3. ChatGPT/architecture review validates or corrects the plan.
4. BUILD is explicitly requested.
5. Agent implements only the approved issue scope.
6. Relevant tests/typecheck/build are run.
7. PR/diff is reviewed before merge.

In PLAN mode: do not modify repository files, branches or commits.

In BUILD mode: do not expand scope to “complete” future phases.
