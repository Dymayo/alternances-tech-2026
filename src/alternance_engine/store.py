"""État persistant des offres — un seul fichier JSON lisible par un humain.

Pourquoi JSON et pas SQLite (décision documentée, cf. analyse d'intern_engine) :
le fichier est commité dans le repo par GitHub Actions, donc un format texte
donne des diffs propres en PR ("3 offres ajoutées, 1 fermée") et zéro problème
de persistance binaire. Le store est un dict indexé par id d'offre, trié à
l'écriture pour des diffs stables.

Cycle de vie géré ici :
  - first_seen : la date où NOUS avons vu l'offre pour la première fois
    (alimente le badge 🆕 et le tri du README) ;
  - active / closed_at : une offre absente d'un run RÉUSSI de sa source est
    marquée fermée ; les offres communautaires expirent par ancienneté
    (seuil STALE_COMMUNAUTE_JOURS, comme le mark_stale de SimplifyJobs) ;
  - rétention : les offres fermées depuis longtemps quittent le store pour
    que le fichier ne grossisse jamais indéfiniment (l'anti-11-Mo)... mais
    elles ne sont plus jamais supprimées : elles sont DÉPLACÉES dans
    data/archive/AAAA-MM.jsonl (mois de closed_at). L'analyseur de
    calendrier de recrutement (roadmap v2, phase 5) a besoin de cet
    historique ; une offre purgée était une donnée perdue pour toujours.

Pourquoi un fichier JSONL par mois et pas un archive.json unique :
  - pas de monolithe (l'anti-pattern SimplifyJobs, cette fois côté archive) ;
  - un mois clos n'est plus jamais réécrit, donc les diffs quotidiens ne
    touchent que le fichier du mois courant ;
  - JSONL = ajout en fin de fichier, une ligne par offre, diff ligne à ligne.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from .models import Offre

STALE_COMMUNAUTE_JOURS = 60   # offre communautaire sans confirmation → fermée
RETENTION_FERMEES_JOURS = 45  # offre fermée depuis > 45 j → déplacée dans l'archive
# (pendant ces 45 j elle reste dans le store et alimente README-Inactive.md)

ARCHIVE_DIR = "data/archive"

# Sources gérées par pipeline : l'absence dans un run réussi signifie "fermée".
# Les autres sources (communaute) vivent selon leur ancienneté.
SOURCES_PIPELINE = {"lba"}


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(data.items())), f, ensure_ascii=False, indent=2)
        f.write("\n")


def merge(
    store: dict,
    offres: list[Offre],
    sources_reussies: set[str],
    now: str | None = None,
) -> dict:
    """Fusionne le résultat d'un run dans le store. Retourne les compteurs
    {"nouvelles": n, "fermees": n, "reactivees": n} pour le message de PR.

    `sources_reussies` : seules les sources dont le fetch a réussi peuvent
    faire fermer des offres — un échec réseau ne doit jamais fermer quoi
    que ce soit (isolation des pannes).
    """
    now = now or now_iso()
    vus = {o.id for o in offres}
    stats = {"nouvelles": 0, "fermees": 0, "reactivees": 0}

    for offre in offres:
        record = offre.to_store()
        existant = store.get(offre.id)
        if existant is None:
            record["first_seen"] = now
            record["active"] = True
            record["closed_at"] = None
            stats["nouvelles"] += 1
        else:
            record["first_seen"] = existant.get("first_seen", now)
            record["closed_at"] = None
            if not existant.get("active", True):
                stats["reactivees"] += 1
            record["active"] = True
        store[offre.id] = record

    # Fermetures : offres pipeline non revues dans un run réussi de leur source.
    for oid, record in store.items():
        if not record.get("active", True):
            continue
        source = record.get("source", "")
        if source in SOURCES_PIPELINE and source in sources_reussies and oid not in vus:
            record["active"] = False
            record["closed_at"] = now
            stats["fermees"] += 1

    return stats


def marquer_perimees(store: dict, now: str | None = None) -> int:
    """Ferme les offres communautaires trop anciennes (pattern SimplifyJobs)."""
    now_dt = _parse_iso(now or now_iso())
    n = 0
    for record in store.values():
        if not record.get("active", True):
            continue
        if record.get("source") in SOURCES_PIPELINE:
            continue
        age = now_dt - _parse_iso(record.get("first_seen", now_iso()))
        if age > timedelta(days=STALE_COMMUNAUTE_JOURS):
            record["active"] = False
            record["closed_at"] = now or now_iso()
            n += 1
    return n


def _fichier_archive(archive_dir: str, closed_at: str) -> str:
    """data/archive/AAAA-MM.jsonl — le mois de FERMETURE, pas de publication :
    un mois clos n'est alors plus jamais modifié."""
    return os.path.join(archive_dir, f"{closed_at[:7]}.jsonl")


def _cle_archive(record: dict) -> tuple[str, str]:
    """Une même offre peut être archivée plusieurs fois si elle réapparaît
    puis refait une fermeture : chaque (id, closed_at) est un épisode distinct."""
    return (record["id"], record["closed_at"])


def lire_archive(archive_dir: str = ARCHIVE_DIR) -> Iterator[dict]:
    """Itère sur toutes les lignes archivées, mois par mois (ordre chronologique)."""
    if not os.path.isdir(archive_dir):
        return
    for nom in sorted(os.listdir(archive_dir)):
        if not nom.endswith(".jsonl"):
            continue
        with open(os.path.join(archive_dir, nom), encoding="utf-8") as f:
            for ligne in f:
                if ligne.strip():
                    yield json.loads(ligne)


def ecrire_archive(records: list[dict], archive_dir: str = ARCHIVE_DIR) -> int:
    """Ajoute des enregistrements fermés à leur fichier mensuel. Idempotent :
    un (id, closed_at) déjà présent n'est pas réécrit — si un run plante
    entre l'écriture de l'archive et celle du store, le run suivant ne crée
    pas de doublon. Retourne le nombre de lignes réellement ajoutées."""
    par_fichier: dict[str, list[dict]] = {}
    for r in records:
        par_fichier.setdefault(_fichier_archive(archive_dir, r["closed_at"]), []).append(r)

    ajoutees = 0
    os.makedirs(archive_dir, exist_ok=True)
    for chemin, lot in par_fichier.items():
        deja = set()
        if os.path.exists(chemin):
            with open(chemin, encoding="utf-8") as f:
                deja = {_cle_archive(json.loads(l)) for l in f if l.strip()}
        nouveaux = sorted(
            (r for r in lot if _cle_archive(r) not in deja),
            key=lambda r: (r["closed_at"], r["id"]),
        )
        if not nouveaux:
            continue
        with open(chemin, "a", encoding="utf-8") as f:
            for r in nouveaux:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        ajoutees += len(nouveaux)
    return ajoutees


def archiver(
    store: dict, archive_dir: str = ARCHIVE_DIR, now: str | None = None
) -> int:
    """Déplace (jamais ne supprime) les offres fermées depuis plus de
    RETENTION_FERMEES_JOURS vers data/archive/AAAA-MM.jsonl.

    Remplace l'ancien `purger()`. L'archive est écrite AVANT le retrait du
    store : en cas d'échec, l'offre reste dans le store et sera archivée au
    run suivant — le pire cas est un report, jamais une perte.

    Chaque ligne garde tout l'enregistrement du store (first_seen, closed_at,
    source, contrat, categorie, ville, date_publication...) moins `active`,
    toujours faux ici."""
    now_dt = _parse_iso(now or now_iso())
    a_archiver = [
        oid
        for oid, r in store.items()
        if not r.get("active", True)
        and r.get("closed_at")
        and now_dt - _parse_iso(r["closed_at"]) > timedelta(days=RETENTION_FERMEES_JOURS)
    ]
    if not a_archiver:
        return 0
    lignes = [{k: v for k, v in store[oid].items() if k != "active"} for oid in a_archiver]
    ecrire_archive(lignes, archive_dir)
    for oid in a_archiver:
        del store[oid]
    return len(a_archiver)


CHAMPS_ARCHIVE_OBLIGATOIRES = ("id", "source", "entreprise", "intitule", "first_seen", "closed_at")


def valider_archive(archive_dir: str = ARCHIVE_DIR) -> list[str]:
    """Erreurs d'intégrité de l'archive (CI) : JSON valide, champs de cycle
    de vie présents, ligne rangée dans le bon mois, pas de doublon."""
    erreurs: list[str] = []
    if not os.path.isdir(archive_dir):
        return erreurs
    vus: set[tuple[str, str]] = set()
    for nom in sorted(os.listdir(archive_dir)):
        if not nom.endswith(".jsonl"):
            continue
        with open(os.path.join(archive_dir, nom), encoding="utf-8") as f:
            for n, ligne in enumerate(f, 1):
                if not ligne.strip():
                    continue
                ou = f"archive/{nom}:{n}"
                try:
                    r = json.loads(ligne)
                except json.JSONDecodeError:
                    erreurs.append(f"{ou} : JSON invalide")
                    continue
                manquants = [c for c in CHAMPS_ARCHIVE_OBLIGATOIRES if not r.get(c)]
                if manquants:
                    erreurs.append(f"{ou} : champ(s) vide(s) {', '.join(manquants)}")
                    continue
                if f"{r['closed_at'][:7]}.jsonl" != nom:
                    erreurs.append(f"{ou} : closed_at {r['closed_at']} hors du mois du fichier")
                cle = _cle_archive(r)
                if cle in vus:
                    erreurs.append(f"{ou} : doublon {cle[0]} fermée le {cle[1]}")
                vus.add(cle)
    return erreurs
