# TESTING.md — Stratégie de test et validation Joboolo

**Statut :** procédure obligatoire avant merge d'une évolution.  
**Dernière mise à jour :** 2026-09-01

---

## 1. Objectif

Les tests Joboolo doivent prouver deux choses :

1. la fonctionnalité demandée fonctionne ;
2. les invariants métier critiques restent vrais sous erreurs, retries et concurrence.

Un code qui « compile » n'est pas automatiquement un code validé.

---

## 2. Environnements de test

Utiliser au minimum :

```text
local/development
staging/test
production
```

### Interdictions

Ne jamais lancer contre la production :

- tests créant/supprimant des utilisateurs ;
- tests créant/supprimant des offres ;
- tests de webhook simulé ;
- tests CPC répétitifs ;
- tests de migration destructive ;
- tests de purge ;
- tests de charge.

Les tests existants créent parfois des données et modifient des ressources. Ils doivent donc viser uniquement un environnement de test/staging.

---

## 3. Pré-requis backend local

Exemple depuis le dépôt :

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

Configurer un `.env` local non versionné avec au minimum les variables nécessaires au scénario testé, par exemple :

```text
MONGO_URL=...
DB_NAME=joboolo_test
SECRET_KEY=...
```

Ajouter les clés Stripe/email/storage/IA uniquement si le test concerné en a besoin, et toujours utiliser des credentials de test.

Lancer l'API :

```bash
cd backend
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

Test de santé :

```bash
curl http://localhost:8000/api/health
```

---

## 4. Vérification syntaxique backend

Commande minimale après toute modification Python :

```bash
python -m compileall backend
```

Cette commande ne remplace pas pytest mais détecte rapidement les erreurs de syntaxe/import compilable.

---

## 5. Tests backend existants

Les tests historiques sont majoritairement des tests HTTP d'intégration utilisant `requests` contre une API déjà démarrée.

Ils attendent typiquement :

```text
REACT_APP_BACKEND_URL=http://localhost:8000
```

Exemple :

```bash
export REACT_APP_BACKEND_URL=http://localhost:8000
pytest backend/tests -q
```

Sous Windows PowerShell :

```powershell
$env:REACT_APP_BACKEND_URL="http://localhost:8000"
pytest backend/tests -q
```

### Attention

Certains tests historiques utilisent des comptes seed ou modifient des ressources existantes. Vérifier le fichier avant exécution et ne jamais pointer vers production.

---

## 6. Frontend

Le projet frontend utilise actuellement CRACO / React Scripts.

Installation :

```bash
cd frontend
yarn install
```

**Cible recommandée :** committer un `yarn.lock`, puis utiliser :

```bash
yarn install --frozen-lockfile
```

Lancement :

```bash
yarn start
```

Build production :

```bash
yarn build
```

Tests :

```bash
yarn test --watchAll=false
```

Le build frontend est un gate important : une PR frontend ne doit pas être mergée si le build échoue.

---

## 7. Lint et format

Le dépôt contient ESLint/Black/Flake8 dans les dépendances, mais les scripts doivent être vérifiés dans la branche courante avant usage.

Backend, lorsque configuré :

```bash
black --check backend
flake8 backend
```

Ne pas lancer un auto-format massif sur tout le dépôt dans une PR métier sans décision explicite.

Frontend : ajouter/standardiser un script `lint` dans une tâche dédiée si nécessaire. Ne pas prétendre qu'un lint a été exécuté si aucun script/config fiable n'existe.

---

## 8. Niveaux de tests attendus

### Niveau A — Smoke

À chaque changement :

- backend compile ;
- API health OK ;
- frontend build OK si frontend touché ;
- route principale du changement répond correctement.

### Niveau B — Régression de domaine

Exécuter tous les tests du domaine touché :

- auth ;
- jobs ;
- applications ;
- files ;
- partner/campaign ;
- payments ;
- alerts ;
- messaging ;
- AI ;
- analytics.

### Niveau C — Invariants critiques

Obligatoire pour :

- argent ;
- crédits ;
- permissions ;
- documents privés ;
- migration ;
- suppression ;
- concurrence ;
- webhooks.

---

## 9. Tests prioritaires à ajouter

### 9.1 Identité

```text
[ ] Paul@example.com et paul@example.com ne créent pas deux identités
[ ] login est cohérent avec l'unicité email
[ ] compte léger d'alerte peut devenir compte complet
[ ] utilisateur inactif refusé
[ ] rôle incorrect → 403
```

### 9.2 Publication recruteur / entitlements

```text
[ ] 3 crédits → exactement 3 publications autorisées
[ ] 0 crédit → publication payante refusée côté backend
[ ] double clic avec 1 crédit → au plus 1 publication/consommation
[ ] erreur avant création → crédit non perdu
[ ] même entitlement ne peut être consommé deux fois
[ ] admin/flux spéciaux suivent leur règle explicite
```

### 9.3 Stripe

```text
[ ] paiement non confirmé → aucun crédit
[ ] webhook reçu 2 fois → un seul crédit
[ ] status endpoint + webhook concurrents → un seul crédit
[ ] crash/retry ne perd pas le crédit dû
[ ] mauvais owner/session → refus
[ ] montant/devise inattendus → refus ou traitement explicite
```

### 9.4 CPC

Test de concurrence essentiel :

```text
balance = 0,30 €
CPC = 0,20 €
2 clics simultanés
```

Résultat attendu : au plus un clic facturé si la règle exige le solde disponible avant chaque débit ; aucun solde négatif causé par race condition.

Autres tests :

```text
[ ] campagne paused → aucun nouveau débit
[ ] campagne expirée → aucun nouveau débit
[ ] budget atteint → aucun nouveau débit
[ ] partenaire inactif → aucun nouveau débit
[ ] replay event → pas de double facturation si idempotence activée
```

### 9.5 Flux XML

```text
[ ] première importation crée annonces
[ ] deuxième import met à jour sans doublon
[ ] annonce absente d'un import réussi → désactivation selon règle
[ ] feed timeout → anciennes annonces restent intactes
[ ] XML invalide → anciennes annonces restent intactes
[ ] deux campagnes avec même external_ref ne se contaminent pas
[ ] campagne paused ne redevient pas diffusable par simple import
```

### 9.6 Documents

```text
[ ] propriétaire peut télécharger son CV
[ ] candidat B ne peut pas télécharger CV candidat A
[ ] employeur sans relation → 403
[ ] employeur autorisé par candidature → accès selon règle
[ ] document supprimé → inaccessible
[ ] type interdit → upload refusé
[ ] taille excessive → upload refusé
[ ] chemin arbitraire/traversal → refus
```

### 9.7 Géolocalisation

```text
[ ] offre manuelle créée avec ville → loc calculé
[ ] recherche rayon trouve l'offre
[ ] changement location → loc recalculé
[ ] échec géocode → comportement fallback défini, pas de donnée incohérente
```

### 9.8 Candidatures

```text
[ ] candidature unique par job/candidat
[ ] candidat ne lit que ses candidatures
[ ] recruteur ne lit que candidatures de ses offres
[ ] changement statut par utilisateur non autorisé → 403
[ ] side effect email en panne n'endommage pas application créée
```

### 9.9 Messagerie

```text
[ ] non-participant → 403
[ ] messages paginés correctement
[ ] ordre chronologique stable
[ ] unread count cohérent
[ ] polling/delta ne duplique pas les messages
```

### 9.10 IA / Matching

```text
[ ] fournisseur indisponible → fallback prévu
[ ] JSON invalide → erreur contrôlée
[ ] score hors plage → normalisé/refusé
[ ] aucune donnée sensible inutile envoyée
[ ] contenu candidat ne peut pas remplacer les instructions système
[ ] version modèle/prompt observable si fonctionnalité auditée
```

---

## 10. Tests de permissions : matrice minimale

Pour chaque endpoint privé important, tester :

| Acteur | Ressource propre | Ressource autre utilisateur | Résultat attendu |
|---|---:|---:|---|
| Candidate | oui | non | selon domaine |
| Employer | oui | non | ownership obligatoire |
| Partner | oui | non | ownership obligatoire |
| Admin | selon policy | selon policy | explicitement défini |
| Anonymous | non | non | 401/403 |

Ne pas se contenter d'un seul test « sans token ».

---

## 11. Tests de concurrence

Les tests financiers et de stock/crédit doivent réellement envoyer plusieurs requêtes en parallèle.

Exemples de scénarios :

```text
1 crédit + 10 requêtes publication simultanées
→ au plus 1 consommation autorisée

balance faible + 20 clics simultanés
→ aucun dépassement de la règle de solde

1 session Stripe + 10 traitements simultanés
→ 1 crédit final
```

Un test séquentiel ne prouve pas l'absence de race condition.

---

## 12. Migrations MongoDB

Toute migration doit être :

- idempotente ;
- relançable ;
- observable ;
- testée sur copie/staging ;
- accompagnée d'un comptage avant/après ;
- accompagnée d'une stratégie de rollback ou compatibilité descendante.

Structure recommandée d'un script :

```text
1. dry-run / count
2. batch limité
3. logs sans données sensibles
4. résumé
5. code de sortie clair
```

Avant production, sauvegarde vérifiée.

---

## 13. Staging — checklist fonctionnelle

Après déploiement staging :

### Candidat

```text
[ ] inscription/login
[ ] recherche
[ ] géolocalisation/rayon
[ ] détail offre
[ ] sauvegarde
[ ] candidature
[ ] upload/download CV
[ ] alertes
[ ] recommandations si concernées
[ ] messages si concernés
```

### Recruteur

```text
[ ] login
[ ] entreprise
[ ] achat/test checkout si concerné
[ ] crédits/droits
[ ] création offre
[ ] modification/toggle
[ ] réception candidature
[ ] statut candidature
[ ] analytics
[ ] messagerie
```

### Partenaire

```text
[ ] login
[ ] campagne
[ ] feed
[ ] import
[ ] affichage jobs
[ ] tracking
[ ] débit test
[ ] pause/reprise
[ ] performance
```

### Admin

```text
[ ] auth admin
[ ] users
[ ] jobs
[ ] partners
[ ] campaigns/feeds
[ ] settings
[ ] actions financières critiques si concernées
```

---

## 14. PR gate obligatoire

Une PR ne doit pas être déclarée prête tant que son auteur/agent ne fournit pas :

```text
[ ] objectif métier
[ ] fichiers modifiés
[ ] migration éventuelle
[ ] tests exécutés
[ ] résultats des tests
[ ] cas limites couverts
[ ] impact sécurité/permissions
[ ] impact données personnelles
[ ] impact financier
[ ] impact performance
[ ] rollback
```

---

## 15. Règle de vérité

Formulations interdites sans preuve :

- « tous les tests passent » si toute la suite n'a pas été lancée ;
- « aucun impact » sans analyse ;
- « sécurisé » sans tests de permission ;
- « idempotent » sans test de replay ;
- « thread-safe/concurrent-safe » sans opération atomique ou test de concurrence ;
- « compatible production » si seulement testé localement.

Toujours distinguer :

```text
TESTÉ
NON TESTÉ
RISQUE CONNU
```
