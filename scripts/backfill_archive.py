#!/usr/bin/env python3
"""Rattrapage unique (roadmap v2, phase 0) : reconstruit data/archive/ à
partir de l'historique git de data/listings.json.

Avant la phase 0, `purger()` supprimait les offres fermées depuis > 45 j.
Elles ne sont plus dans le store, mais chaque version du store est dans git :
on rejoue l'historique et on archive toute offre qui a été vue FERMÉE
(closed_at renseigné) puis a disparu du store courant.

Deux exclusions, pour ne pas polluer l'analyseur :
  - les offres de démonstration du premier commit (8f402e0), jamais revues
    par un vrai run : URL générique, pas de date de publication ;
  - les offres disparues sans jamais avoir été fermées :
ce sont les ~18 800 lignes du run d'export du 2026-08-05, annulé par
e8440db (« restaurer le store d'avant le run d'export »). Elles n'ont pas
de cycle de vie réel et fausseraient l'analyseur.

Idempotent (ecrire_archive saute les (id, closed_at) déjà présents) :
on peut le relancer sans risque.

    python scripts/backfill_archive.py            # écrit dans data/archive/
    python scripts/backfill_archive.py --dry-run  # affiche seulement le bilan
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

from alternance_engine import store as store_mod  # noqa: E402

STORE = "data/listings.json"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=RACINE, text=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    commits = _git("log", "--reverse", "--format=%H", "--", STORE).split()
    dernier_etat: dict[str, dict] = {}
    vues_apres_le_premier: set[str] = set()
    for i, sha in enumerate(commits):
        try:
            version = json.loads(_git("show", f"{sha}:{STORE}"))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        if isinstance(version, dict):
            dernier_etat.update(version)
            if i > 0:
                vues_apres_le_premier.update(
                    oid for oid, r in version.items() if r.get("active", True)
                )
    # Démo du premier commit : présentes au départ, jamais revues actives ensuite.
    demo = set(json.loads(_git("show", f"{commits[0]}:{STORE}"))) - vues_apres_le_premier

    courant = store_mod.load(str(RACINE / STORE))
    a_archiver = [
        {k: v for k, v in r.items() if k != "active"}
        for oid, r in dernier_etat.items()
        if oid not in courant and oid not in demo and r.get("closed_at") and r.get("first_seen")
    ]
    ignorees = sum(
        1 for oid, r in dernier_etat.items() if oid not in courant and not r.get("closed_at")
    )

    print(f"{len(commits)} versions du store relues, {len(dernier_etat)} offres vues au total")
    print(f"{len(a_archiver)} offres purgées à archiver")
    print(f"{len(demo)} offres de démonstration du premier commit ignorées")
    print(f"{ignorees} offres disparues sans closed_at ignorées (run d'export annulé)")
    if args.dry_run:
        return 0
    n = store_mod.ecrire_archive(a_archiver, str(RACINE / store_mod.ARCHIVE_DIR))
    print(f"[OK] {n} lignes ajoutées dans {store_mod.ARCHIVE_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
