# ARCHITECTURE.md — Architecture de Joboolo

**Statut :** document d'architecture vivant.  
**Dernière mise à jour :** 2026-09-01  
**Objectif :** décrire l'état actuel, les frontières de domaines et la cible d'évolution sans imposer de réécriture globale.

---

## 1. Vision système

Joboolo est une plateforme d'emploi à plusieurs faces :

```text
                         JOOBOLO
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
      CANDIDATS        RECRUTEURS        PARTENAIRES
          │                 │                 │
   recherche/offres    offres/candidats     feeds XML
   candidatures        analytics            campagnes
   CV/alertes          messagerie           CPC/packs
          │                 │                 │
          └─────────────────┼─────────────────┘
                            ▼
                         FastAPI
                            │
                         MongoDB
                            │
        ┌─────────┬─────────┼─────────┬──────────┐
        ▼         ▼         ▼         ▼          ▼
      Stripe    Email    Storage     IA       Geo/Scheduler
```

Le back-office admin opère transversalement sur utilisateurs, offres, partenaires, campagnes, paramètres et contenu.

---

## 2. Stack actuelle

### Frontend

- React 19
- React Router
- CRACO / `react-scripts`
- Tailwind CSS
- Radix/shadcn-style components
- Axios
- React Hook Form / Zod selon les écrans

### Backend

- Python
- FastAPI
- Pydantic
- Motor / MongoDB
- JWT bearer auth
- APScheduler
- Stripe
- Resend/email
- object storage compatible S3
- géocodage
- fournisseurs IA via bibliothèques dédiées

### API

Toutes les routes applicatives sont exposées sous :

```text
/api/...
```

---

## 3. Domaines fonctionnels actuels

Les modules historiques sont principalement organisés dans `backend/routes/` et les services/utilitaires dans `backend/`.

### Identity / Auth

Responsabilités :

- inscription ;
- connexion ;
- Google/session OAuth ;
- profil utilisateur ;
- rôles ;
- JWT ;
- statut actif/vérifié.

Rôles principaux : `candidate`, `employer`, `partner`, `admin`.

### Jobs

Responsabilités :

- recherche ;
- suggestion ;
- détail ;
- création recruteur ;
- modification ;
- activation/désactivation ;
- offres d'entreprise ;
- tracking clics/impressions partenaire.

### Companies

Responsabilités :

- fiche entreprise ;
- ownership recruteur ;
- logo et informations métier.

### Applications

Responsabilités :

- candidature candidat ;
- unicité candidat/offre ;
- consultation candidat ;
- consultation recruteur ;
- changement de statut ;
- notifications associées.

### Candidate documents

Responsabilités :

- photo profil ;
- CV ;
- lettres de motivation ;
- object storage ;
- métadonnées documents ;
- téléchargement.

### Alerts

Responsabilités :

- alertes de recherche ;
- fréquences ;
- abonnements sans compte complet ;
- envoi scheduler ;
- tracking de clic.

### Partner / Campaigns / Feeds

Responsabilités :

- profil partenaire ;
- mode de facturation ;
- balance ou packs ;
- campagnes ;
- imports XML ;
- performance ;
- logos ;
- imports planifiés.

### Recruiter commerce

Responsabilités :

- packs/offres commerciales ;
- checkout Stripe ;
- devis ;
- crédits Premium côté recruteur.

### Payments

Responsabilités :

- sessions Stripe ;
- webhooks ;
- statut transaction ;
- recharge partenaire ;
- crédit recruteur ;
- idempotence partielle.

### Geo

Responsabilités :

- détection ;
- autocomplete ;
- géocodage ;
- coordonnées `2dsphere` ;
- recherche par rayon.

### AI / Matching

La version récente ajoute une couche de recommandation/matching, avec présélection déterministe puis recours éventuel à un fournisseur IA.

Responsabilités cibles :

- extraction/normalisation ;
- shortlist ;
- scoring ;
- explication ;
- fallback ;
- audit/coût.

### Messaging

La version récente inclut une messagerie candidat–recruteur.

À terme, la conversation doit devenir une ressource explicite plutôt qu'être reconstruite en permanence à partir d'un grand nombre de messages.

### Analytics

La version récente inclut des analytics recruteur calculés à partir des offres/candidatures et compteurs disponibles.

La cible est une analytics événementielle, non limitée par des chargements arbitraires de milliers de documents.

---

## 4. Collections MongoDB principales

Les noms exacts doivent toujours être vérifiés dans la branche courante avant modification. Les collections observées/attendues incluent notamment :

```text
users
companies
jobs
applications
saved_jobs
alerts
candidate_documents
files                # legacy/à unifier selon parcours
partner_profiles
campaigns
payment_transactions
footer_countries
messages
```

D'autres collections de tracking/import/IA peuvent exister selon la version courante.

### Index déjà structurants

- `users.email` unique actuellement ;
- `applications(job_id, candidate_id)` unique ;
- index jobs par title/location/company/employer/date/actif ;
- index texte jobs ;
- `jobs.loc` en `2dsphere` ;
- `saved_jobs(user_id, job_id)` unique.

### Index cibles importants

À ajouter uniquement avec la requête qui les justifie :

```text
users(email_normalized) UNIQUE
campaigns(partner_id, status)
jobs(campaign_id, is_active)
jobs(partner_id, campaign_id, external_ref)
messages(conversation_id, created_at)
alerts(user_id, is_active)
payment_transactions(provider_session_id) UNIQUE
candidate_documents(owner_id, category, is_deleted)
events(event_type, occurred_at)
ledger(account_id, created_at)
```

---

## 5. Flux métier principaux

### 5.1 Recherche candidat

```text
Recherche UI
  ↓
GET /api/jobs
  ↓
filtres Mongo + géo
  ↓
enrichissement entreprise/campagne
  ↓
liste publique
```

Cible : séparer clairement retrieval, eligibility, ranking et enrichment.

### 5.2 Candidature

```text
Candidat
  ↓
POST /api/applications
  ↓
permission + unicité
  ↓
écriture application
  ↓
compteurs / email / analytics
```

Cible : l'écriture de la candidature est l'opération principale ; email, analytics et autres effets deviennent des side effects via événement/outbox.

### 5.3 Publication recruteur

État actuel : création directe via route jobs. Les crédits commerciaux existent mais leur consommation doit être rendue explicite et obligatoire côté backend.

Cible :

```text
CreateJobUseCase
  ├─ vérifier recruteur
  ├─ vérifier ownership entreprise
  ├─ vérifier entitlement
  ├─ normaliser + géocoder
  ├─ stocker job
  ├─ consommer entitlement atomiquement
  └─ émettre job.created
```

### 5.4 Import partenaire

```text
feed XML
  ↓
parser
  ↓
normalisation
  ↓
géocodage
  ↓
upsert annonces
  ↓
fin d'import validée
  ↓
désactivation des annonces non vues
```

La dernière étape ne doit jamais s'exécuter après un import incomplet/échoué.

### 5.5 CPC partenaire

```text
clic utilisateur
  ↓
qualification antifraude minimale
  ↓
opération atomique balance/budget
  ↓
ledger / événement facturable
  ↓
analytics
```

Le clic brut et le clic facturable sont deux notions différentes.

### 5.6 Stripe

```text
checkout
  ↓
Stripe
  ↓
webhook/status
  ↓
transaction idempotente
  ↓
ledger
  ↓
entitlement/balance
```

La vérité commerciale ne doit pas dépendre uniquement du retour navigateur après paiement.

---

## 6. Problèmes d'architecture connus à traiter progressivement

### P0 — sécurité / revenu / intégrité

1. crédits recruteur non garantis partout comme entitlement backend ;
2. débit CPC à rendre atomique ;
3. campagne pause/dates/budget pas encore centralisés dans une politique unique de diffusion ;
4. disparition d'une annonce du feed à gérer explicitement ;
5. ACL des CV/documents à renforcer ;
6. identité email à normaliser ;
7. compte créé par alerte à rendre revendicable/completable ;
8. géocodage à appliquer aux offres manuelles également ;
9. secrets/fallbacks et comptes seed à interdire en production.

### P1 — évolutivité

1. routes encore trop responsables des règles métier ;
2. absence de ledger financier généralisé ;
3. side effects synchrones/dispersés ;
4. scheduler embarqué dans le processus web ;
5. N+1 sur certains enrichissements ;
6. recherche regex peu scalable ;
7. messagerie basée sur polling/reconstruction ;
8. analytics calculés depuis des chargements bornés ;
9. absence d'événementiel produit unifié.

---

## 7. Architecture cible : monolithe modulaire

La cible n'est pas une réécriture immédiate, mais une direction :

```text
backend/
  app/
    core/
      config
      database
      auth
      security
      errors
      observability

    domains/
      identity/
      candidates/
      employers/
      jobs/
      applications/
      partners/
      campaigns/
      billing/
      alerts/
      messaging/
      matching/
      analytics/

    integrations/
      stripe/
      email/
      storage/
      llm/
      geo/

    workers/
```

Ne pas déplacer tous les fichiers d'un coup. Extraire domaine par domaine lorsque de nouvelles évolutions touchent la zone.

---

## 8. Pattern cible d'un domaine

```text
Router HTTP
   ↓
Use Case / Service métier
   ↓
Repository / Gateway
   ↓
MongoDB ou intégration externe
```

Exemple :

```text
POST /jobs
  ↓
JobService.create_job()
  ├─ EmployerPolicy
  ├─ EntitlementService
  ├─ GeoService
  ├─ JobRepository
  └─ DomainEvents
```

La route doit rester fine.

---

## 9. Domain Events et Outbox

Événements cibles :

```text
user.registered
job.created
job.updated
job.published
job.viewed
job.clicked
application.created
application.status_changed
payment.succeeded
credit.granted
entitlement.consumed
campaign.started
campaign.paused
campaign.budget_exhausted
feed.import_succeeded
feed.import_failed
message.sent
alert.created
alert.clicked
```

Format minimal :

```text
event_id
event_type
actor_id
subject_id
occurred_at
metadata
schema_version
```

L'outbox permet de publier ces événements après une opération métier sans rendre l'API dépendante d'un email ou autre service externe.

---

## 10. Billing : architecture cible

Deux concepts distincts :

### Ledger

Historique immuable des mouvements monétaires/crédits.

```text
ledger_entry
  id
  account_id
  amount_minor
  currency
  type
  source_type
  source_id
  idempotency_key
  created_at
  metadata
```

### Entitlement

Droit consommable ou temporaire :

```text
entitlement
  id
  owner_id
  type
  quantity_total
  quantity_remaining
  source
  starts_at
  expires_at
  created_at
```

Exemples : `job_post`, `featured_job`, `candidate_unlock`, `analytics_access`.

---

## 11. Recherche et ranking : cible

Éviter de transformer `GET /jobs` en énorme bloc de règles.

Pipeline recommandé :

```text
Query parsing
  ↓
Retrieval
  ↓
Eligibility / visibilité
  ↓
Deduplication
  ↓
Relevance
  ↓
Quality
  ↓
Commercial ranking
  ↓
Personalization
  ↓
Enrichment
```

Le ranking commercial ne doit pas sacrifier les règles de qualité, sécurité ou pertinence.

---

## 12. Donnée normalisée

### Job

Cible progressive :

```text
occupation_id
occupation_family
specialization
seniority
skills_normalized
location_normalized
salary_min/max normalisés
remote_policy
industry
contract_type
```

### Candidate

Cible progressive :

```text
occupations
skills
skill_evidence
experience
seniority
mobility
salary_expectation
contract_preferences
availability
```

Le CV et la description d'offre restent les sources brutes ; les profils normalisés deviennent les données de travail pour matching/recherche.

---

## 13. Messagerie : cible

Introduire à terme une ressource `conversation` :

```text
conversations
  id
  participants
  job_id
  last_message_at
  last_message_preview
  unread_counts
  status

messages
  id
  conversation_id
  sender_id
  body
  created_at
  read_at
```

Éviter de reconstruire la liste de conversations en parcourant des milliers de messages à chaque polling.

---

## 14. Analytics : cible événementielle

Les compteurs actuels restent utiles, mais l'analytics commerciale doit se baser sur des événements explicites :

```text
job.impression
job.viewed
job.clicked
application.started
application.submitted
application.reviewed
application.accepted
payment.succeeded
message.sent
```

Objectif : funnels fiables, cohortes, attribution, facturation et expérimentation.

---

## 15. Environnements

Au minimum :

```text
development
staging
production
```

Chaque environnement doit avoir :

- base Mongo séparée ;
- clés Stripe séparées ;
- configuration email séparée ;
- bucket/namespace de stockage séparé si possible ;
- secrets IA séparés ;
- URLs frontend/backend explicites.

Aucun seed automatique ni compte admin hardcodé en production.

---

## 16. Observabilité cible

Chaque requête importante doit pouvoir être corrélée via un `request_id`.

Logs structurés à enrichir selon le contexte :

```text
request_id
user_id
job_id
application_id
campaign_id
payment_id
event_id
duration_ms
status
error_category
```

Ne jamais logger de CV, token, mot de passe, secret, numéro de carte ou contenu privé inutile.

---

## 17. Décisions à ne pas prendre implicitement

Une évolution ne doit pas changer sans décision explicite :

- modèle de tarification ;
- conservation de données ;
- consentement candidat ;
- algorithme de ranking commercial ;
- politique de visibilité ;
- suppression/anonymisation ;
- ownership des entreprises/offres ;
- signification d'un crédit ;
- règles de facturation CPC.

Ces sujets doivent être documentés dans une issue/ADR avant implémentation.

---

## 18. Règle d'évolution

**Strangler pattern interne :** quand une évolution touche un ancien bloc, extraire juste assez de logique pour rendre la nouvelle règle testable et réutilisable, puis laisser le reste en place.

Le succès architectural de Joboolo se mesure par :

- règles métier plus explicites ;
- moins de duplication ;
- opérations financières traçables ;
- permissions vérifiables ;
- tests plus ciblés ;
- changements plus petits ;
- rollback plus simple.
