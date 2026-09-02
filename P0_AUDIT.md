# P0-011 — Audit ciblé intégrité comptes/candidatures

**Base**: SHA `581745436aaf969ea7aa87cfe7c895766b790136` (main, P0-010 mergé)

---

## 1. Cartographie des invariants métier et writers/readers

### Invariants métier (P0)
| Invariant | Description | Collection/Champ |
|-----------|-------------|------------------|
| **I-UNICITÉ_CANDIDATURE** | Un candidat ne peut postuler qu'une fois à un même job | `applications` : index unique `(job_id, candidate_id)` |
| **I-COMPTEUR_COHÉRENT** | `jobs.applications_count` = nombre exact de candidatures pour ce job | `jobs.applications_count` vs `count(applications.job_id)` |
| **I-ACL_EMPLOYEUR** | Un employeur ne lit/modifie que les candidatures de SES jobs | `jobs.employer_id` = `current_user.id` |

### Writers (écrivent l'état)
| Endpoint | Fonction | Opérations critiques |
|----------|----------|---------------------|
| `POST /applications` | `apply_to_job` (applications.py:66) | `find_one` pré-check → `insert_one` application → `$inc jobs.applications_count` |
| `PUT /applications/{id}/status` | `update_application_status` (applications.py:206) | `$set application.status` + notification email |

### Readers (lisent l'état, décisions métier)
| Endpoint | Fonction | Dépendances invariants |
|----------|----------|------------------------|
| `GET /applications` | `get_my_applications` (applications.py:143) | Lit `applications.candidate_id` |
| `GET /applications/job/{job_id}` | `get_job_applications` (applications.py:168) | Filtre `jobs.employer_id` + lit `applications.job_id` |
| `GET /messages` | `_can_message` (messages.py:20) | Vérifie existence application via `distinct job_id` |
| `GET /ai/recommendations` | `recommendations` (ai.py:44) | Exclut jobs où `applications.job_id` existe pour le candidat |

---

## 2. Scénarios de corruption/doublon/ACL reproductibles

### A. Race condition `POST /applications` vs index unique — **GRAVITÉ: HAUTE, PROBABILITÉ: MOYENNE**

**Fichier/Fonction**: `backend/routes/applications.py:66-141` → `apply_to_job`

**Code actuel**:
```python
# Lignes 88-97 : pré-check
existing_application = await db.applications.find_one({
    "job_id": application_data.job_id,
    "candidate_id": current_user.id
})
if existing_application:
    raise HTTPException(400, "You have already applied to this job")

# Ligne 110 : insert SANS gestion DuplicateKeyError
await db.applications.insert_one(app_doc)

# Lignes 112-116 : incrément compteur (séparé)
await db.jobs.update_one(
    {"_id": application_data.job_id},
    {"$inc": {"applications_count": 1}}
)
```

**Scénario reproductible**:
1. Candidat envoie 2 requêtes `POST /applications` quasi-simultanées pour le même job
2. Les deux passent le `find_one` (pré-check) car aucune n'a encore inséré
3. Première requête : `insert_one` réussit, compteur incrémenté
4. Deuxième requête : `insert_one` lève `pymongo.errors.DuplicateKeyError` (index unique ligne 142 database.py)
5. **Résultat**: Exception non gérée → **HTTP 500** au lieu de HTTP 400 attendu

**Preuve**: L'index unique existe (`database.py:142`) mais aucun `try/except DuplicateKeyError` n'entoure l'`insert_one`.

---

### B. Incohérence insertion candidature + `applications_count` — **GRAVITÉ: HAUTE, PROBABILITÉ: FAIBLE**

**Fichier/Fonction**: `backend/routes/applications.py:109-116`

**Problème**: Deux opérations distinctes sans atomicité ni compensation:
```python
await db.applications.insert_one(app_doc)           # (1) Peut réussir
await db.jobs.update_one(..., {"$inc": {"applications_count": 1}})  # (2) Peut échouer
```

**Scénarios d'échec partiel**:
- (1) réussit, (2) échoue (job supprimé, erreur réseau, timeout) → candidature orpheline, compteur sous-compté
- Retry client → nouvelle tentative crée doublon (si pas géré par A) ou double incrément si (1) échoue mais (2) réussit (impossible ici car ordre fixe)

**Pas de**: transaction MongoDB, compensation (rollback), idempotency key, retry côté serveur.

---

### C. Employer ACL lecture/changement statut — **GRAVITÉ: MOYENNE, PROBABILITÉ: FAIBLE**

**Fichiers/Fonctions**:
- `backend/routes/applications.py:168-199` → `get_job_applications`
- `backend/routes/applications.py:206-270` → `update_application_status`

**Vérification actuelle** (lignes 177-185, 229-237):
```python
job = await db.jobs.find_one({
    "_id": job_id,  # ou application["job_id"]
    "employer_id": current_user.id
})
if not job:
    raise HTTPException(403/404, ...)
```

**Analyse**: Logique correcte, cohérente avec P0-003 (ACL fichiers dans `files.py:301-308` fait la même vérification via `application.job_id → job.employer_id`). **Aucune régression détectée**.

---

### D. Références orphelines `applications` ↔ `messages` — **GRAVITÉ: BASSE, PROBABILITÉ: FAIBLE**

**Fichier**: `backend/routes/messages.py:33-39` (`_can_message`)

```python
if me.user_type == "candidate":
    my_apps = await db.applications.distinct("job_id", {"candidate_id": me.id})
    if my_apps and await db.jobs.find_one({"_id": {"$in": my_apps}, "employer_id": other_id}):
        return True
```

**Risque**: Si une candidature est supprimée (pas d'endpoint actuel), un message existant deviendrait inaccessible. **Pas de suppression d'application dans le code actuel** → risque théorique seulement.

---

## 3. Classement des risques par gravité/probabilité

| # | Risque | Gravité | Probabilité | Priorité |
|---|--------|---------|-------------|----------|
| A | Race condition `POST /applications` → DuplicateKeyError 500 | **HAUTE** | **MOYENNE** | **P0** |
| B | Incohérence insert + compteur (échec partiel) | **HAUTE** | FAIBLE | P1 |
| C | ACL employeur (régression P0-003) | MOYENNE | FAIBLE | — (OK) |
| D | Références orphelines applications/messages | BASSE | FAIBLE | — (théorique) |

**Conclusion**: Le risque **A** est le seul reproductible avec gravité haute et probabilité non-négligeable. Il constitue le prochain correctif P0 prioritaire.

---

## 4. Proposition du prochain correctif P0 minimal

### Objectif
Éliminer le HTTP 500 sous concurrence sur `POST /applications` en gérant `DuplicateKeyError` de l'index unique `(job_id, candidate_id)`.

### Règle métier
> Si un candidat tente de postuler deux fois au même job (concurrence ou retry), l'API doit retourner **HTTP 400** avec message clair, jamais HTTP 500.

### Fichiers à modifier
1. **`backend/routes/applications.py`** — fonction `apply_to_job` (lignes 66-141)

### Stratégie de concurrence/atomicité

**Option 1 (minimale, recommandée P0)** : Gestion `DuplicateKeyError` au niveau application
```python
from pymongo.errors import DuplicateKeyError

try:
    await db.applications.insert_one(app_doc)
except DuplicateKeyError:
    raise HTTPException(400, "You have already applied to this job")
```
- Avantage: Simple, sans dépendance replica set, corrige le 500 immédiat
- Inconvénient: Ne résout pas l'incohérence compteur (risque B) — à traiter en P1 si nécessaire

**Option 2 (transaction MongoDB)** : Atomicité insert + `$inc` dans une transaction
- Nécessite replica set (transactions non supportées sur standalone)
- Plus complexe, hors scope P0 minimal

**Décision P0**: **Option 1** — correction minimale, ciblée, sans préjuger de l'architecture transactionnelle future.

### Migration/index
- **Aucune migration nécessaire** : l'index unique `(job_id, candidate_id)` existe déjà (`database.py:142`)
- **Aucun index additionnel** : l'index couvre exactement l'invariant I-UNICITÉ_CANDIDATURE

### Tests à ajouter

#### Tests fake (unitaires, sans Mongo)
1. `test_apply_duplicate_key_returns_400` — simule `DuplicateKeyError` sur `insert_one`, vérifie HTTP 400
2. `test_apply_concurrent_precheck_both_pass_then_one_fails` — deux appels simulés, premier OK, deuxième 400

#### Tests Mongo réel (intégration, replica set requis)
1. `test_real_concurrent_apply_same_job_one_succeeds` — 2 tâches asyncio simultanées sur même job/candidat, exactement 1 succès, 1 erreur 400, `applications_count == 1`
2. `test_real_concurrent_apply_different_jobs_both_succeed` — pas de régression sur jobs différents

---

## 5. Ce qui n'est PAS un bug / déjà sécurisé

| Point | Statut | Justification |
|-------|--------|---------------|
| Index unique `(job_id, candidate_id)` | ✅ **Présent** | Créé au startup `database.py:142` |
| Pré-check applicatif avant insert | ✅ **Présent** | Lignes 88-97 `applications.py` |
| ACL employeur sur lectures candidatures | ✅ **Correct** | Vérification `job.employer_id == current_user.id` (lignes 177-185, 229-237) |
| ACL employeur sur changement statut | ✅ **Correct** | Même vérification, cohérente avec P0-003 |
| ACL fichiers (CV) via application | ✅ **Correct** | `files.py:301-308` vérifie `application.job_id → job.employer_id` |
| Recommandations IA excluent jobs déjà postulés | ✅ **Correct** | `ai.py:55-59` utilise `applications.distinct` |
| Messagerie vérifie application existante | ✅ **Correct** | `messages.py:33-39` |
| P0-005/006/007/008/009/010 préservés | ✅ **Aucun impact** | Audit lecture seule, pas de modification |

---

## Livrable : Plan P0-012 (correctif unique)

**Titre**: `P0-012 — Gestion DuplicateKeyError POST /applications (concurrence candidature)`

**Scope**: Uniquement `backend/routes/applications.py` fonction `apply_to_job`

**Diff minimal**:
1. Import `from pymongo.errors import DuplicateKeyError`
2. `try/except DuplicateKeyError` autour de `insert_one` (ligne 110)
3. Retour `HTTPException(400, "You have already applied to this job")` dans le `except`

**Tests**: 2 fake + 2 Mongo réel (si replica set dispo)

**Risques**: Zéro régression (ne change que le code d'erreur 500→400 sur cas limite)

**Non-inclus dans ce P0**: Transaction atomicité insert+compteur (risque B) → P1 ultérieur si incidence métier avérée.

---

TESTS=NOT_RUN