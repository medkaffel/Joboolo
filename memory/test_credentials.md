# Test Accounts — Joboolo

This file intentionally contains **no passwords, API keys, tokens, personal OAuth identities, or other secrets**.

The repository is public. Test credentials must be supplied outside Git (for example through local/CI environment variables or an approved secret store). Never commit real credentials here, even for test accounts.

## Shared test-account roles

The historical test suite uses the following account roles:

- candidate
- employer / recruiter
- per-click partner
- per-posting partner
- admin
- optional seeded development users

When an E2E environment requires fixed shared accounts, provide both the account identifier and password explicitly through the environment used by that isolated environment. Test code must not fall back to a repository-known password.

Recommended variable families:

- `E2E_CANDIDATE_EMAIL` / `E2E_CANDIDATE_PASSWORD`
- `E2E_EMPLOYER_EMAIL` / `E2E_EMPLOYER_PASSWORD`
- `E2E_ADMIN_EMAIL` / `E2E_ADMIN_PASSWORD`
- `E2E_PARTNER_EMAIL` / `E2E_PARTNER_PASSWORD`
- `E2E_POSTING_PARTNER_EMAIL` / `E2E_POSTING_PARTNER_PASSWORD`

## Partner self-registration flow

New partners register through the Partner signup flow. The backend creates a pending partner account that must be activated by an authorized admin before normal login is allowed. Admin notification email is best-effort and depends on the environment's mail configuration.

## OAuth

Google OAuth may be enabled in configured environments. OAuth-only test identities must be environment-owned fixtures; do not document a real person's account in the repository. Password login for an OAuth-only account should remain rejected.

## Seed / development data

Development seeds are explicit operations, not startup behavior. If an isolated development or E2E environment needs seeded users, their credentials must be supplied/configured for that environment and must not be reused for production or public services.

## External services

Email, Stripe, OAuth and object-storage integration tests must use dedicated test/sandbox configuration. Do not place service credentials or statements about live unrestricted credentials in repository documentation.

## Rotation requirement after an exposure

If a credential has ever been committed to Git, treat it as exposed. Repository sanitation does **not** invalidate an already exposed credential. Rotate or disable reachable accounts/secrets in the owning environment first, then update isolated test fixtures as needed.

Git history rewriting is a separate operational decision and is not required merely to remove a credential from the current branch once the exposed credential has been invalidated.
