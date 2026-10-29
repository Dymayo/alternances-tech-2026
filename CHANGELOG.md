# Changelog

Toutes les modifications notables de ce projet sont documentées ici.
Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

## [1.1.0] — non publié

### Changé
- **Le connecteur La bonne alternance utilise la route d'export en masse
  `/job/v1/export` au lieu de la route de recherche**, plafonnée à 150
  résultats par requête et sans pagination. Reprend le connecteur du
  2026-08-04 (annulé le lendemain) en corrigeant les causes de l'annulation :
  - les « recruteurs_lba » (entreprises sans offre, 98,8 % du run annulé)
    sont écartés sur `identifier.partner_label` ;
  - `config.json` passe des 6 anciens codes ROME aux 79 codes ROME v4
    (tous les métiers « enfants » de ces 6 codes, plus data scientist,
    data analyst et ingénieur télécoms) : les offres portent le code
    précis, ce qui limitait la recherche comme l'export à ~65 offres ;
  - `ville` garde l'adresse brute, comme la route de recherche : les ids
    des offres déjà en store sont inchangés (le run annulé les avait
    toutes fermées puis recréées).
- Le rendu du README trouve par dichotomie le nombre d'offres qui tient
  sous la limite GitHub (l'ancienne boucle était quadratique : sans fin à
  6 000 offres). Dans README-Inactive.md, les offres encore ouvertes
  déplacées faute de place ont leur propre section, et la liste des offres
  fermées est plafonnée (l'historique complet est dans `data/archive/`).
- `store.purger()` remplacé par `store.archiver()` ; la statistique de run
  `purgees` devient `archivees`.

### Ajouté
- `data/archive/AAAA-MM.jsonl` : les offres fermées depuis plus de 45 jours
  sont archivées au lieu d'être supprimées (roadmap v2, phase 0).
- `scripts/backfill_archive.py` : reconstruit l'archive depuis l'historique
  git ; 164 offres purgées depuis juillet 2026 récupérées.
- `python main.py validate` vérifie aussi l'archive.
- Parsing incrémental de l'export avec `ijson` (mémoire bornée), lien S3
  signé (valable 2 minutes) téléchargé en streaming.
- Mode hors-ligne `LBA_EXPORT_FILE` pour développer sans jeton.
- Garde-fou : un export non vide dont aucune offre n'est retenue fait
  échouer la source au lieu de fermer toutes les offres.
- `date_debut` (`contract.start`) lue depuis l'export.
- Le workflow quotidien commite `data/archive/*.jsonl`.
- Tests : 34 au total (archive, connecteur d'export, recruteurs, codes
  ROME v4, stabilité des ids).
- Dépendance `ijson>=3.2`.

## [1.0.0] — 2026-07-14

Première version publique.
