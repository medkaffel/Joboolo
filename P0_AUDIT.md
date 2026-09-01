# P0_AUDIT.md — Audit des divergences P0 entre le code applicatif et les règles fondatrices

**Statut :** document d'audit en lecture seule — aucune modification applicative associée.
**Date de l'audit :** 2026-09-01
**Base :** branche `foundation/p0-audit`.
**Rapport détaillé source :** analyse réalisée contre `AGENTS.md`, `ARCHITECTURE.md`, `BUSINESS_RULES.md` et `TESTING.md`.

Chaque entrée ci-dessous décrit une divergence **P0** constatée dans le code, à corriger dans une itération dédiée.
Aucune de ces entrées n'a été implémentée : le statut initial de chacune est **TODO**.

---

## P0-001 Secrets et configuration production

### État actuel constaté
Des valeurs de repli connues sont codées en dur et utilisées silencieusement lorsque la variable d'environnement n'est pas définie :
- `SECRET_KEY` : `os.environ.get("SECRET_KEY", "your-secret-key-change-this-in-production")` ;
- clé Stripe : `os.environ.get("STRIPE_SECRET_KEY") or ... or "sk_test_emergent"`.

En production, l'absence de configuration critique est donc masquée par un secret public connu, sans erreur explicite.

### Fichiers / fonctions concernés
- `backend/auth.py` : ligne 13 — `SECRET_KEY` (utilisation dans `create_access_token`, `get_current_user`, `_resolve_user` de `files.py`).
- `backend/routes/payments.py` : ligne 16 — `stripe.api_key` ; `_ensure_stripe()`.
- `backend/routes/recruiter.py` : ligne 45 — `_ensure_stripe()`.

### Risque
- Sécurité : un secret JWT public permet de forger les tokens de toutes les sessions si `SECRET_KEY` manque.
- Sécurité/financier : une clé Stripe test publique connue, si utilisée par erreur, rend les opérations de paiement non authentiques et potentiellement inutiles en production.
- Métier : aucune alerte en cas de configuration manquante → déploiement « silencieusement cassé » mais fonctionnel.

### Règle métier ou sécurité violée
- `AGENTS.md` §7 — jamais de secret dans Git/tests/logs ; en production, une configuration critique manquante doit provoquer une erreur explicite ; environnement development/test/production séparés.
- `BUSINESS_RULES.md` `BR-ID-006` [MUST] — aucun mot de passe admin ou secret JWT de production codé en dur.
- `TESTING.md` §2 / `BR-REL-002` [MUST] — pas de vraies clés de paiement ni comptes destructifs en test.

### Comportement cible
- `SECRET_KEY` obligatoire en production : démarrage en erreur explicite si absent (crash fail-fast), aucun fallback connu.
- `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` obligatoires en production ; échec explicite au démarrage ou à la 1ʳᵉ utilisation.
- Aucune valeur secrète de repli dans le code source ; les environnements utilisent des secrets distincts (dev/test/prod).

### Critères d'acceptation
- Le backend refuse de démarrer en environnement de production sans `SECRET_KEY` et `STRIPE_SECRET_KEY`.
- Aucune chaîne `sk_test_emergent`, `your-secret-key-...` ou équivalent présent dans le dépôt.
- En développement, les valeurs de repli éventuelles sont strictement locales et non comitées.

### Tests obligatoires
- Test de démarrage : absence de `SECRET_KEY` → erreur claire ; présence → démarrage OK.
- Test de démarrage : absence de `STRIPE_SECRET_KEY` → erreur claire.
- Test de régression : aucune trace de secret dans les logs applicatifs ordinaires.

### Dépendances avec les autres P0
- **P0-002** : même thème « secrets et comptes de production » ; la purge des fallbacks et la purge des seed/admin doivent être faites de concert.
- **P0-005** : la facturation Stripe (crédit recruteur) repose sur une configuration Stripe fiable — à sécuriser ensemble.

### Statut initial
TODO

---

## P0-002 Seed/admin dangereux en production

### État actuel constaté
À chaque démarrage (`startup` de FastAPI), le code :
- exécute `seed_database()` (comptes, entreprises et offres de démonstration) ;
- crée un compte administrateur `admin@joboolo.fr` avec le mot de passe en dur `AdminJoboolo2026!` si absent ;
- propage ensuite l'index géospatial et démarre scheduler/storage dans le même bloc startup.

Les comptes seed (`seed_data.py`) utilisent tous le mot de passe connu `password123`.

### Fichiers / fonctions concernés
- `backend/server.py` : `startup_db_client` (lignes 74-98) — appel `seed_database()` + création admin dur.
- `backend/seed_data.py` : `seed_database()`, `seed_users()`, `seed_companies()`, `seed_jobs()` — mots de passe `password123`.
- `backend/tests/*` et scripts à la racine : utilisent ces comptes (dépendance de test non isolée).

### Risque
- Sécurité : un compte admin de production avec mot de passe public connu donne un contrôle total du back-office (validation partenaires, recharges `add_balance`, toggles utilisateurs/offres).
- Sécurité : les comptes seed actifs (`is_active=True`) sont des points d'entrée de démonstration exploitables en production.
- Métier : pollution de la base de production par des données de démonstration (offres/entreprises factices visibles publiquement).

### Règle métier ou sécurité violée
- `AGENTS.md` §7 — jamais de secret ni compte seed en production ; `AGENTS.md` §15 item 8 — suppression des secrets/comptes seed de production.
- `ARCHITECTURE.md` §15 — aucun seed automatique ni compte admin hardcodé en production.
- `BUSINESS_RULES.md` `BR-ID-006` [MUST].

### Comportement cible
- Aucune création de compte (admin ou démo) au démarrage de l'application.
- Le `seed_database()` n'est exécutable qu'en environnement de développement, de manière explicite et contrôlée (script dédié, feature flag, variable d'environnement interdit en prod).
- L'administrateur initial est créé via un flux d'amorçage sécurisé (commande idempotente, secret injecté) et jamais depuis une valeur connue du dépôt.

### Critères d'acceptation
- Un démarrage de l'instance (dans tout environnement) ne crée ni admin ni compte seed.
- Il est impossible de se connecter avec `admin@joboolo.fr`/`AdminJoboolo2026!` ou tout compte seed en production.
- L'environnement de production ne comporte aucune offre/entreprise de démonstration seedée automatiquement.

### Tests obligatoires
- Test de démarrage : base vierge → aucun utilisateur créé au `startup`.
- Test négatif : authentification avec les identifiants admin/seed connus → 401.
- Test d'isolation : `seed_database()` appelé explicitement fonctionne en dev ; aucune voie automatique ne le déclenche en production.

### Dépendances avec les autres P0
- **P0-001** : purge conjointe des secrets et des comptes hardcodés.
- **P0-009** : la normalisation email doit s'appliquer avant toute nouvelle gestion des comptes d'origine seed.

### Statut initial
TODO

---

## P0-003 ACL CV et documents privés

### État actuel constaté
Le endpoint de téléchargement `GET /api/files/{path}` vérifie uniquement qu'un utilisateur est **authentifié**, sans vérification de propriétaire ni de relation métier. Le commentaire du code le dit explicitement : « Any authenticated user may download (candidate/employer) ».

Les documents stockés via `/upload-cv` et `/candidate-documents` (CV, lettres de motivation) portent pourtant un `owner_id`.

### Fichiers / fonctions concernés
- `backend/routes/files.py` :
  - `download_file` (lignes 286-312) — ACL inexistante ;
  - `_resolve_user` (lignes 249-264) — authentification sans autorisation de ressource ;
  - `upload_cv` / `upload_candidate_document` — créent les objets concernés.

### Risque
- Sécurité/vie privée : un candidat ou recruteur peut télécharger le CV/lettre d'un autre utilisateur en connaissant ou devinant le `storage_path`.
- Conformité : exposition de données personnelles (RGPD) sans base de finalité vérifiée.
- Métier : confiance rompue dans le produit et les flux de candidature.

### Règle métier ou sécurité violée
- `BUSINESS_RULES.md` `BR-DOC-002` [MUST] (accès confiné au propriétaire), `BR-DOC-003` [P0][MUST] (« le simple fait d'être authentifié comme employeur n'est pas suffisant »).
- `AGENTS.md` §4.2 — « Interdit : donner accès à un fichier uniquement parce que l'utilisateur est authentifié » ; la question à garantir : « cet utilisateur précis a-t-il le droit de consulter cette ressource précise ? ».

### Comportement cible
- Lecture d'un document : propriétaire uniquement, OU recruteur lié par une candidature explicite à une offre qu'il possède (relation métier vérifiée dynamiquement), OU admin selon politique auditable.
- Les métadonnées `owner_id`/relation font partie de l'autorisation : vérification `owner_id == user.id` ou jointure candidature/offre/employer avant restitution du contenu.
- Préférence d'URL signée courte durée ou de téléchargement autorisé côté backend plutôt que JWT long-lived dans l'URL (`BR-DOC-004`).

### Critères d'acceptation
- Un candidat télécharge ses propres documents → 200.
- Un candidat B tente de télécharger le CV du candidat A → 403.
- Un employeur sans candidature reçue → 403.
- Un employeur disposant d'une candidature pour son offre, liée au document → 200.
- Document soft-deleted → 404.

### Tests obligatoires
- Matrice TESTING §9.6 intégrale : propriétaire / tiers candidat / employeur sans relation / employeur relation / document supprimé.
- Test de chemin arbitraire / traversal → refus (400/404) sans fuite d'information.
- Vue du candidat et vue recruteur : aucun `storage_path` sensible exposé par l'API de listage (`list_candidate_documents`).

### Dépendances avec les autres P0
- **P0-010** : sans identifiant métier fiable pour lier les ressources (email/offre), la jointure candidature→document peut échouer — à coordonner avec la normalisation des identités.
- **P0-009** : des identités doublonnées cassent la résolution propriétaire/relation.

### Statut initial
TODO

---

## P0-004 Débit CPC atomique

### État actuel constaté
Le débit d'un clic facturable suit la séquence naïve : `read balance → if balance >= cpc → $inc balance -cpc`. Ce pattern est explicitement interdit par les règles. Deux clics concurrents sur un solde faible peuvent tous deux passer le contrôle de lecture puis débiter → solde négatif, double facturation.

Le clic, le débit balance, la désactivation d'offre, l'incrément campagne (clics/spent) et la pause de campagne sont réalisés en plusieurs écritures indépendantes et non atomiques. Les impressions sont dédupliquées côté client.

### Fichiers / fonctions concernés
- `backend/routes/jobs.py` : `record_partner_click` (lignes 379-434) — contrôle/débit balance et budget ;
- `backend/routes/jobs.py` : `record_impressions` (lignes 444-474) — événements d'impressions ;
- Collections : `partner_profiles`, `click_events`, `campaigns`, `jobs`.

### Risque
- Financier : solde partenaire négatif par race condition ; deux clics facturés au lieu d'un seul sur budget insuffisant.
- Facturation : pas de trace de l'événement (ledger) reliant un débit à un événement/campagne précis.
- Métier : campagne désactivée en différé (après l'incrément), créant une fenêtre de sur-consommation.

### Règle métier ou sécurité violée
- `BUSINESS_RULES.md` `BR-CPC-002` [P0][MUST] — contrôle solde/budget et débit atomiques ; `BR-PART-003` [MUST] — solde cohérent sous concurrence ; `BR-CPC-003` [TARGET] — idempotence ; `BR-CPC-005` — audit.
- `AGENTS.md` §4.1 — « Interdit : séquence naïve read balance → vérifier → update balance » ; exigence d'idempotency key, écriture atomique, ledger, statut explicite.
- `BR-AN-002` [MUST] — une métrique approximative (impressions dédupliquées côté client) ne doit pas être la seule preuve de facturation.

### Comportement cible
- Débit atomique unique : `update_one({"user_id": id, "balance": {"$gte": cpc}}, {"$inc": {"balance": -cpc, "total_spent": cpc, "total_clicks": 1}})` et vérification `modified_count == 1` pour décider du débit.
- Clic brut (événement observé) et clic facturable (qualifié) distingués.
- Idempotence : un identifiant d'événement de clic stable empêche la double facturation d'un replay (`BR-CPC-003`).
- Écriture d'un événement facturable dans un ledger/table d'audit lié à la campagne (source, job, cost, ts).

### Critères d'acceptation
- Solde 0,30 €, CPC 0,20 €, 2 clics simultanés → au plus 1 clic facturé, solde jamais négatif.
- Campagne `paused` → aucun débit (voir **P0-006**).
- Campagne expirée ou budget atteint → aucun débit.
- Partenaire inactif → aucun débit.
- Rejouer le même événement → aucune double facturation.

### Tests obligatoires
- Test de concurrence réel (TESTING §11) : 2 clics simultanés sur solde faible.
- Scénarios §9.4 : paused / expirée / budget atteint / partenaire inactif / replay.
- Test d'audit : chaque débit est relié à un `click_event` avec `cost` et `campaign_id`.

### Dépendances avec les autres P0
- **P0-006** : la politique de diffusion (pause/dates/budget) doit être évaluée AVANT le débit ; blocage coordonné des clics et de la visibilité.
- **P0-007** : l'attribution du débit à la bonne campagne dépend d'une identité d'annonce fiable (`campaign_id`).
- **P0-005** : même besoin d'atomicité/idempotence pour la consommation d'entitlements.

### Statut initial
TODO

---

## P0-005 Entitlements recruteur

### État actuel constaté
La publication d'offre par un recruteur (`POST /api/jobs`) ne vérifie **ni** n'évalue **aucun** crédit. En parallèle, l'achat de packs (`recruiter.py`) crédite `users.premium_credits` via `payments.py` (`_credit_if_paid`), mais ce compteur n'est jamais consommé à la création d'une offre.

### Fichiers / fonctions concernés
- `backend/routes/jobs.py` : `create_job` (lignes 251-285) — aucune vérification/consommation d'entitlement.
- `backend/routes/payments.py` : `_credit_if_paid` (lignes 151-197) — crédite `premium_credits` (pack recruteur).
- `backend/routes/recruiter.py` : `recruiter_checkout` (lignes 64-113) — initie la session Stripe.
- Modèle utilisateur : champ `premium_credits` présent mais non consommé côté backend.

### Risque
- Financier : perte de revenu (pack payé sans contrepartie de publication) ; crédits crédités et jamais débités.
- Métier : promesse produit non tenue (« 1 publication réussie = 1 consommation »), double achat inutile par l'utilisateur.
- Concurrence : sans débit atomique, deux requêtes simultanées peuvent consommer le même dernier crédit deux fois.

### Règle métier ou sécurité violée
- `BUSINESS_RULES.md` `BR-ENT-001` [P0][TARGET] (crédit = droit explicite consommable, pas un nombre affiché), `BR-ENT-002` [P0][MUST], `BR-ENT-003` [P0][MUST] (vérifié côté backend), `BR-ENT-005` [MUST] (concurrence).
- `ARCHITECTURE.md` §5.3 — cible `CreateJobUseCase` avec vérification entitlement et consommation atomique, côté backend.
- `AGENTS.md` §15 item 1 — entitlements/crédits recruteur réellement appliqués côté backend.

### Comportement cible
- À la création d'offre nécessitant un crédit : vérification `premium_credits > 0` puis débit **atomique** (`update_one` avec filtre de solde, `modified_count == 1`), liés à la même requête métier.
- Échec avant création effective → crédit non perdu (`BR-ENT-004`).
- Trace de chaque attribution/consommation (achat, admin, promotion, expiration) — `BR-ENT-006`.
- Les offreurs sans entitlement se voient refuser la publication payante côté backend, indépendamment du frontend.

### Critères d'acceptation
- 3 crédits → exactement 3 publications autorisées.
- 0 crédit → publication payante refusée (403/409) côté backend.
- Double clic avec 1 crédit → au plus 1 publication + 1 consommation.
- Erreur avant création → crédit conservé.
- Même entitlement ne peut être consommé deux fois (idempotence).

### Tests obligatoires
- Scénarios TESTING §9.2 intégralement.
- Test de concurrence TESTING §11 : 1 crédit + 10 requêtes publication simultanées → 1 consommation.
- Test d'atomicité : les échecs intermédiaires (validation, géocodage) ne consomment pas de crédit.

### Dépendances avec les autres P0
- **P0-004** : pattern de débit atomique/idempotent commun à mettre en place de façon cohérente.
- **P0-006** : la « publication » est indissociable de la politique de diffusion (une offre sans crédit et hors campagne ne doit pas être publiquement visible).
- **P0-010** : la géolocalisation fait partie de la création d'offre — à séquencer AVANT la consommation du crédit.

### Statut initial
TODO

---

## P0-006 Cycle de vie et visibilité des campagnes

### État actuel constaté
La visibilité publique d'une offre se résume au filtre `{"is_active": True}` dans `search_jobs`, `get_job`, `get_company_jobs` et `saved_jobs`. L'état de la campagne (`active`/`paused`), les dates `start_date`/`end_date`, le budget (`spent >= budget_limit`) et l'état du partenaire ne sont jamais évalués pour décider si une offre peut être affichée ou cliquée.

Par ailleurs, aucune politique centrale n'existe : chaque route recode une partie de la logique.

### Fichiers / fonctions concernés
- `backend/routes/jobs.py` : `search_jobs` (lignes 119-223), `get_job` (233-249), `get_company_jobs` (354-377), `record_partner_click` (379-434).
- `backend/routes/saved_jobs.py` : `save_job`, `get_saved_jobs` (filtrent `is_active` uniquement).
- `backend/routes/payments.py` : modèle de campagne (`CampaignCreate/Update`), `create_campaign` (définit `status: "active"` par défaut).

### Risque
- Métier : une campagne en pause, expirée ou budget épuisé continue d'être exposée et cliquée → diffusion non maîtrisée par le partenaire.
- Financier : des clics sont facturés sur des campagnes censées être stoppées ; le CPC débité contredit la promesse « budget atteint → arrêt ».
- Incohérence : `status` campagne `paused` n'a aucun effet opérationnel sur le catalogue.

### Règle métier ou sécurité violée
- `BUSINESS_RULES.md` `BR-JOB-002` [P0][TARGET] (visibilité = job actif ET source active ET campagne diffusable ET dates ET budget ET partenaire actif — décision centralisée), `BR-CAMP-003`/`004`/`005` [P0][MUST], `BR-CAMP-006` [P0][TARGET].
- `AGENTS.md` §4.4 — politique de diffusion unique, pas de duplication par route.

### Comportement cible
- Une politique/visibilité centralisée (service ou repository dédié) évalue pour chaque offre : `is_active`, état de campagne, période de validité, budget, état partenaire, modération/entitlement.
- `search_jobs`, `get_job`, `get_company_jobs`, `saved_jobs` et `record_partner_click` utilisent tous la même politique.
- La pause d'une campagne stoppe immédiatement nouvelle diffusion et nouveaux débits.

### Critères d'acceptation
- Offre d'une campagne `paused` absente de GET /jobs.
- Offre hors `start_date`/`end_date` absente de GET /jobs.
- Offre d'une campagne `spent >= budget_limit` absente de GET /jobs et non débittable.
- Offre d'un partenaire inactif absente de GET /jobs.
- La politique est unique et référencée (un seul module de source de vérité).

### Tests obligatoires
- Scénarios §9.4 : paused / expirée / budget atteint / partenaire inactif → aucune diffusion ni débit.
- Vérification de la centralisation : les 4 routeurs de lecture + le click renvoient à la même fonction.
- Test de cohérence : pause campagne alors que des offres sont `is_active=True` → plus rien de visible publiquement.

### Dépendances avec les autres P0
- **P0-004** : le clic facturable doit être bloqué par la même politique — à implémenter ensemble (blocage = pas de débit).
- **P0-007** : l'évaluation de la campagne s'appuie sur un `campaign_id` fiable stocké sur l'offre.
- **P0-005** : visibilité d'une offre payante et consumption entitlement sont deux faces de la même publication.

### Statut initial
TODO

---

## P0-007 Identité des annonces partenaires avec campaign_id

### État actuel constaté
L'upsert d'une annonce importée se fait sur `{"partner_id": partner_id, "external_ref": reference}` **sans** le `campaign_id`. Deux campagnes d'un même partenaire peuvent donc porter la même référence externe et se mettre à jour l'une l'autre (contamination croisée), mélangeant diffusion, clics et attribution.

### Fichiers / fonctions concernés
- `backend/partner_feed.py` : `import_feed` (ligne 128 — `existing = ...find_one({"partner_id": ..., "external_ref": reference})`), `import_campaign_feed` (lignes 175-198).
- `backend/routes/payments.py` : `import_campaign` (lignes 518-527) — déclencheur par campagne.
- `backend/routes/admin.py` : `import_xml_feed` — import historique hors campagne.
- Index cible attendu : `jobs(partner_id, campaign_id, external_ref)` (ARCHITECTURE.md §4).

### Risque
- Métier : annonces confondues entre campagnes du même partenaire ; une mise à jour de l'une écrase/masque l'autre.
- Financier : attribution CPC/budget/performance vers une mauvaise campagne.
- Intégrité : invalide les promesses de campagne (références, compteurs, historique d'imports).

### Règle métier ou sécurité violée
- `BUSINESS_RULES.md` `BR-FEED-002` [P0] — l'identité d'une annonce partenaire doit inclure assez de contexte (partenaire/campagne/référence externe) pour éviter les collisions ; `BR-FEED-001` (upsert sur identité externe stable).
- `AGENTS.md` §4.5 — ne jamais confondre deux annonces de campagnes distinctes ; identités métier protégées (§5.4).
- `ARCHITECTURE.md` §4 — index cible `jobs(partner_id, campaign_id, external_ref)`.

### Comportement cible
- L'upsert s'appuie sur l'identité composite `(partner_id, campaign_id, external_ref)`.
- Deux campagnes du même partenaire avec la même référence externe produisent deux annonces distinctes, maintenues indépendamment.
- L'import hors campagne (legacy) conserve une identité compatible (campagne absente → identité `(partner_id, external_ref)` en migration progressive).

### Critères d'acceptation
- Deux imports successifs d'une campagne ne dupliquent pas les annonces (upsert).
- Deux campagnes du même partenaire avec le même `external_ref` restent deux annonces distinctes.
- La mise à jour de l'une n'affecte pas l'autre (pas de croisement).
- Migration idempotente de l'index/identité `jobs(partner_id, campaign_id, external_ref)` avec compatibilité ancien format.

### Tests obligatoires
- Scénarios TESTING §9.5 : import 1 crée, import 2 met à jour sans doublon ; deux campagnes mêmes `external_ref` non contaminées ; campagne `paused` non réactivée par simple import.
- Test feed en erreur : timeout/XML invalide → anciennes annonces intactes (`BR-FEED-004`).
- Test d'idempotence de la migration avant/après.

### Dépendances avec les autres P0
- **P0-006** : la politique de visibilité s'appuie sur `campaign_id` fiable ; une identité d'annonce correcte garantit l'évaluation de la bonne campagne.
- **P0-004** : attribution du débit à la bonne campagne.
- **P0-005** : cohérence entre crédits consommées et offres importées par campagne.

### Statut initial
TODO

---

## P0-008 Open redirect des alertes

### État actuel constaté
`GET /api/alerts/track/{alert_id}?redirect=<url>` est un endpoint public (aucune authentification) qui redirige vers la valeur du paramètre `redirect` sans aucune validation d'hôte ou de domaine. Les liens des emails d'alerte passent par ce tracker avec un `redirect` construit côté serveur, mais la même route accepte n'importe quelle URL fournie par un attaquant.

### Fichiers / fonctions concernés
- `backend/routes/alerts.py` : `track_alert_click` (lignes 78-90).
- `backend/email_service.py` : `_tracked` (lignes 21-25) — génère les liens `.../api/alerts/track/{alert_id}?redirect=...`.

### Risque
- Sécurité : phishing déguisé en lien `joboolo.com` (blanchi par le domaine du site) ; un clic peut être dévié vers un site frauduleux.
- Métier : fausse attribution des clics d'alertes (billing/open-tracking) si la destination n'est pas maîtrisée.

### Règle métier ou sécurité violée
- `AGENTS.md` §9 — routes publiques/privées clairement distinguées ; robustesse des flux exposés.
- `AGENTS.md` §2/§14 — toute déviation de sécurité nécessite une décision ; la vulnérabilité « open redirect » tombe dans les risques sécurité à traiter avant livraison (`TESTING.md` §14 — impact sécurité).
- Cohérence : la cible de navigation publique ne doit jamais être pilotée par une donnée non fiable arbitraire.

### Comportement cible
- La destination du tracker est validée contre une whitelist de domaines métier (domaine `joboolo.com` et sous-domaines) ou remplacée par une route interne codée en dur (`/jobs/{id}`, `/`).
- Toute URL hors whitelist est refusée (400/403) ou ramenée à l'accueil — jamais redirigée telle quelle.

### Critères d'acceptation
- `redirect=https://evil.com` → refus (pas de `302`).
- `redirect=/jobs/abc` ou lien interne légitime → autorisé, suivi enregistré.
- La résolution du domaine ne dépend pas de la casse ni de l'encodage (normalisation avant comparaison).

### Tests obligatoires
- Test négatif : `http://evil.com`, `https://evil.com`, sous-domaines inconnus → refus.
- Test positif : liens internes des emails d'alerte → `302` vers la bonne page.
- Test de phishing : `/.joboolo.com` ou variantes de confusion de domaine → refus.
- Test de régression : le tracking de clic (compteur, `last_viewed_at`) continue de fonctionner.

### Dépendances avec les autres P0
- **P0-009** : la normalisation des identités conditionne l'exactitude du lien alerte → compte (destination et tracking).
- **P0-006** : les liens d'alertes pointent vers des offres dont la visibilité doit rester validée (offre non diffusable → lien vers page de détail incohérent).

### Statut initial
TODO

---

## P0-009 Normalisation des emails

### État actuel constaté
L'inscription classique compare l'email sans normalisation : `db.users.find_one({"email": user_data.email})`. À l'inverse, la connexion utilise une expression régulière insensible à la casse, et les flux partenaire/alerte normalisent (`lower().strip()`). Résultat : `Paul@Example.com` et `paul@example.com` peuvent créer deux comptes distincts, tandis que le login peut matcher l'un ou l'autre de façon ambiguë. Les flux entrants (alertes, OAuth Google) ne partagent pas une identité cohérente.

### Fichiers / fonctions concernés
- `backend/routes/auth.py` : `register` (ligne 64), `google_session` (ligne 274), `register_partner` (ligne 124 — normalise).
- `backend/auth.py` : `authenticate_user` (lignes 51-65 — regex casse-insensible), `get_user_by_email` (ligne 46).
- `backend/routes/alerts.py` : `subscribe_alert` (ligne 32 — normalise).
- Index attendu : `users.email_normalized` UNIQUE (ARCHITECTURE.md §4).

### Risque
- Intégrité d'identité : doublons de comptes, perte d'accès, confusion entre deux identités.
- Métier : le compte léger d'alerte (BR-ID-005) ne peut pas être revendiqué/complété si la casse diffère au moment de la création du compte complet.
- Sécurité : une prise de contrôle par variation de casse de l'email d'un autre utilisateur devient possible.

### Règle métier ou sécurité violée
- `BUSINESS_RULES.md` `BR-ID-004` [P0] — identité email insensible à la casse et aux espaces externes ; unicité sur la forme canonique ; `BR-ID-005` [P0][TARGET].
- `AGENTS.md` §5.4 — l'email normalisé est une identité stable de référence.
- `ARCHITECTURE.md` §4 — index cible `users.email_normalized` UNIQUE.

### Comportement cible
- Stockage et unicité sur `email_normalized = lower(trim(email))`.
- `register`, `register_partner`, `google_session`, `subscribe_alert`, `authenticate_user` utilisent tous la même fonction de normalisation.
- Un compte léger d'alerte peut être complété en compte complet sans « email déjà enregistré ».

### Critères d'acceptation
- `Paul@example.com` et `paul@example.com` → même identité (une seule inscription possible).
- Login avec l'une ou l'autre casse → même compte authentifié.
- Inscription d'alerte puis inscription complète même email → conversion/revendication possible.
- Utilisateur inactif → toujours refusé après normalisation (`BR-ID-003`).

### Tests obligatoires
- Scénarios TESTING §9.1 : unicité casse, cohérence login, compte léger → complet, utilisateur inactif refusé, rôle incorrect → 403.
- Test de migration idempotente de l'index `email_normalized` avec comptage avant/après.
- Test négatif : espaces externes et variantes de casse rejetées.

### Dépendances avec les autres P0
- **P0-002** : les comptes seed utilisent des emails en dur — la normalisation conditionne leur purge/remplacement propre.
- **P0-003** : la résolution propriétaire d'un document dépend de comptes non ambigus.
- **P0-008** : l'attribution des liens d'alerte à une identité fiable.

### Statut initial
TODO

---

## P0-010 Géolocalisation des offres créées manuellement

### État actuel constaté
`create_job` et `update_job` (recruteur, admin) ne géocodent jamais la `location` et ne stockent jamais le champ `loc` (2dsphere). Seules les offres importées via `partner_feed.py` appellent `geocode_place`. Résultat : la recherche par rayon (`radius`, `$geoWithin`) ne peut jamais renvoyer une offre créée manuellement. En cas d'échec du géocodeur, aucun fallback n'est défini (silencieux `None`).

### Fichiers / fonctions concernés
- `backend/routes/jobs.py` : `create_job` (lignes 251-285), `update_job` (lignes 287-318).
- `backend/routes/admin.py` : `update_job` (lignes 532-543 — change `location` sans recalcul `loc`).
- `backend/geo_service.py` : `geocode_place` (lignes 85-118) — utilitaire déjà disponible.
- `backend/partner_feed.py` : lignes 137-139 — seul usage actuel du géocodage.

### Risque
- Métier : les offres manuelles sont absentes de la recherche géographique par rayon (fonctionnalité phare de la plateforme).
- Cohérence : une modification de localisation laisse des coordonnées obsolètes ou absentes.
- Robustesse : l'échec du fournisseur de géocodage est silencieux → données incohérentes sans alerte.

### Règle métier ou sécurité violée
- `BUSINESS_RULES.md` `BR-JOB-004` [P0] — toute offre avec localisation exploitable obtient des coordonnées normalisées ; rechangement de localisation → recalcul.
- `ARCHITECTURE.md` §5.3 — pipeline cible avec `GeoService` dans la publication recruteur.
- `AGENTS.md` §15 item 7 — géocodage systématique des offres.

### Comportement cible
- À la création et à toute modification de `location` : appel à `geocode_place`, stockage de `loc` en `{"type": "Point", "coordinates": [lng, lat]}` indexé `2dsphere`.
- Définition d'un fallback explicite en cas d'échec du géocodage (file/temporisation/retry observable), jamais de données incohérentes silencieuses.
- Recherche par rayon fonctionnelle pour les offres manuelles et partenaires de manière identique.

### Critères d'acceptation
- Offre manuelle créée avec une ville → `loc` présent et cohérent.
- Recherche avec rayon retrouve cette offre.
- Changement de `location` → `loc` recalculé (pas de coordonnées de l'ancienne ville).
- Échec géocode → comportement fallback défini et observable, pas de `loc` corrompu.

### Tests obligatoires
- Scénarios TESTING §9.7 intégralement : création avec ville → loc ; rayon → trouvée ; changement location → recalcul ; échec géocode → fallback.
- Test d'index : vérifier `jobs.loc` en `2dsphere` (présent au startup).
- Test de régression sur `update_job` admin (changement de ville).

### Dépendances avec les autres P0
- **P0-005** : le géocodage doit être réalisé avant la consommation de l'entitlement (échec géocode → publication non consommée).
- **P0-006** : une offre de campagne et une offre manuelle doivent aussi passer par la politique de visibilité après géocodage.
- **P0-003** : données de localisation recalculées préservent la confiance des parcours candidats.

### Statut initial
TODO

---

## Récapitulatif

| Identifiant | Intitulé | Priorité de traitement relative |
|---|---|---|
| P0-001 | Secrets et configuration production | 1 |
| P0-002 | Seed/admin dangereux en production | 1 |
| P0-003 | ACL CV et documents privés | 2 |
| P0-004 | Débit CPC atomique | 2 |
| P0-005 | Entitlements recruteur | 3 |
| P0-006 | Cycle de vie et visibilité des campagnes | 4 |
| P0-007 | Identité des annonces partenaires avec campaign_id | 5 |
| P0-008 | Open redirect des alertes | 6 |
| P0-009 | Normalisation des emails | 7 |
| P0-010 | Géolocalisation des offres créées manuellement | 8 |

Les interdépendances notables : `P0-001`/`P0-002` (secrets + seed), `P0-004`/`P0-005` (atomicité/idempotence), `P0-004`/`P0-006` (politique avant débit), `P0-006`/`P0-007` (campagne fiable), `P0-009` (prérequis d'identité pour `P0-003`, `P0-005`, `P0-008`).