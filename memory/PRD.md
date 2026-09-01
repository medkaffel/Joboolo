# Joboolo — PRD & Changelog

## CDC Joboolo 2026 — analyse & lots
Source: CDC-Joboolo-2026.pdf. Plan en 4 lots. Géo simplifiée (pas de multi-domaine), AdSense en placeholders, multilingue FR/EN reporté (Lot 4).

### Lot 1 + Lot 2 — DONE (2026-06) — testés 100% (iteration_2.json)
- Lot 1: back-to-top (BackToTop.jsx), section « 3 bonnes raisons » (WhyJoboolo.jsx, home avant recherche), message rouge si champs vides (SearchSection search-warning), blocs inscription alerte haut+milieu (AlertInlineBlock, milieu si >10 offres) + toujours visible même 0 résultat, footer international (Footer.jsx, 13 pays avec drapeaux — liens '#' à brancher/gérer via admin plus tard).
- Lot 2: historique recherches localStorage (utils/searchHistory.js, RecentSearches.jsx, max 10, transformer en alerte via dialog + supprimer + tout effacer, masqué si vide) ; auto-complétion mots-clés+lieu+entreprise (AutocompleteInput.jsx → GET /api/jobs/suggest?q=&field=title|location|company) ; rayon de distance (SearchSection search-radius-select — UI seulement) ; filtres (type contrat, date posted_within, tri) + recherche avancée dépliable (entreprise, salaire, télétravail) + pagination numérotée (JobList.jsx) ; colonne droite (ResultsSidebar.jsx : placeholders AdSense adsense-placeholder-top/bottom, mini-form alerte, recherches similaires, recherche à proximité) ; slider alerte (AlertSlider.jsx, 1×/session) ; scroll auto vers résultats.
- Backend: GET /api/jobs/suggest (autocomplete), GET /api/jobs params posted_within/company/sort, POST /api/alerts/subscribe (public — crée compte candidat léger + alerte, stocke origin/search_mode/result_count).
- Note: « rayon » passe le param mais pas de vrai calcul de distance (nécessite géocodage lat/lng — Lot 4).

### Lot 3 — DONE (2026-06) — testés 100% (16/16 backend, frontend OK — iteration_3.json)
- Formulaire campagnes partenaire (PartnerCampaigns.jsx dans /partenaire) : nom, méthode facturation clic/pack, CPC, CPC max, dates début/fin, limite budget (si au clic) ; validité pack = paramètre admin (30j) pour per_posting. CRUD : GET/POST/PUT/DELETE /api/partner/campaigns. Pause/activer + supprimer.
- **Flux XML + CPC/pack PAR CAMPAGNE (2026-06)** : chaque campagne porte son propre `xml_feed_url`, `cpc`/`cpc_max`/`budget_limit` (per_click) ou `pack_price` (per_posting). Import par campagne : POST /api/partner/campaigns/{id}/import (coller XML ou récupérer depuis l'URL de la campagne) → jobs taggés `campaign_id` + CPC de la campagne. Clics attribués à la campagne (campaigns.clicks/spent), auto-pause + désactivation des offres quand spent >= budget_limit. UI : bouton import + dialog par ligne de campagne. L'ancienne carte d'import globale (profil) a été retirée.
- **Format d'import standard Joboolo** (partner_feed.py `_parse_ads`) : `<joboolo><ad><id/><title/><content/><url/><contract/><postcode/><city/><date/></ad></joboolo>` (CDATA géré par ElementTree). Mapping : id→external_ref, title→title, content→description, url→external_url, contract→job_type (normalisé via _CONTRACT_MAP), postcode+city→location "City (postcode)". Ancien format `<jobs><job>` toujours supporté (fallback).
- Paramètres généraux admin (SettingsTab, onglet Paramètres) : pack_validity_days (30) + low_balance_threshold (10 €). GET/PUT /api/admin/settings (singleton db.settings _id=global).
- Alerte « solde bas » : email + bouton recharge quand balance < seuil, one-shot (flag low_balance_notified), reset à la recharge. Hook dans jobs.record_partner_click → _check_low_balance ; email_service.build_low_balance_email.
- Campagnes flux XML enrichies (FeedsTab, onglet Flux XML) : source_name, url, cpc/pack_price ; affecter à partenaire existant OU créer partenaire SANS login (hashed_password=None, profile.no_login=True). GET/POST/DELETE /api/admin/xml-feeds + POST /import (réutilise partner_feed.import_feed). db.xml_feeds.
- Onglet alertes admin (AlertsTab) : liste + recherche + filtre actif/inactif, toggle, supprimer (corbeille). GET /api/admin/alerts, PUT /toggle, DELETE. Tracking clics alertes : GET /api/alerts/track/{id}?redirect= (302, remplit last_viewed_at sur alerte + last_alert_viewed_at sur user, +click_count) ; build_alert_html enveloppe les liens via le tracker + liens modifier/désactiver/désinscrire.
- Tableau de bord performance partenaire (PartnerPerformance.jsx dans /partenaire) : clics, coût total, CPC moyen, CTR + graphique clics/jour (7/14/30 j) + top offres. GET /api/partner/performance?days= (agrège db.click_events, journalisés à chaque clic dans jobs.record_partner_click avec cost/stopped/ts). Testé (5 clics, 2.00 €, CPC 0.40).

### Lot 4 — En cours (Infra avancée)
- Rafraîchissement auto des flux XML par campagne — DONE (2026-06) : scheduler.refresh_campaign_feeds (job APScheduler interval 1h) réimporte chaque campagne active avec xml_feed_url quand due selon settings.feed_refresh_hours (configurable admin, défaut 24h, SettingsTab settings-feed-refresh). Import journalisé dans db.import_logs via partner_feed.import_campaign_feed (manuel + auto). Historique partenaire 30 j : GET /api/partner/imports (début/fin/new_ads/trigger/status) affiché dans PartnerCampaigns (data-testid import-history / import-log-*).
- **Demande 9 points (2026-06) — DONE, testée (iteration_4.json, backend 13/13, frontend 100%)** :
  1. BUG Hiérarchie géo : geo_service.resolve_location_codes (geo.api.gouv.fr, correspondance EXACTE nom département/région -> codes). jobs.search_jobs : si codes résolus -> filtre UNIQUEMENT par regex code postal (postcode_regex, « Ville (42160) ») ; sinon texte libre. « Loire » -> 42xxx only, « Rhône » -> 69xxx, régions -> tous leurs départements.
  2. Header « Partenaire » (nav-partenaire) ouvre l'AuthModal (ou /partenaire si déjà partenaire connecté).
  3. Type de compte « Partenaire - Jobboard / Diffusion permanente » à l'inscription + champ société. POST /api/auth/register-partner : compte is_active=False (EN ATTENTE), pas d'auto-login. Login inactif -> 403. Email admin (ADMIN_EMAIL, défaut admin@joboolo.fr) via build_new_partner_email. Validation admin = toggle is_active (back-office). authenticate_user rendu insensible à la casse.
  4. Autocomplétion lieu recruteur : PostJob location = AutocompleteInput field=location.
  5. Suppression campagne en cascade : delete_campaign fait db.jobs.delete_many({campaign_id}).
  6. URL flux XML OBLIGATOIRE : create_campaign 400 sans xml_feed_url ; label « * » + validation front.
  7. Logos partenaire/campagne : stockage objet (POST /partner/logo, /partner/campaigns/{id}/logo), servis publiquement sans auth (GET /api/files/public/{path}). JobResponse.logo_url (campagne > profil). Affiché sur JobCard face au bouton Postuler (job-card-logo-<id>).
  8. Icônes campagne : loupe (campaign-view-jobs-<id> -> GET /partner/campaigns/{id}/jobs dans campaign-jobs-dialog) + crayon édition (campaign-edit-<id>, dialog pré-rempli, PUT).

### Lot 4 — À FAIRE (reste)
- **Géo & tracking & impressions (2026-06) — DONE, testé (iteration_5.json, backend 9/9, frontend 4/4)** :
  - Géo-détection IP : GET /api/geo/detect (ip-api.com, X-Forwarded-For). Home pré-remplit « Où » avec la ville détectée + cookie joboolo_country (une fois). SearchSection sync initialQuery.location.
  - Vrai rayon de distance (France) : geo_service.geocode_place (geo.api.gouv.fr communes, [lng,lat]). Offres stockent loc GeoJSON Point (backfill scripts/geocode_jobs.py : 2222/2442 ; géocodage aussi à l'import partner_feed). Index 2dsphere (server startup). jobs.search_jobs : param radius -> filtre $geoWithin/$centerSphere (rayon/6378.1). Vérifié : Lyon 5km<100km.
  - Tracking provenance à l'inscription : utils/attribution.js (first-touch : source/referrer/utm/landing, localStorage), fusionné dans /auth/register + /auth/register-partner. Stocké sur user, visible back-office (colonne Provenance, UsersTab, _user_out).
  - Amélioration CTR : vraies impressions. POST /api/jobs/impressions (batch, offres partenaires uniquement) -> db.impression_events + campaigns.impressions + partner_profiles.total_impressions. JobList logue à l'affichage (dédup sessionStorage joboolo_impr). /partner/performance : totals.impressions = count impression_events sur la période, ctr = clics/impressions.
- RESTE (reporté par l'utilisateur) : Multilingue FR/EN (i18n complet). AdSense réel (ca-pub-…, nécessite ID éditeur + slots du client).

### Footer international + onglet admin « Pays » (2026-06) — DONE
- Vraies icônes de drapeaux (flagcdn PNG, cross-platform) au lieu des emojis. Footer charge `GET /api/footer-countries` (repli défaut). Liens cliquables vers sous-domaines `https://{code}.joboolo.com` (nouvel onglet + icône ExternalLink). Collection `footer_countries` (seed idempotent 13 pays + migration `#`->sous-domaines). CRUD admin `/api/admin/footer-countries` (onglet « Pays » : ajout/edit/toggle/suppression, génération auto du sous-domaine si URL vide).

### Emails import auto + validation partenaire (2026-06) — DONE, testé
- Email récapitulatif au partenaire après chaque import AUTOMATIQUE (scheduler.refresh_campaign_feeds) : `build_auto_import_email` (X nouvelles / Y mises à jour), envoyé si activité > 0. Réglage `settings.auto_import_email` (défaut True).
- Onglet admin « En attente » : `GET /api/admin/partners/pending` (partenaires is_active=False) + bouton Valider `POST /api/admin/partners/{id}/validate` -> active user+profil (is_active True, pending_validation False) ET envoie `build_partner_welcome_email`. Vérifié curl : register->403->pending list->validate->200->retiré de la liste.

### Lot 4 — reporté
- Géo-détection pays/ville + pré-remplissage « Où » + cookie pays (simplifié).
- Tracking provenance à l'inscription (google/direct/referer, dernière page).
- Multilingue FR/EN. AdSense réel (ca-pub-…). Vrai rayon de distance (géocodage).


## Original Problem Statement
Build a responsive job board like indeed.fr, rebranded "Joboolo" (French UI). Full functional backend, social login, country-based localized greeting, seeded jobs, working candidate profile navigation.

### Candidate profile — photo, social links, documents (2026-07)
- Alert form auto-fills the candidate's email: `Home.jsx` initialises `alertEmail` from `user.email` when authenticated candidate clicks "Créer une alerte" on a recent search; same behaviour for `AlertSlider`.
- Profile photo: **new** `POST /api/files/upload-profile-photo` (JPG/PNG/WEBP/GIF, ≤3 Mo) writes to object storage, marks the file as public, saves `profile_photo_url` on the user doc. UI: circular avatar with camera badge on the Informations personnelles card.
- Social links: `UserUpdate`/`UserResponse` extended with `social_link_1/2/3` (free-text, optional). UI: label «Mes sites et liens sociaux : LinkedIn, GitHub, Portfolio, etc..» + 3 inputs; when read-only, non-empty links render as clickable brand-coloured chips.
- Candidate documents: **new** collection `candidate_documents` + 4 endpoints under `/api/files/candidate-documents` (list / upload / update title-description / soft-delete). Enforced max 3 per category (`cv` | `cover_letter`); PDF/DOC/DOCX ≤10 Mo. UI: reusable `CandidateDocuments` component with 2 cards (CV / Lettres de motivation), each showing count/3, upload dialog (file + title + description), edit dialog (title + description), delete confirmation, and inline open (`fileService.openFile`).

### Admin dashboard — full CRUD polish (2026-07)
- Every list (Candidats, Employeurs, Partenaires, Partenaires en attente, Offres, Flux XML, Alerte pays) now shows a shared `AdminListHeader` with the live count, an optional inline search block, and a primary "Nouveau…" button.
- Each row exposes a **Pencil edit icon** wired to a dedicated edit dialog:
  - Candidats/Employeurs → `PUT /admin/users/{id}` (first_name, last_name, phone, location, bio)
  - Partenaires → existing `PUT /admin/partners/{id}/config` reused (billing_mode, CPC, prix, XML URL, packs, crédits)
  - En attente → `PUT /admin/users/{id}` (contact name)
  - Offres → **new** `PUT /admin/jobs/{id}` (title, location, job_type, description, salary min/max)
  - Flux XML → **new** `PUT /admin/xml-feeds/{id}` (source_name, url, billing_mode, cpc, pack_price) — also syncs the parent partner profile
  - Alerte pays → existing `PUT /admin/footer-countries/{id}`
- **First column of every row is now a clickable link** (`DetailLinkCell`) that opens a generic `DetailDialog` listing all relevant fields of the record (localised labels, boolean → Oui/Non, ISO date → local FR datetime, nested keys supported).
- Search fields added on Partenaires and Partenaires en attente (query joins users email/first_name/last_name + partner_profiles.company_name). Backend `/admin/partners` and `/admin/partners/pending` now both accept `search`.
- Login selector: option "Administrateur" retirée du sélecteur public. Logo (`Header.jsx`) redimensionné pour matcher la H1 de la page d'accueil (`text-2xl sm:text-2xl lg:text-3xl`).

### Strict role-based login (2026-07)
- Backend `POST /api/auth/login` — LoginRequest gained optional `expected_user_type` (candidate | employer | partner | admin). When provided, backend enforces exact match against the account's real user_type; mismatch → HTTP 403 with FR message «Ce compte est de type « X » et ne peut pas se connecter en tant que « Y »». Omitting the field keeps full backward compatibility (used by scripts / Google session).
- Frontend `AuthModal` login tab gained a "Je me connecte en tant que" selector (Candidat / Recruteur / Partenaire / Administrateur, default Candidat) whose value is forwarded to the API. Admin credentials therefore cannot be used through the Candidat/Recruteur/Partenaire flows, and vice versa.

### Home + Header refresh (2026-07)
- SearchSection: removed "Créer une alerte email pour cette recherche" link under the search bar; H1 "Trouvez le poste qui vous correspond" downsized (text-2xl sm:text-2xl lg:text-3xl, ~half the previous size); Recherches populaires only shown when the visitor has NO local history.
- Home.jsx: hides "3 bonnes raisons" (WhyJoboolo) AND "Recherches populaires" for returning visitors (localStorage joboolo_search_history has ≥1 entry). Also auto-runs a search when arriving from /saved-searches with ?q=&l=.
- Header.jsx: logo enlarged (text-4xl sm:text-5xl, h-20 header). For connected candidates: top nav shows ONLY "Rechercher des emplois" (Recruteur/Partenaire/Affiliation hidden). Dropdown gains two new entries: "Mes alertes" (after "Mes candidatures", data-testid menu-alerts → /my-alerts) and "Recherches sauvegardées" (after "Emplois sauvegardés", data-testid menu-saved-searches → /saved-searches).
- New pages: /my-alerts (MyAlerts.jsx, renders AlertsManager, candidate-only) and /saved-searches (SavedSearches.jsx, local history list + delete/clear + create alert with frequency dialog, candidate-only). Both auth-guarded (redirect to /).

## Stack
- Frontend: React + Tailwind + Shadcn UI, react-router-dom, Context API, Axios.
- Backend: FastAPI + MongoDB (Motor), JWT auth, APScheduler (daily alert scheduler), Resend (email).
- All backend routes prefixed with /api. Frontend uses REACT_APP_BACKEND_URL.

## Personas
- Candidate: search jobs, apply, save jobs, edit profile, create email alerts.
- Employer: create company, post/manage jobs.

## Implemented (2026-06)
- P0 FIX: white-screen crash on login (App.js referenced unimported CandidateProfile; missing GraduationCap icon).
- P0 FIX: mixed-content 307 redirect (routes defined with "/" under prefix downgraded HTTPS→HTTP). Fixed by using "" route paths + FastAPI(redirect_slashes=False) + frontend calls without trailing slash.
- P0 FIX: seed_data.py was wiping users/companies/jobs on every restart (delete_many). Now IDEMPOTENT via upsert ($setOnInsert). Registered users, posted jobs and companies persist across restarts.
- (a) Candidate profile edit + save → PUT /api/auth/me. Wired in CandidateProfile.jsx via AuthContext.updateProfile.
- (b) Candidate pages: "Mes candidatures" (/my-applications), "Emplois sauvegardés" (/saved-jobs).
- (c) Employer pages: "Publier une offre" (/post-job, inline company creation), "Mes offres" (/my-jobs, list + delete), EmployerDashboard (/employer-dashboard).
- (d) REAL Google login via Emergent-managed Google Auth. Backend POST /api/auth/google/session exchanges session_id → issues app JWT (find/create user, default candidate). Frontend AuthCallback handles #session_id. Facebook/X/LinkedIn removed per user request.
- NEW: Save-search → Email alerts. Backend alerts CRUD (POST/GET/PUT/DELETE /api/alerts) + POST /api/alerts/{id}/send-now. Candidate creates alert from home ("Créer une alerte"), manages frequency (instant/daily/weekly/never) + active toggle + send-now + delete from profile (AlertsManager). Daily APScheduler (08:00 UTC) emails new matching jobs via Resend.
- Footer rebranded Indeed → Joboolo (© 2026).

## Testing status
- Backend: 13/13 pytest pass (auth, profile, alerts CRUD+send-now, google 401, employer company/job).
- Frontend (playwright): login no crash, all pages render, no mixed-content, no JS errors. Candidate alert creation + employer job posting verified end-to-end.

## MOCKED / PENDING
- (2026-07) Resend RE-ACTIVATED after GitHub re-import: RESEND_API_KEY reset in /app/backend/.env, SENDER_EMAIL=noreply@joboolo.fr. Fixed server.py to run load_dotenv BEFORE route imports (email_service reads env at import time). Verified: real delivery via Resend API returns message ID.

## Backlog / Next
- P2: Public shareable Job Detail page — DONE (2026): /jobs/:jobId, dynamic SEO + JSON-LD JobPosting, share buttons, apply/save.
- P2: Apply modal (cover letter + CV upload) — DONE (2026): ApplyModal.jsx used from JobCard & JobDetail. CV (PDF/DOC/DOCX, ≤10MB) uploaded to object storage via POST /api/files/upload-cv (asyncio.to_thread, non-blocking). Download via GET /api/files/{path} (auth via header or ?auth= token). Application stores cv_url = storage_path.
- P2: Employer applications-per-job view — DONE (2026): /my-jobs/:jobId/applications (ApplicationsForJob.jsx), lists applicants with cover letter, CV download, and status update (pending/reviewed/accepted/rejected). MyJobs has a "Candidatures (N)" button per job. Status endpoint now takes a JSON body (StatusUpdate).
- P2 (DEFERRED by user): SSR/prerender for social OG previews. SPA (CRA) can't SSR here without Next.js migration; client SEO + JSON-LD works for Google.
- P2: "instant" alert frequency currently approximated by daily scheduler.

## Design system (2026 redesign — Indeed/Talent.com inspired)
- Fonts: Outfit (headings) + DM Sans (body) via Google Fonts in index.css.
- Brand color #0055FF (hover #0044CC), tailwind `brand` + shadcn HSL vars updated (primary 220 100% 50%, radius 0.75rem). Backgrounds slate-50/white, text slate-900/500.
- Hero: soft radial accents + floating pill search bar (Quoi/Où) with divider, popular-search chips, fade-up entrance animations.
- Header: sticky glassmorphism (backdrop-blur), lucide icons in account dropdown, pill CTA.
- JobCard: rounded-2xl, company initial avatar, pill uppercase badges, hover lift + border tint, brand "Postuler".
- JobDetail & Footer restyled to match (brand accents, slate-900 footer with brand logo).
- design_guidelines.json holds the full blueprint.
- Internal pages (profil, mes candidatures, emplois sauvegardés, publier une offre, mes offres, dashboard employeur, candidatures par offre, AlertsManager) restyled to the charter (font-heading titles, brand accents, slate palette).
- Header nav links updated to: Rechercher des emplois / Recruteur (/post-job) / Partenaire / Affiliation.

## Partner & Admin (2026 — Phase 1 done)
- Roles: added `partner` and `admin` to UserType. require_admin dependency in auth.py. Default admin seeded at startup (admin@joboolo.fr / AdminJoboolo2026!).
- Admin back-office at /adminos (AdminDashboard.jsx): stats, tabs Candidats/Employeurs/Partenaires/Offres. Manage users (toggle active / delete / edit), search jobs + stop/resume diffusion + delete. Create partners + configure billing.
- Partner billing config (partner_profiles collection): billing_mode per_click|per_posting, default_cpc (€), posting_price (€/annonce), packs (add 5/10/20/50/100/200 → postings_remaining), balance (€ prepaid), xml_feed_url, total_clicks, total_spent.
- Backend: routes/admin.py (require_admin). adminService.js frontend.
- CPC logic (to implement Phase 2): CPC from XML per-offer if present, else partner default_cpc.

## Partner Phase 2 — DONE (2026-06)
- XML feed ingestion: standard format (title, company, location, description, url, cpc, job_type, reference). POST /api/admin/partners/{id}/import-xml (paste XML or fetch from configured xml_feed_url). Admin UI: import dialog in AdminDashboard PartnersTab (data-testid admin-import-xml-dialog / import-xml-textarea / import-xml-submit). Verified end-to-end via UI ("Import terminé — N importée(s)").
- Click tracking on partner jobs: JobCard.jsx + JobDetail.jsx call jobService.recordClick(job.id) → POST /api/jobs/{id}/click when is_partner + external_url, then open external_url. Backend decrements balance (per_click) / postings_remaining (per_posting), increments total_clicks/total_spent.
- NOTE: screenshot_tool page object is ASYNC — every page.* call MUST be awaited or it is silently skipped (caused false "login broken" symptoms during debugging).

## PENDING — Stripe (NOT yet built)
- (superseded — see Stripe section below)

## Stripe Partner Top-up — DONE (2026-06)
- Flow A claimable sandbox (country FR). Keys in backend/.env (STRIPE_SECRET_KEY/PUBLISHABLE/ACCOUNT_ID/WEBHOOK_SECRET/MODE). onboarding_url from provisioning (claim to go live).
- Tax mode: DIY (payment processing only, no tax at funding). Rationale: prepaid ad-wallet top-up — tax applies when balance is consumed via CPC, not at funding. Other modes (Stripe-calculates-only / Stripe-manages-all) available on request.
- Backend routes/payments.py: server-side PACKS (50/100/200/500 €) + free amount (10–5000 €, validated server-side). POST /api/payments/create-topup (partner self OR admin with partner_id) → Stripe checkout w/ price_data EUR. GET /api/payments/status/{session_id} (unauth, polls + idempotent credit). POST /api/stripe/webhook (idempotent). GET /api/partner/me + /api/partner/transactions. _ensure_stripe() reads key at request time (server.py load_dotenv runs after import).
- On paid: partner_profiles.balance += amount, guarded by credited flag (credited once only). Verified E2E: real Stripe checkout w/ 4242 card → balance credited 50 €.
- Frontend: /partenaire (PartnerDashboard.jsx — login gate + stats + recharge + txn history), RechargeDialog.jsx (shared, packs + custom), /payment/success (PaymentSuccess.jsx, polls status), /payment/cancel. Admin: "Recharger" button per partner row in AdminDashboard PartnersTab opens same RechargeDialog with partner_id. Header "Partenaire" nav → /partenaire.
- Test card 4242 4242 4242 4242, any future expiry/CVC. US card triggers currency-choice + phone/ZIP; EUR card pays €50 directly.

## Stripe follow-ups — DONE (2026-06)
- Receipt email after successful recharge: email_service.build_topup_receipt_email + send via Resend, best-effort inside payments._credit_if_paid (_send_receipt). Handles both balance top-up and posting-pack receipts. (Wired; delivery not re-verified this session — Resend infra already proven for alerts.)
- Partner self-service XML import: partner_feed.py (shared import_feed used by admin AND partner). POST /api/partner/import-xml + PUT /api/partner/feed-url (require_partner). /partner/me returns xml_feed_url. PartnerDashboard has a "flux XML" card (feed URL save + paste XML + import). Verified: imported 1.
- per_posting Stripe posting packs: POST /api/payments/create-topup accepts {postings:N} (N in [5,10,20,50,100,200]); amount = N * posting_price; kind=posting_pack; on paid → $inc postings_remaining. /payments/packs returns posting_packs. RechargeDialog shows posting packs (with € price) when billingMode=per_posting; balance packs+custom otherwise. Verified backend + UI.

## Object storage / integrations
- CV files: Emergent object storage (storage.py, EMERGENT_LLM_KEY). Bucket path: joboolo/uploads/{user_id}/{uuid}.{ext}. File metadata in db.files.
- Status-change email (2026): when an employer sets an application to reviewed/accepted/rejected, the candidate is auto-emailed via Resend (email_service.build_status_email, sent from PUT /api/applications/{id}/status). Best-effort, non-blocking.
- Apply emails (2026): on POST /api/applications, candidate gets a confirmation email (build_application_confirmation_email) and the job's employer gets a new-application notification (build_new_application_email). Best-effort, non-blocking.


## Page Recruteur Premium — DONE (2026-06) — testée (iteration_6.json, backend 15/15, frontend 100%)
Nouvelle vitrine marketing orientée conversion pour recruteurs, route **/recruteur** (le lien Header « Recruteur » pointe désormais ici ; bouton « Publier une offre » → checkout Stripe / AuthModal).
- Frontend: `pages/RecruiterLanding.jsx` (Hero, Stats, Comment ça marche 3 étapes, section IMPORT automatique dark band, Tarifs 2 paliers, section Candidats ciblés, Témoignages, FAQ, Formulaire de devis #devis, CTA final), `components/RecruiterCheckoutDialog.jsx` (choix pack + paiement Stripe), `services/recruiterService.js`.
- Paliers tarifaires: **Au clic (CPC)** (sur mesure → devis) + **Offre Premium** (achat Stripe à l'unité). Le palier « Candidats Ciblés » a été retiré (demande user). Prix Premium affiché avec préfixe « À partir de ».
- **Prix Premium paramétrable** via admin onglet Paramètres (`settings-recruiter-price`) → `db.settings _id=global recruiter_premium_price` (défaut 299 €). Les packs sont calculés depuis ce prix unitaire (premium_1 = unit, premium_3 = round(unit*3*0.89), premium_5 = round(unit*5*0.80)). Endpoints admin.py: DEFAULT_SETTINGS + SettingsUpdate + PUT /api/admin/settings.
- Backend `routes/recruiter.py`: GET /api/recruiter/packs (retourne unit_price + packs), POST /api/recruiter/checkout (require_employer → session Stripe, kind=recruiter_pack, crédite user.premium_credits à paiement via payments._credit_if_paid + reçu email _send_recruiter_receipt), POST /api/recruiter/quote (lead public → db.recruiter_leads + email admin), GET /api/recruiter/quotes (admin).
- PaymentSuccess.jsx: si kind=recruiter_pack → bouton « Publier mon offre » (/post-job) et affiche offres créditées. /payments/status renvoie kind+postings.
- **STRIPE SANDBOX PROVISIONNÉ (2026-06)**: la clé de l'env était un placeholder (ancienne clé Stripe de test codée en dur, invalide — cassait aussi le paiement partenaire). Un sandbox Stripe « claimable » a été provisionné (POST integrations.emergentagent.com/stripe/sandboxes) et écrit dans /app/backend/.env: STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_ACCOUNT_ID, STRIPE_WEBHOOK_SECRET, STRIPE_MODE=test. ⚠️ Sandbox NON RÉCLAMÉ (badge « Unclaimed sandbox » + devise SGD affichée à côté de l'EUR sur checkout.stripe.com) — À RÉCLAMER avant production via l'onboarding_url.
- Note copie: FAQ/témoignage/CTA feature mentionnent encore « candidats ciblés sur-mesure » (mappé désormais vers le formulaire de devis) — conservé volontairement (section Candidats ciblés maintenue).
