# Test Credentials — Joboolo

## Partner account (Stripe top-up test — /partenaire)
- Email: partenaire@joboolo.fr
- Password: Partner2026!
- Company: Partenaire Demo (per_click, CPC 0.35 €). Balance credited via Stripe test payment.

## Partner account per_posting (posting-pack Stripe test — /partenaire)
- Email: posting@joboolo.fr
- Password: Post2026!
- Company: PostCorp (per_posting, 3.00 €/annonce). Buys posting packs via Stripe.

## Admin account (back-office at /adminos)
- Email: admin@joboolo.fr
- Password: AdminJoboolo2026!

## Partner self-registration (pending validation flow)
- New partners register via header "Partenaire" -> AuthModal -> Inscription -> account type "Partenaire".
- Backend POST /api/auth/register-partner creates user with is_active=False (pending). Login returns 403 until an admin activates the account (Admin > Partenaires > toggle active, or PUT /api/admin/partners/{id}/config is_active=true, or POST /api/admin/users/{id}/toggle).
- Admin notification email sent to ADMIN_EMAIL (default admin@joboolo.fr) on signup (best-effort via Resend).

## Candidate account
- Email: candidate@joboolo.fr
- Password: Test1234

## Employer account (own seed companies? no — freshly registered, no companies yet)
- Email: employer@joboolo.fr
- Password: Test1234

## Seed candidate (persistent, pre-populated profile)
- Email: candidate@test.fr
- Password: password123

## Seed employers (persistent, each OWNS a seed company with jobs — good for testing "Mes offres")
- Email: recruteur@techcorp.fr  (owns TechCorp France, has seed jobs)
- Password: password123
- Other seed employers (all password123): hr@digitalboost.fr, rh@hopital-antoine.fr, recrutement@softsales.fr, contact@expertise-plus.fr, rh@mediacom.fr, jobs@datainsights.fr, recrutement@education.gouv.fr

Notes:
- Auth is JWT-based (email + password). Register: POST /api/auth/register, login: POST /api/auth/login.
- Google login is REAL via Emergent-managed Google Auth (button "Continuer avec Google"). Flow: redirect to auth.emergentagent.com, returns with #session_id, backend exchanges it at POST /api/auth/google/session and issues app JWT. Google-created users default to candidate type.
- Facebook/X/LinkedIn OAuth were removed per user request.
- Seeding is now IDEMPOTENT (upsert) — registered users, posted jobs and companies persist across backend restarts.
- Email alerts (Resend) are LIVE and unrestricted: RESEND_API_KEY set in /app/backend/.env, SENDER_EMAIL=noreply@joboolo.fr (domain joboolo.fr verified on Resend). Delivery works to any recipient.
- Daily scheduler runs at 08:00 UTC (APScheduler) for active alerts; on-demand send via POST /api/alerts/{id}/send-now.
- Google OAuth user example (no password): medkaffel@gmail.com (oauth_provider=google). Password login for OAuth-only accounts correctly returns 401 (not 500).
