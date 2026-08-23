# Contrats API - Indeed Clone

## 1. API Contracts

### Emplois (Jobs)
- **GET /api/jobs** - Récupérer tous les emplois avec pagination
  - Query params: `page`, `limit`, `search`, `location`, `sort`
  - Response: `{ jobs: Job[], total: number, page: number, totalPages: number }`

- **GET /api/jobs/:id** - Récupérer un emploi spécifique
  - Response: `Job`

- **POST /api/jobs** - Créer un nouvel emploi (employeurs)
  - Body: `JobCreate`
  - Response: `Job`

- **PUT /api/jobs/:id** - Mettre à jour un emploi
  - Body: `JobUpdate`
  - Response: `Job`

- **DELETE /api/jobs/:id** - Supprimer un emploi

### Utilisateurs (Users)
- **POST /api/auth/register** - Inscription utilisateur
  - Body: `{ email, password, firstName, lastName, userType }`
  - Response: `{ user: User, token: string }`

- **POST /api/auth/login** - Connexion utilisateur
  - Body: `{ email, password }`
  - Response: `{ user: User, token: string }`

- **GET /api/users/profile** - Profil utilisateur (authentifié)
  - Response: `User`

- **PUT /api/users/profile** - Mettre à jour le profil
  - Body: `UserUpdate`
  - Response: `User`

### Candidatures (Applications)
- **POST /api/applications** - Postuler à un emploi
  - Body: `{ jobId, coverLetter?, cv? }`
  - Response: `Application`

- **GET /api/applications** - Mes candidatures
  - Response: `Application[]`

- **GET /api/applications/job/:jobId** - Candidatures pour un emploi (employeur)
  - Response: `Application[]`

### Entreprises (Companies)
- **GET /api/companies** - Liste des entreprises
  - Response: `Company[]`

- **GET /api/companies/:id** - Détails d'une entreprise
  - Response: `Company`

- **POST /api/companies** - Créer/revendiquer une entreprise
  - Body: `CompanyCreate`
  - Response: `Company`

## 2. Données mockées à remplacer

Dans `/frontend/src/data/mockJobs.js` :
- `mockJobs` array → Remplacé par appels API `GET /api/jobs`
- `getJobsBySearch()` → Remplacé par `GET /api/jobs?search=...&location=...`

Les données mockées incluent :
- 8 emplois avec titre, entreprise, localisation, salaire, type, description
- Badges "Nouveau" et "Urgent"
- Dates de publication
- Types de contrat (CDI, Titulaire, etc.)

## 3. Implémentation Backend

### Modèles MongoDB
1. **Job** - Offres d'emploi
2. **User** - Utilisateurs (candidats + employeurs)
3. **Company** - Entreprises
4. **Application** - Candidatures
5. **SavedJob** - Emplois sauvegardés

### Fonctionnalités Backend
- Authentification JWT
- CRUD complet pour les emplois
- Système de recherche et filtrage avancé
- Gestion des candidatures
- Upload de CV et lettres de motivation
- Pagination et tri
- Validation des données avec Pydantic
- Gestion des erreurs et logs

### Sécurité
- Hashage des mots de passe
- Validation des tokens JWT
- Permissions par rôle (candidat/employeur/admin)
- Validation et sanitisation des inputs

## 4. Intégration Frontend & Backend

### Services Frontend
Créer `/frontend/src/services/` avec :
- `api.js` - Configuration Axios
- `authService.js` - Authentification
- `jobService.js` - Gestion des emplois
- `userService.js` - Gestion utilisateur
- `applicationService.js` - Candidatures

### Context React
- `AuthContext` - État d'authentification global
- `JobContext` - État des emplois et recherches

### Composants à modifier
1. **SearchSection.jsx** - Utiliser `jobService.searchJobs()`
2. **JobList.jsx** - Remplacer mockJobs par appels API
3. **JobCard.jsx** - Ajouter fonctionnalités sauvegarde/candidature
4. **Header.jsx** - Ajouter vraie authentification
5. **Nouveau : AuthModal.jsx** - Modal connexion/inscription

### Nouvelles pages à créer
- `/login` - Page de connexion
- `/register` - Page d'inscription
- `/profile` - Profil utilisateur
- `/my-applications` - Mes candidatures
- `/post-job` - Publier une offre (employeurs)
- `/job/:id` - Détail d'un emploi

### Gestion d'état
- Utiliser React Context pour l'authentification
- États locaux pour les formulaires
- Cache simple pour les données fréquemment utilisées

## 5. Migration des données

Les données mockées actuelles seront utilisées comme seed data pour peupler la base MongoDB avec des emplois de test réalistes.