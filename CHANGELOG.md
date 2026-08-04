# Changelog

Toutes les modifications notables de ce projet sont documentées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

## [1.1.0] — 2026-08-04

### Changé
- **Le connecteur La bonne alternance utilise désormais la route d'export
  en masse `/job/v1/export` au lieu de la route de recherche.** La route
  de recherche est plafonnée à 150 résultats par source et sans
  pagination : sa documentation indique explicitement qu'il n'est pas
  possible de récupérer toutes les offres correspondant aux critères.
  L'export expose la totalité des offres actives en un seul appel, ce qui
  rend la liste réellement exhaustive.
- Le filtrage par code ROME passe côté client (l'export n'est pas
  filtrable côté serveur). `config.json` est inchangé dans sa forme.
- Le cron quotidien est documenté comme passant après 3h heure de Paris,
  moment où l'export est régénéré côté LBA.

### Ajouté
- Parsing incrémental du fichier d'export avec `ijson` : mémoire bornée
  quel que soit le volume (mesuré sur export synthétique : 60 000 offres
  parsées en 2-3 s, pic mémoire de l'ordre de 80-110 Mo selon la taille
  des enregistrements, objets résidents inclus).
- Téléchargement en streaming vers un fichier temporaire, démarré
  immédiatement après l'obtention du lien S3 signé (valable 2 minutes).
- Mode hors-ligne `LBA_EXPORT_FILE` pour développer et tester le
  connecteur sans jeton ni réseau.
- Filtrage défensif sur `offer.status` (seules les offres actives).
- 9 tests supplémentaires sur le connecteur, avec un jeu de données
  reproduisant le format v3 réel (25 tests au total).
- Dépendance `ijson>=3.2`.

### Corrigé
- Les chemins de champs du connecteur, désormais alignés sur le schéma
  officiel vérifié dans le code source de l'API : `contract.type` est une
  liste de valeurs capitalisées, `contract.remote` vaut
  `onsite`/`remote`/`hybrid`, et `workplace.location.address` est une
  adresse postale complète dont la commune est extraite pour l'affichage.

## [1.0.0] — 2026-07-14

Première version publique.

### Ajouté
- Connecteur API La bonne alternance (`src/alternance_engine/connectors/la_bonne_alternance.py`).
- Modèle `Offre` normalisé avec clé de déduplication inter-sources.
- Store JSON avec cycle de vie complet : `first_seen`, fermeture automatique
  des offres absentes d'un run réussi, péremption des offres communautaires
  à 60 jours, purge de rétention à 45 jours après fermeture.
- Isolation des pannes réseau : un connecteur en échec ne ferme jamais
  d'offres.
- Déduplication inter-sources par (entreprise, intitulé, ville) normalisés,
  priorité aux offres vérifiées par la communauté.
- Catégorisation par mots-clés (6 catégories : Développement, Data & IA,
  Cybersécurité, Réseaux/Cloud/Infra, Embarqué & Électronique, Produit/Support).
- Colonne « Ajoutée » et badge 🆕 basés sur la date de publication de
  l'offre côté source (`date_publication`), avec repli sur `first_seen`
  quand la source ne la fournit pas.
- Génération du README par injection dans un template à marqueurs, avec
  garde-fou automatique de la limite d'affichage GitHub (512 Kio) et
  archivage du surplus dans `README-Inactive.md`.
- Contributions communautaires via issue forms (`ajouter_offre.yml`,
  `signaler_offre.yml`), traitement automatique au label
  `contribution-approuvee`.
- Workflows GitHub Actions : mise à jour quotidienne (ouvre une PR),
  validation CI sur chaque PR, traitement des contributions.
- CLI (`main.py`) : `update`, `render`, `validate`, `contribution`.
- Suite de tests (16 tests) couvrant le cycle de vie du store, la dédup,
  la catégorisation, le rendu et le parsing des issue forms.

### Configuration requise pour le premier déploiement
- Secret GitHub `LBA_API_KEY` (jeton gratuit sur api.apprentissage.beta.gouv.fr).
- Autoriser les Actions à créer des Pull Requests (Settings → Actions → General).
- Vérifier le schéma de réponse de l'API contre `_vers_offre()` au premier run réel.
