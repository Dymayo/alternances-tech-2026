# Architecture

Ce repo applique une synthèse de l'étude de trois projets similaires
(SimplifyJobs/Summer2026-Internships, LorenzoLaCorte/european-tech-internships,
zshah101/intern_engine). Chaque décision ci-dessous est traçable à un
enseignement de cette étude.

## Flux de données

```
API La bonne alternance ──┐
                          ├─ pipeline.py ─ categorize ─ dedupe ─▶ data/listings.json ─▶ render ─▶ README.md
Issues communautaires ────┘   (async, échecs isolés)              (store, cycle de vie)            README-Inactive.md
```

## Décisions et leurs raisons

- **Un connecteur = un fichier, un modèle `Offre` normalisé unique**
  (de intern_engine). Ajouter une source ne touche que son connecteur.
  Contrairement à intern_engine et ses 12 scrapers ATS, une seule API
  officielle suffit : La bonne alternance agrège déjà France Travail et
  les jobboards partenaires.
- **Store JSON lisible, indexé par id, trié à l'écriture** (de intern_engine,
  justification incluse) : commité par Actions, donc les diffs de PR sont
  lisibles. Cycle de vie complet : `first_seen`, `active`, `closed_at`,
  péremption des offres communautaires, purge de rétention — le fichier ne
  peut pas devenir le monolithe de 11 Mo de SimplifyJobs.
- **Un échec de fetch ne ferme jamais d'offres** : seules les sources dont le
  run a réussi peuvent déclencher des fermetures (`sources_reussies`).
- **README généré par injection dans un template à marqueurs**
  (d'european-tech-internships), avec **garde-fou de la limite GitHub de
  512 Kio** (de SimplifyJobs) : au-delà, le surplus le plus ancien bascule
  dans `README-Inactive.md`.
- **Contributions par issue forms, pas par PR** (de SimplifyJobs) : le README
  étant généré, une PR humaine serait toujours en conflit. Le label
  `contribution-approuvee` déclenche l'injection automatique.
- **Le cron quotidien ouvre une PR au lieu de pusher sur main**
  (d'european-tech-internships) : relecture avant publication, et merge en
  squash pour garder un historique lisible (l'anti-50 000 commits).
- **Zéro dépendance runtime hors `httpx`**, CLI argparse : rien à maintenir.
