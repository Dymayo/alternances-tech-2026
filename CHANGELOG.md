# Changelog

## [Non publié]

### Ajouté
- `data/archive/AAAA-MM.jsonl` : les offres fermées depuis plus de 45 jours
  sont archivées au lieu d'être supprimées (roadmap v2, phase 0).
- `scripts/backfill_archive.py` : reconstruit l'archive depuis l'historique
  git ; 164 offres purgées depuis juillet 2026 récupérées.
- `python main.py validate` vérifie aussi l'archive (JSON, champs de cycle
  de vie, mois du fichier, doublons).
- 6 tests sur l'archivage (22 au total).

### Modifié
- `store.purger()` remplacé par `store.archiver()` ; la statistique de run
  `purgees` devient `archivees`.
- Le workflow quotidien commite `data/archive/*.jsonl` avec le store.
