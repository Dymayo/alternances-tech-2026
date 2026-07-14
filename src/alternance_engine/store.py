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
  - rétention : les offres fermées depuis longtemps sont purgées pour que
    le fichier ne grossisse jamais indéfiniment (l'anti-11-Mo).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

from .models import Offre

STALE_COMMUNAUTE_JOURS = 60   # offre communautaire sans confirmation → fermée
RETENTION_FERMEES_JOURS = 45  # offre fermée depuis > 45 j → purgée du fichier

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


def purger(store: dict, now: str | None = None) -> int:
    """Supprime les offres fermées depuis plus de RETENTION_FERMEES_JOURS."""
    now_dt = _parse_iso(now or now_iso())
    a_purger = [
        oid
        for oid, r in store.items()
        if not r.get("active", True)
        and r.get("closed_at")
        and now_dt - _parse_iso(r["closed_at"]) > timedelta(days=RETENTION_FERMEES_JOURS)
    ]
    for oid in a_purger:
        del store[oid]
    return len(a_purger)
