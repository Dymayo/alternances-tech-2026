"""Orchestrateur : une passe par run.

Fetch de chaque source (échecs isolés — un connecteur en panne ne fait ni
planter le run ni fermer ses offres), normalisation, catégorisation,
déduplication inter-sources, fusion dans le store (détection nouvelles /
fermées / réactivées), marquage des offres communautaires périmées, purge
de rétention, écriture du store.

Contrairement à intern_engine et ses 12 scrapers ATS, une seule source API
officielle suffit ici (La bonne alternance agrège déjà France Travail et
les jobboards partenaires) : le pipeline reste volontairement minuscule.
Ajouter une source = un fichier dans connectors/ + une entrée dans SOURCES.
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx

from . import store as store_mod
from .categorize import categoriser
from .connectors import la_bonne_alternance
from .dedupe import dedupe
from .models import Offre, from_store

SOURCES = {
    "lba": la_bonne_alternance.fetch,
}

USER_AGENT = "alternances-tech-2026 (repo open source non lucratif)"


def charger_config(path: str = "config.json") -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


async def _fetch_source(nom: str, fetch, config: dict, client: httpx.AsyncClient):
    """Retourne (nom, offres, erreur) — ne lève jamais."""
    try:
        offres = await fetch(config, client)
        return nom, offres, None
    except Exception as exc:  # noqa: BLE001 — isolation volontaire des pannes
        return nom, [], f"{type(exc).__name__}: {exc}"


async def run_update(config_path: str = "config.json", store_path: str = "data/listings.json") -> dict:
    config = charger_config(config_path)
    data = store_mod.load(store_path)

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        resultats = await asyncio.gather(
            *(_fetch_source(nom, fetch, config, client) for nom, fetch in SOURCES.items())
        )

    sources_reussies: set[str] = set()
    collectees: list[Offre] = []
    for nom, offres, erreur in resultats:
        if erreur:
            print(f"[WARN] source {nom} en échec : {erreur}", file=sys.stderr)
            continue
        sources_reussies.add(nom)
        collectees.extend(offres)
        print(f"[OK] {nom} : {len(offres)} offres")

    for offre in collectees:
        offre.categorie = categoriser(offre)

    # Les offres communautaires déjà en store participent à la dédup pour
    # que le pipeline ne recrée pas en doublon une offre soumise à la main.
    communautaires = [
        from_store(r)
        for r in data.values()
        if r.get("source") not in store_mod.SOURCES_PIPELINE and r.get("active", True)
    ]
    dedupliquees = dedupe(communautaires + collectees)
    # On ne re-merge que les offres pipeline (les communautaires sont déjà en store).
    a_merger = [o for o in dedupliquees if o.source in store_mod.SOURCES_PIPELINE]

    stats = store_mod.merge(data, a_merger, sources_reussies)
    stats["perimees"] = store_mod.marquer_perimees(data)
    stats["purgees"] = store_mod.purger(data)

    store_mod.save(store_path, data)
    print(
        f"[OK] store : {stats['nouvelles']} nouvelles, {stats['fermees']} fermées, "
        f"{stats['reactivees']} réactivées, {stats['perimees']} périmées, "
        f"{stats['purgees']} purgées"
    )
    return stats
