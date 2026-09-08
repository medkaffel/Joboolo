# Contrat de déploiement préproduction Joboolo

Statut : **PREP-02 — contrat uniquement**. Aucun provisionnement, déploiement externe, secret ou donnée de production n'est créé par ce lot.

Base validée : `main` au commit `2ccdb15ef41b13fc59bfc23c1a3c65d46dd30e91`.
Issue : `#80 — PREP-02 — Figer le contrat de déploiement préproduction Railway + Cloudflare Pages`.

## 1. Objectif et invariants

La préproduction cible l'architecture suivante :

- frontend React sur Cloudflare Pages ;
- backend FastAPI sur Railway ;
- MongoDB Atlas dédié à la préproduction ;
- Cloudflare R2 privé pour les objets/CV ;
- aucun service de production partagé ;
- aucun secret dans Git ;
- une seule instance backend pour la recette initiale ;
- `SCHEDULER_ENABLED=false` pour la recette initiale.

PREP-02 ne modifie aucun comportement applicatif. Il ne crée ni `Dockerfile`, ni `Procfile`, ni fichier de configuration Railway. Le mécanisme de build réellement choisi par Railway sera validé pendant le lot de provisioning/déploiement ; toute nécessité de modifier le dépôt fera l'objet d'un périmètre séparé.

## 2. Contrat Railway — backend FastAPI

### Source et exécution

```text
Root Directory: backend
Start command: uvicorn server:app --host 0.0.0.0 --port $PORT
Healthcheck Path: /api/health
Instances: 1
Scheduler: disabled
```

Railway injecte `PORT`; le serveur doit écouter sur `0.0.0.0` et sur cette valeur. Le endpoint `/api/health` existant sert de gate de déploiement : un `2xx` signifie que le processus FastAPI répond.

### Limite volontaire du healthcheck

`/api/health` est un **liveness/deployment gate**, pas un test d'intégration complet. Il ne prouve pas à lui seul :

- la disponibilité de MongoDB Atlas ;
- la capacité à lire/écrire dans R2 ;
- la disponibilité de Resend, Stripe ou du fournisseur IA.

PREP-02 ne modifie donc pas ce endpoint. Les dépendances externes seront testées par des smoke tests explicites lors des lots ultérieurs.

### Variables backend de préproduction

Variables obligatoires ou attendues pour le socle :

```text
APP_ENV=test
SECRET_KEY=<secret-preprod>
MONGO_URL=<uri-atlas-preprod>
DB_NAME=joboolo_preproduction
CORS_ALLOWED_ORIGINS=<origine-frontend-preprod-exacte>
SCHEDULER_ENABLED=false
FRONTEND_URL=<origine-frontend-preprod>
S3_ENDPOINT_URL=<endpoint-r2>
S3_ACCESS_KEY_ID=<secret-r2>
S3_SECRET_ACCESS_KEY=<secret-r2>
S3_BUCKET_NAME=<bucket-r2-preprod>
S3_REGION=auto
```

Règles :

- les vraies valeurs secrètes sont injectées dans les variables Railway, jamais commitées ;
- `CORS_ALLOWED_ORIGINS` contient l'origine HTTPS exacte du frontend, sans chemin ni wildcard ;
- `FRONTEND_URL` pointe vers l'origine de préproduction et ne doit jamais pointer vers la production pendant la recette ;
- `SCHEDULER_ENABLED=false` reste imposé jusqu'au test scheduler explicitement autorisé ;
- le bucket R2 reste privé ; les ACL applicatives Joboolo restent l'autorité d'accès aux fichiers.

`APP_PUBLIC_URL` est mentionné dans la checklist historique mais aucune référence runtime n'a été trouvée dans le code lors de PREP-02. Il n'est donc pas classé comme variable obligatoire par ce contrat. Cette observation ne justifie aucune suppression de code ou de documentation hors périmètre.

### Variables optionnelles par scénario

Ne configurer ces intégrations que pour les scénarios de recette correspondants, avec des comptes/clés de test :

- `RESEND_API_KEY`, `SENDER_EMAIL`, `ADMIN_EMAIL` ;
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` ;
- `EMERGENT_LLM_KEY` pour l'IA encore dépendante d'Emergent.

`EMERGENT_LLM_KEY` n'est plus utilisé par le stockage depuis PREP-01.

## 3. Contrat Cloudflare Pages — frontend React

```text
Root Directory: frontend
Build command: yarn build
Build output directory: build
REACT_APP_BACKEND_URL=https://<backend-preprod>
```

Règles :

- `REACT_APP_BACKEND_URL` est une variable publique de build, pas un secret ;
- sa valeur est l'origine backend HTTPS **sans suffixe `/api` et sans slash final** ;
- le frontend construit déjà les appels sous la forme `${REACT_APP_BACKEND_URL}/api` ;
- aucune clé privée, URI MongoDB ou credential R2 ne doit être exposé au build frontend.

Une fois l'URL Pages connue, son origine exacte doit être reportée dans `CORS_ALLOWED_ORIGINS` et `FRONTEND_URL` côté Railway.

## 4. Dépendances externes — contrat de préproduction

### MongoDB Atlas

Exigences :

- projet/cluster dédié à Joboolo préproduction ;
- aucune donnée de production ;
- base explicite `joboolo_preproduction` ;
- URI fournie uniquement à Railway via `MONGO_URL` ;
- connectivité réseau limitée au strict nécessaire ;
- migrations/indexes appliqués explicitement selon la checklist avant les scénarios qui en dépendent.

Le choix du tier Atlas et la stratégie exacte d'allowlist réseau appartiennent au lot de provisioning Atlas, pas à PREP-02.

### Cloudflare R2

Exigences :

- bucket dédié à la préproduction ;
- bucket privé ;
- credentials R2 dédiés et injectés uniquement côté backend ;
- conservation des clés objet applicatives existantes sous le préfixe `joboolo/...` ;
- aucune migration d'objets historiques Emergent dans PREP-02.

## 5. Conventions de nommage proposées

Ces noms sont des conventions de travail, pas des ressources créées par PREP-02 :

```text
Environment: preproduction
Railway project/service: joboolo-preprod / backend
Cloudflare Pages project: joboolo-preprod
MongoDB Atlas project: joboolo-preprod
MongoDB database: joboolo_preproduction
R2 bucket: joboolo-preprod-private
```

Si une contrainte fournisseur impose un nom différent, conserver le principe d'isolation `preprod` et documenter l'écart avant déploiement.

## 6. Ordre recommandé des lots suivants

Atlas et R2 sont indépendants et peuvent être provisionnés en parallèle. Le découpage reste celui validé pour la préparation de la préproduction :

1. **PREP-03 — MongoDB Atlas préproduction** : créer l'environnement dédié, le réseau, l'utilisateur et la base ; préparer les migrations requises.
2. **PREP-04 — Cloudflare R2 préproduction** : créer le bucket privé et les credentials dédiés.
3. **PREP-05 — Configuration préproduction** : préparer les variables/secrets Railway et Pages, les comptes de test externes, les origines attendues et maintenir `SCHEDULER_ENABLED=false`, sans lancer encore la recette externe.
4. **PREP-06 — Déploiement et recette** : créer/configurer les services Railway/Pages nécessaires, déployer le backend puis le frontend, boucler `REACT_APP_BACKEND_URL` / `CORS_ALLOWED_ORIGINS` / `FRONTEND_URL`, traiter le routage `/api/alerts/track`, puis exécuter les smoke tests navigateur/API/Atlas/R2 et les scénarios externes autorisés.

Aucun passage en production ne découle automatiquement de la réussite de ces étapes.

## 7. Point de vigilance : tracker d'alertes sur le domaine frontend

La checklist existante exige que `/api/alerts/track` soit joignable via le domaine frontend. Avec un frontend Pages et un backend Railway séparés, ce routage/proxy doit être défini explicitement pendant le lot de déploiement.

PREP-02 **ne crée pas** de Pages Function, `_redirects`, Worker ou autre mécanisme de proxy. Si le routage ne peut pas être réalisé uniquement par configuration externe, arrêter le déploiement et ouvrir un lot dédié avant toute modification du dépôt.

## 8. Gates avant premier déploiement externe

Avant de lancer la recette :

- Atlas et R2 préproduction existent et sont isolés ;
- aucune URI/clé de production n'est utilisée ;
- le backend Railway a une seule instance ;
- `SCHEDULER_ENABLED=false` ;
- `REACT_APP_BACKEND_URL` ne contient pas `/api` ;
- `CORS_ALLOWED_ORIGINS` correspond exactement à l'origine Pages ;
- `FRONTEND_URL` correspond à l'origine Pages ;
- le bucket R2 est privé ;
- le routage `/api/alerts/track` via le domaine frontend est défini ou bloqué comme dépendance ;
- les trois checks GitHub existants sont verts sur la révision à déployer.

## 9. Références fournisseur à revalider lors du provisioning

Les conventions suivantes ont été vérifiées le 8 septembre 2026 :

- Railway monorepo/root directory : https://docs.railway.com/deployments/monorepo
- Railway healthchecks et variable `PORT` : https://docs.railway.com/deployments/healthchecks
- Railway FastAPI start command : https://docs.railway.com/deployments/troubleshooting/no-start-command-could-be-found
- Cloudflare Pages monorepos : https://developers.cloudflare.com/pages/configuration/monorepos/
- Cloudflare Pages build configuration : https://developers.cloudflare.com/pages/configuration/build-configuration/

Les interfaces et conventions fournisseurs pouvant évoluer, les revalider avant le provisioning effectif plutôt que d'élargir silencieusement ce contrat.
