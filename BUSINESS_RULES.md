# BUSINESS_RULES.md — Règles métier de Joboolo

**Statut :** source de vérité métier à maintenir avec le code.  
**Dernière mise à jour :** 2026-09-01

---

## 1. Comment lire ce document

Étiquettes utilisées :

- **[MUST]** : invariant obligatoire à garantir côté backend ;
- **[CURRENT]** : comportement observé dans le produit/code actuel ;
- **[TARGET]** : comportement voulu mais pouvant nécessiter une évolution ;
- **[P0]** : priorité critique avant d'étendre fortement la fonctionnalité.

Si le code contredit une règle **[MUST]**, ne pas adapter la règle silencieusement : ouvrir une décision ou corriger le code.

---

## 2. Utilisateurs et rôles

### BR-ID-001 — Rôles

**[MUST]** Un utilisateur possède un rôle principal parmi :

```text
candidate
employer
partner
admin
```

### BR-ID-002 — Autorité backend

**[MUST]** Toute autorisation sensible est contrôlée côté backend, indépendamment de l'état du frontend.

### BR-ID-003 — Utilisateur inactif

**[MUST]** Un utilisateur désactivé ne peut pas utiliser les fonctions authentifiées normales.

### BR-ID-004 — Email canonique

**[P0][TARGET]** L'identité email est insensible à la casse et aux espaces externes.

Forme canonique :

```text
email_normalized = lower(trim(email))
```

L'unicité doit porter sur la forme canonique.

### BR-ID-005 — Compte léger d'alerte

**[CURRENT]** Une inscription à une alerte peut créer une identité légère sans mot de passe complet.

**[P0][TARGET]** Si la même personne souhaite ensuite créer un compte complet, elle doit pouvoir revendiquer/compléter cette identité au lieu d'être bloquée par « email déjà enregistré ».

### BR-ID-006 — Secrets

**[MUST]** Aucun mot de passe admin ou secret JWT de production ne doit être codé en dur ou créé automatiquement depuis une valeur connue du dépôt.

---

## 3. Entreprises

### BR-COMP-001 — Ownership

**[MUST]** Un recruteur ne peut modifier que les entreprises qu'il possède/gère, sauf privilège admin explicite.

### BR-COMP-002 — Création d'offre

**[MUST]** Un recruteur ne peut publier une offre au nom d'une entreprise qu'il n'est pas autorisé à gérer.

### BR-COMP-003 — Admin

**[MUST]** Un admin peut intervenir selon les fonctions de back-office, mais chaque action sensible doit rester auditable.

---

## 4. Offres d'emploi

### BR-JOB-001 — Types de source

Une offre peut être au minimum :

- offre publiée directement par un recruteur ;
- offre issue d'un partenaire/feed.

Les champs spécifiques à une source ne doivent pas rendre les autres sources invalides.

### BR-JOB-002 — Visibilité

**[P0][TARGET]** Une offre publique est visible seulement si toutes les conditions applicables sont satisfaites.

Exemple de politique :

```text
job actif
AND source active
AND campagne diffusable si partenaire
AND date de validité correcte
AND budget/droit disponible si requis
AND partenaire actif si applicable
```

La décision doit être centralisée.

### BR-JOB-003 — Ownership recruteur

**[MUST]** Un recruteur ne peut modifier, activer/désactiver ou supprimer que ses propres offres, sauf admin.

### BR-JOB-004 — Géolocalisation

**[P0][TARGET]** Toute offre avec une localisation exploitable doit obtenir des coordonnées normalisées lorsque la recherche par rayon en dépend.

Lorsqu'une localisation change, les coordonnées doivent être recalculées.

### BR-JOB-005 — Salaire

**[MUST]** Si `salary_min` et `salary_max` sont tous deux présents, `salary_min <= salary_max`.

### BR-JOB-006 — Suppression

**[TARGET]** Privilégier désactivation/soft-delete lorsqu'une suppression physique casserait l'audit, les candidatures ou les données commerciales. Toute suppression hard doit définir le traitement des références associées.

### BR-JOB-007 — Compteurs

Les compteurs `views_count`, `applications_count` ou équivalents sont des métriques pratiques, mais ne doivent pas être utilisés comme seul système d'audit financier.

---

## 5. Publication Premium / crédits recruteur

### BR-ENT-001 — Définition

**[P0][TARGET]** Un crédit/entitlement de publication représente un droit explicite à consommer, et non un simple nombre affiché dans le profil.

### BR-ENT-002 — Consommation

**[P0][MUST]** Si une publication requiert un crédit :

```text
1 publication réussie = 1 consommation
```

### BR-ENT-003 — Pas de crédit, pas de publication payante

**[P0][MUST]** La règle est vérifiée côté backend. Masquer le bouton frontend ne suffit pas.

### BR-ENT-004 — Échec de publication

**[MUST]** Une publication qui échoue avant création effective ne doit pas faire perdre définitivement un crédit.

### BR-ENT-005 — Concurrence

**[MUST]** Deux requêtes simultanées ne doivent pas consommer le même dernier crédit deux fois.

### BR-ENT-006 — Audit

**[TARGET]** Chaque attribution/consommation doit avoir une source et une trace : achat, admin, promotion, consommation, expiration.

---

## 6. Candidatures

### BR-APP-001 — Candidat authentifié

**[MUST]** Seul un candidat autorisé peut créer une candidature candidate normale.

### BR-APP-002 — Unicité

**[CURRENT][MUST]** Un candidat ne peut pas avoir plusieurs candidatures indépendantes pour la même offre si l'unicité `(job_id, candidate_id)` est la règle active.

### BR-APP-003 — Offre valide

**[MUST]** Une candidature ne doit pas être créée sur une offre introuvable ou non éligible à la candidature selon sa source/état.

### BR-APP-004 — Confidentialité

**[MUST]** Une candidature est visible :

- par son candidat ;
- par le recruteur autorisé de l'offre ;
- par l'admin selon la politique de back-office.

Elle n'est pas publique.

### BR-APP-005 — Statuts

Statuts actuels :

```text
pending
reviewed
accepted
rejected
```

Toute évolution du workflow doit définir les transitions autorisées avant implémentation.

### BR-APP-006 — Side effects

**[TARGET]** Email, analytics ou matching déclenchés par une candidature ne doivent pas compromettre l'enregistrement principal si le service externe est temporairement indisponible.

---

## 7. CV, lettres et documents

### BR-DOC-001 — Propriété

**[MUST]** Chaque document privé possède un propriétaire ou une règle d'accès explicite.

### BR-DOC-002 — Accès candidat

**[MUST]** Un candidat peut accéder à ses propres documents, sous réserve de statut non supprimé.

### BR-DOC-003 — Accès recruteur

**[P0][MUST]** Un recruteur ne peut accéder au CV/document d'un candidat que si une relation métier l'autorise explicitement, par exemple une candidature à l'une de ses offres.

Le simple fait d'être authentifié comme employeur n'est pas suffisant.

### BR-DOC-004 — URL/token

**[TARGET]** Éviter de transporter un JWT long-lived dans une URL. Préférer autorisation backend ou URL signée courte durée selon le cas.

### BR-DOC-005 — Types et taille

Les formats et limites acceptés doivent être validés côté backend, pas uniquement dans l'UI.

### BR-DOC-006 — Modèle unifié

**[P0][TARGET]** Les métadonnées de CV/lettres doivent converger vers un modèle de document cohérent afin d'éviter les divergences entre collections/parcours.

---

## 8. Alertes emploi

### BR-ALERT-001 — Propriétaire

Une alerte appartient à une identité utilisateur, y compris lorsqu'elle provient d'un abonnement léger.

### BR-ALERT-002 — Fréquences

Valeurs actuelles :

```text
instant
daily
weekly
never
```

**[CURRENT]** Le comportement `instant` peut être rapproché d'un traitement quotidien dans l'implémentation actuelle. Ne pas promettre du temps réel sans l'implémenter.

### BR-ALERT-003 — Désactivation

Une alerte inactive ou `never` ne doit pas produire d'envoi automatique.

### BR-ALERT-004 — Idempotence

**[TARGET]** Un même batch ne doit pas envoyer plusieurs fois la même alerte au même utilisateur à cause d'une exécution concurrente du scheduler.

---

## 9. Partenaires

### BR-PART-001 — Modes de facturation

Modes principaux :

```text
per_click
per_posting
```

Chaque campagne/profil doit appliquer le mode configuré de manière cohérente.

### BR-PART-002 — Partenaire inactif

**[MUST]** Un partenaire désactivé ne doit pas continuer à générer de nouvelles dépenses ou diffusion active selon la politique définie.

### BR-PART-003 — Solde

**[MUST]** Une opération facturable ne peut pas rendre le solde incohérent par effet de concurrence.

---

## 10. Campagnes partenaire

### BR-CAMP-001 — Ownership

**[MUST]** Un partenaire ne peut gérer que ses propres campagnes, sauf admin.

### BR-CAMP-002 — États

Les campagnes doivent avoir des états explicites (`active`, `paused`, etc. selon le modèle courant).

### BR-CAMP-003 — Pause

**[P0][MUST]** Une campagne suspendue ne doit plus produire de nouvelle diffusion facturable.

### BR-CAMP-004 — Dates

**[P0][MUST]** Une campagne hors de sa période valide ne doit pas être considérée comme diffusable.

### BR-CAMP-005 — Budget

**[P0][MUST]** Une limite budgétaire atteinte doit empêcher les nouveaux événements facturables correspondants.

### BR-CAMP-006 — Politique centrale

**[P0][TARGET]** Les règles de campagne et de visibilité d'offre sont évaluées dans un service/policy commun, pas recodées par endpoint.

---

## 11. CPC, clics et impressions

### BR-CPC-001 — Clic brut vs facturable

**[P0][TARGET]** Distinguer :

- événement de clic observé ;
- clic qualifié/facturable.

### BR-CPC-002 — Débit atomique

**[P0][MUST]** Le contrôle du solde/budget et le débit d'un clic doivent être atomiques ou transactionnels selon la stratégie retenue.

### BR-CPC-003 — Idempotence

**[TARGET]** Un même événement utilisateur ne doit pas pouvoir être facturé plusieurs fois uniquement parce qu'une requête a été rejouée.

### BR-CPC-004 — Antifraude

**[P0][TARGET]** Prévoir au minimum des garde-fous contre les rafales de clics manifestement automatisées avant de considérer le CPC comme comptabilité de production robuste.

### BR-CPC-005 — Audit

**[TARGET]** Chaque débit facturable doit pouvoir être relié à un événement et à une campagne.

---

## 12. Imports XML

### BR-FEED-001 — Upsert

Une annonce importée existante est mise à jour selon son identité externe stable ; une nouvelle annonce est créée.

### BR-FEED-002 — Identité

**[P0][TARGET]** L'identité d'une annonce partenaire doit inclure assez de contexte pour éviter les collisions entre campagnes d'un même partenaire.

### BR-FEED-003 — Annonce disparue

**[P0][TARGET]** Après un import complet réussi, une annonce précédemment active mais absente du feed peut être désactivée selon la politique définie.

### BR-FEED-004 — Feed en erreur

**[MUST]** Une panne, timeout ou XML invalide ne doit pas être interprété comme « le partenaire a supprimé toutes ses annonces ».

### BR-FEED-005 — Traçabilité

**[TARGET]** Chaque exécution d'import doit avoir un identifiant, un statut, un début/fin, des compteurs et une erreur éventuelle.

---

## 13. Paiements Stripe

### BR-PAY-001 — Source de vérité

**[MUST]** Un retour navigateur « success » ne suffit pas pour créditer définitivement un compte. Le statut doit être confirmé par le fournisseur/flow sécurisé prévu.

### BR-PAY-002 — Idempotence

**[P0][MUST]** Une même session/transaction Stripe ne peut créditer qu'une fois, même si le webhook est rejoué.

### BR-PAY-003 — Crash safety

**[P0][TARGET]** Une panne entre « paiement validé » et « crédit appliqué » doit être récupérable sans perte ni double crédit.

### BR-PAY-004 — Ledger

**[TARGET]** Tout crédit/débit commercial doit produire un mouvement auditable dans un ledger.

### BR-PAY-005 — Montants

**[TARGET]** Stocker les nouveaux montants comptables en unités mineures entières (centimes) ou type décimal contrôlé plutôt qu'en float.

---

## 14. Messagerie

### BR-MSG-001 — Participants

**[MUST]** Seuls les participants autorisés d'une conversation peuvent lire et écrire ses messages, sauf permission admin explicitement définie.

### BR-MSG-002 — Confidentialité

Le contenu des messages n'est pas public et ne doit pas apparaître dans les logs applicatifs ordinaires.

### BR-MSG-003 — Pagination

**[TARGET]** Les messages sont paginés/incrémentaux ; ne pas charger indéfiniment tout l'historique pour chaque rafraîchissement.

### BR-MSG-004 — Conversation explicite

**[TARGET]** Une conversation devient une entité de premier ordre avec participants, dernier message et unread counts.

---

## 15. Matching et IA

### BR-AI-001 — Assistance, pas autorité finale

**[MUST]** Un score IA est une aide à la décision et ne constitue pas seul une décision irréversible d'embauche/rejet.

### BR-AI-002 — Explication

**[TARGET]** Un score important doit pouvoir être accompagné d'une justification compréhensible basée sur des données pertinentes.

### BR-AI-003 — Audit

**[TARGET]** Conserver au minimum version modèle/algorithme, timestamp et résultat structuré pour les fonctions sensibles ou coûteuses.

### BR-AI-004 — Données personnelles

**[MUST]** Envoyer au fournisseur IA uniquement les données nécessaires à la finalité, sans secret ni identifiant inutile.

### BR-AI-005 — Prompt injection

**[MUST]** Le contenu d'une offre, d'un CV ou d'un message est une donnée non fiable et ne peut pas remplacer les instructions du système.

### BR-AI-006 — Fallback

Une indisponibilité IA ne doit pas rendre inutilisable une fonction de base lorsque celle-ci peut fonctionner sans IA.

---

## 16. Analytics

### BR-AN-001 — Événement explicite

**[TARGET]** Les métriques importantes doivent provenir d'événements définis, pas uniquement de compteurs ambigus.

### BR-AN-002 — Pas de facturation sur métrique approximative

**[MUST]** Une métrique purement analytique ou tronquée ne doit pas être utilisée comme seule preuve d'une facture.

### BR-AN-003 — Pas de troncature silencieuse

**[TARGET]** Un dashboard ne doit pas présenter comme total exhaustif un calcul basé sur une limite arbitraire de documents sans l'indiquer.

---

## 17. Administration

### BR-ADMIN-001 — Permission

**[MUST]** Toutes les routes admin vérifient `admin` côté backend.

### BR-ADMIN-002 — Audit

**[TARGET]** Toute action admin financière, de suppression ou de modification de statut critique doit enregistrer : acteur, action, cible, date et motif/métadonnées utiles.

### BR-ADMIN-003 — Données de production

Un outil admin ne doit pas exposer de secret, hash de mot de passe ou token utilisable.

---

## 18. Suppression, confidentialité et rétention

### BR-DATA-001 — Suppression logique vs physique

Avant toute suppression, distinguer :

- désactivation ;
- soft delete ;
- anonymisation ;
- purge ;
- conservation nécessaire pour audit financier.

### BR-DATA-002 — Références

**[MUST]** Une suppression ne doit pas laisser silencieusement des références critiques incohérentes.

### BR-DATA-003 — Minimisation

Ne conserver et ne transmettre que les données nécessaires à la finalité métier définie.

---

## 19. Scheduler et jobs de fond

### BR-SCHED-001 — Multi-instance

**[TARGET]** Une tâche périodique ne doit pas être exécutée plusieurs fois parce que plusieurs instances FastAPI sont lancées.

### BR-SCHED-002 — Idempotence

**[MUST]** Une relance d'une tâche doit être sûre ou détecter ce qui a déjà été traité.

### BR-SCHED-003 — Observabilité

**[TARGET]** Chaque job périodique important expose statut, durée, résultat et erreur.

---

## 20. Règle de livraison

### BR-REL-001

**[MUST]** Une évolution financière, permission, migration ou suppression n'est pas considérée terminée sans tests des cas limites correspondants.

### BR-REL-002

**[MUST]** Les tests de développement/staging n'utilisent jamais la base de production ni les vraies clés de paiement pour des scénarios destructifs.

### BR-REL-003

**[TARGET]** Les grosses fonctionnalités sont activables via feature flag et déployables progressivement.
