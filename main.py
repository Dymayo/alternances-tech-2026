#!/usr/bin/env python3
"""CLI du repo — quatre commandes, appelées par les workflows GitHub Actions.

  python main.py update        # interroge les sources et met à jour data/listings.json
  python main.py render        # régénère README.md et README-Inactive.md depuis le store
  python main.py validate      # vérifie l'intégrité du store (CI sur chaque PR)
  python main.py contribution <event.json>  # injecte une offre depuis une issue approuvée

argparse plutôt qu'un framework CLI : zéro dépendance runtime hors httpx.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

STORE_PATH = "data/listings.json"
TEMPLATE_PATH = "templates/README.template.md"


def cmd_update(_args) -> int:
    import asyncio

    from alternance_engine.pipeline import run_update

    asyncio.run(run_update(store_path=STORE_PATH))
    return 0


def cmd_render(_args) -> int:
    from alternance_engine import store as store_mod
    from alternance_engine.render import render

    data = store_mod.load(STORE_PATH)
    template = Path(TEMPLATE_PATH).read_text(encoding="utf-8")
    readme, inactive = render(data, template)
    Path("README.md").write_text(readme, encoding="utf-8")
    Path("README-Inactive.md").write_text(inactive, encoding="utf-8")
    actives = sum(1 for r in data.values() if r.get("active", True))
    print(f"[OK] README généré : {actives} offres actives, {len(data) - actives} archivées")
    return 0


def cmd_validate(_args) -> int:
    """Valide le store : ids cohérents, champs obligatoires, valeurs permises.

    Pattern SimplifyJobs (validate_listings) : un JSON cassé ne doit jamais
    atteindre la branche principale ni casser la génération du README.
    """
    from alternance_engine import store as store_mod
    from alternance_engine.models import CONTRATS_VALIDES

    data = store_mod.load(STORE_PATH)
    erreurs: list[str] = []
    for oid, record in data.items():
        if record.get("id") != oid:
            erreurs.append(f"{oid} : clé et champ id incohérents")
        for champ in ("entreprise", "intitule", "ville", "source", "first_seen"):
            if not record.get(champ):
                erreurs.append(f"{oid} : champ obligatoire vide « {champ} »")
        if record.get("contrat") not in CONTRATS_VALIDES:
            erreurs.append(f"{oid} : contrat invalide « {record.get('contrat')} »")
        if not record.get("active", True) and not record.get("closed_at"):
            erreurs.append(f"{oid} : inactive sans closed_at")
        url = record.get("url", "")
        if url and not url.startswith(("http://", "https://")):
            erreurs.append(f"{oid} : url invalide « {url} »")

    if erreurs:
        for e in erreurs:
            print(f"[ERREUR] {e}", file=sys.stderr)
        return 1
    print(f"[OK] {len(data)} enregistrements valides")
    return 0


def cmd_contribution(args) -> int:
    from alternance_engine import store as store_mod
    from alternance_engine.contribution import offre_depuis_event

    offre = offre_depuis_event(args.event_file)
    data = store_mod.load(STORE_PATH)
    store_mod.merge(data, [offre], sources_reussies=set())
    store_mod.save(STORE_PATH, data)
    print(f"[OK] offre ajoutée : {offre.entreprise} — {offre.intitule} ({offre.id})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="alternance-engine")
    sub = parser.add_subparsers(dest="commande", required=True)
    sub.add_parser("update", help="fetch des sources → data/listings.json")
    sub.add_parser("render", help="data/listings.json → README.md")
    sub.add_parser("validate", help="valide l'intégrité du store")
    p_contrib = sub.add_parser("contribution", help="traite une issue approuvée")
    p_contrib.add_argument("event_file", help="chemin du fichier event GitHub (JSON)")
    args = parser.parse_args()
    return {
        "update": cmd_update,
        "render": cmd_render,
        "validate": cmd_validate,
        "contribution": cmd_contribution,
    }[args.commande](args)


if __name__ == "__main__":
    raise SystemExit(main())
