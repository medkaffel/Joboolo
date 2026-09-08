# Recette préproduction — lot de sécurité 1

Statut : préparation locale, aucun déploiement ni test externe exécuté.

## Conditions avant démarrage

- Confirmer les URL HTTPS frontend/backend et la plateforme de recette.
- MongoDB dédié en replica set ; MONGO_URL et DB_NAME explicites, sans données de production.
- Préparer la migration scripts/migrate_p0007_identity_indexes.py exclusivement sur cette base ; vérifier index p0007_identity_unique et marqueur p0007_identity_indexes avant import.
- APP_ENV=test ; SECRET_KEY propre à la recette, injecté hors Git.
- CORS_ALLOWED_ORIGINS : origine frontend exacte, sans slash final. Une valeur vide refuse le cross-origin. Ce changement exige une configuration avant tout déploiement.
- SCHEDULER_ENABLED=false pour la recette initiale ; un seul processus si activation ultérieure. Fuseau explicite UTC.
- REACT_APP_BACKEND_URL au build frontend : URL backend sans /api.
- FRONTEND_URL et APP_PUBLIC_URL vers la recette ; router /api/alerts/track sur le domaine frontend vers le backend.
- ADMIN_EMAIL, SENDER_EMAIL : boîtes de test contrôlées.
- R2 : bucket préproduction privé et dédié ; renseigner S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_BUCKET_NAME et S3_REGION=auto hors Git. Le préfixe de stockage reste joboolo. EMERGENT_LLM_KEY reste réservé à l'IA et n'est plus utilisé par le stockage.
- Resend : destinataires contrôlés exclusivement ; sans RESEND_API_KEY, aucune livraison validable.
- Stripe : clés de test exclusivement, webhook distinct /api/stripe/webhook, aucun paiement réel.
- Google via Emergent : URL de retour autorisée et compte dédié sans données personnelles de production.
- Aucun import de server.py pour un simple contrôle : son démarrage écrit des index/contenus et initialise des services.

## Protection GitHub à appliquer

main : PR obligatoire ; checks Backend hermetic, Backend Mongo integration, Frontend build obligatoires ; branche à jour ; aucun contournement administrateur ; aucun force-push ni suppression ; conversations résolues. Ne pas imposer une deuxième approbation sans relecteur disponible.

Protection appliquée et active : https://github.com/medkaffel/Joboolo/settings/rules/22405602. Cible exacte main, aucun bypass, zéro approbation humaine imposée ; les trois checks proviennent de GitHub Actions.

## Jeu de données

Deux candidats C1/C2, deux recruteurs R1/R2 et entreprises E1/E2, administrateur A1 créé par le script dédié, partenaire P1 approuvé. CV PDF/DOC/DOCX fictifs, flux XML contrôlé avec deux références stables. Boîtes de test contrôlées pour les emails. Aucune copie de production.

## Exécution et critères

Pour chaque ligne consigner requête, identité, réponse HTTP, état avant/après, attendu/obtenu. Masquer tokens et secrets dans les preuves.

| ID | Action | Attendu |
|---|---|---|
| 01 | Inscrire C1 comme candidate, C2 sans rôle | Candidats, aucune élévation |
| 02 | Inscrire R1/R2 comme employer | Recruteurs |
| 03 | Inscrire admin/partner/inconnu via inscription publique ; injecter admin dans profil | Refus ou champ ignoré, jamais de promotion |
| 04 | Connexion correcte, incorrecte, token expiré, compte inactif | Accès seulement valide et actif |
| 05 | R1 crée E1 et offre standard ; R2 tente modification/publication E1 | Offre visible, accès étranger refusé |
| 06 | Upload PDF/DOC/DOCX, format interdit, >10 Mio | Documents privés au bon propriétaire ; invalides refusés |
| 07 | C1 postule avec son CV puis répète ; candidature sans CV distincte | Pas de doublon ni double compteur ; sans CV accepté |
| 08 | CV étranger, supprimé, inconnu, public, lettre de bibliothèque | Refus sans candidature ni incrément |
| 09 | CV lu par propriétaire, recruteur lié, autre candidat/recruteur, visiteur, A1 ; route publique | Propriétaire/recruteur lié/admin autorisés ; autres refusés |
| 10 | Même CV joint chez R1 et R2 ; second CV non joint | Deux recruteurs autorisés pour le premier uniquement |
| 11 | Messages C1/R1 après candidature ; sans relation ; job_id étranger | Relation valide uniquement |
| 12 | Retirer candidature/offre ou transférer offre dans fixtures ; désactiver destinataire, conserver ancien message | Envoi/fil refusés ; liste et compteur filtrés |
| 13 | Fermer offre tout en conservant candidature | Messagerie toujours autorisée selon règle actuelle |
| 14 | Import XML valide puis réimport et modification même référence | Pas de doublon, mise à jour stable |
| 15 | URL localhost/privée/IPv6 loopback/métadonnées, schéma interdit, redirection privée | Refus avant connexion interdite, vérifier traces isolées |
| 16 | XML malformé, >20 Mio, >5 redirections, serveur indisponible | Erreur maîtrisée, pas de secret exposé |
| 17 | Routes admin avec visiteur/C1/R1/P1 puis A1 | A1 uniquement |
| 18 | Google dédié, email contrôlé, Stripe test + rejeu webhook, IA fictive | Pas de promotion, livraison vérifiée, pas de double crédit, réponse IA vérifiée |
| 19 | Navigateur : origine autorisée/étrangère, liens email, CV | CORS exact ; aucune URL de production |
| 20 | Activer scheduler explicitement dans environnement isolé, un processus | Alertes/flux contrôlés ; aucune destination réelle |

## Limites et décision

Un health check positif ne prouve pas la disponibilité des dépendances. Sans configuration externe, les tests 06–10 (stockage) et 18 ne sont pas validés. Ne jamais perturber un service partagé pour simuler une panne.

Le scheduler existant marque last_sent_at même si Resend retourne un échec ; ce défaut n'est pas corrigé dans le présent lot de configuration. Plusieurs processus peuvent dupliquer les tâches. Les erreurs brutes de stockage restent à examiner pendant la recette.

Sortie de recette : tous les cas de sécurité réussis, aucun effet hors environnement isolé, anomalies restantes documentées. Décision distincte requise avant tout déploiement en production.
