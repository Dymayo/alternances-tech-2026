#!/usr/bin/env python3
"""Diagnostic de l'export LBA : pourquoi si peu d'offres retenues ?

Premier run réel (2026-10-29) : 294 166 éléments lus, 146 offres retenues.
Ce script répond à trois questions sur le vrai fichier :
  1. Combien d'éléments sont des offres, et combien des recruteurs_lba ?
  2. Quels codes ROME portent les offres (et combien n'en ont aucun) ?
  3. Parmi les offres dont l'INTITULÉ est clairement tech, combien notre
     filtre ROME rejette-t-il, et avec quels codes ?

Sortie en Markdown (stdout), pensée pour $GITHUB_STEP_SUMMARY. Lancé par
le workflow manuel « Diagnostic export LBA », ou en local :

    LBA_API_KEY=xxx python scripts/diagnostic_export.py
    LBA_EXPORT_FILE=export.json python scripts/diagnostic_export.py
"""

from __future__ import annotations

import asyncio
import collections
import json
import os
import re
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

import httpx  # noqa: E402
import ijson  # noqa: E402

from alternance_engine.connectors import la_bonne_alternance as lba  # noqa: E402
from alternance_engine.models import normaliser  # noqa: E402

# Intitulés sans ambiguïté tech, indépendants des codes ROME.
TECH = re.compile(
    r"(?<![a-z])(developp|informati|logiciel|devops|cyber|reseaux? info|"
    r"data (engineer|analyst|scientist)|full ?stack|back-?end|front-?end|"
    r"administrateur (systeme|reseau)|technicien (informatique|reseau|support)|"
    r"cloud|python|java(?!s)|dev web|web developer|software)"
)


async def _fichier() -> tuple[str, bool]:
    local = os.environ.get(lba.ENV_FICHIER_LOCAL)
    if local:
        return local, False
    key = os.environ["LBA_API_KEY"]
    async with httpx.AsyncClient() as client:
        r = await client.get(
            lba.BASE_URL + lba.EXPORT_PATH,
            headers={"Authorization": f"Bearer {key}"},
            timeout=60,
        )
        r.raise_for_status()
        url = r.json()["url"]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            chemin = tmp.name
        await lba._telecharger(url, client, chemin)
    return chemin, True


def main() -> int:
    chemin, temporaire = asyncio.run(_fichier())
    romes = {r.upper() for r in json.load(open(RACINE / "config.json"))["romes"]}

    partenaires = collections.Counter()
    statuts = collections.Counter()
    codes = collections.Counter()
    sans_code = 0
    offres = 0
    tech_total = 0
    tech_retenues = 0
    tech_rejetees_codes = collections.Counter()
    exemples: list[tuple[str, list]] = []
    formats = collections.Counter()

    with open(chemin, "rb") as f:
        for brut in ijson.items(f, "item"):
            if not isinstance(brut, dict):
                continue
            p = str((brut.get("identifier") or {}).get("partner_label") or "?")
            partenaires[p] += 1
            if p.lower() in lba.PARTENAIRES_EXCLUS:
                continue
            offer = brut.get("offer") or {}
            statuts[str(offer.get("status"))] += 1
            offres += 1
            rc = offer.get("rome_codes")
            formats[type(rc).__name__] += 1
            liste = rc if isinstance(rc, list) else ([rc] if rc else [])
            liste = [str(c).strip().upper() for c in liste if c]
            if not liste:
                sans_code += 1
            codes.update(liste)
            titre = normaliser(str(offer.get("title") or ""))
            if TECH.search(titre):
                tech_total += 1
                if any(c in romes for c in liste):
                    tech_retenues += 1
                else:
                    tech_rejetees_codes.update(liste or ["(aucun)"])
                    if len(exemples) < 40:
                        exemples.append((str(offer.get("title"))[:80], liste))
    if temporaire:
        os.unlink(chemin)

    print("# Diagnostic export LBA\n")
    print(f"- éléments : **{sum(partenaires.values())}**, dont offres (hors recruteurs) : **{offres}**")
    print(f"- offres sans code ROME : **{sans_code}**")
    print(f"- type de `offer.rome_codes` : {dict(formats)}")
    print(f"- statuts : {dict(statuts)}")
    print(f"- offres à intitulé tech : **{tech_total}**, retenues par le filtre ROME : "
          f"**{tech_retenues}**, rejetées : **{tech_total - tech_retenues}**\n")
    print("## Partenaires\n\n| partner_label | éléments |\n|---|---|")
    for p, n in partenaires.most_common(30):
        print(f"| {p} | {n} |")
    print("\n## Codes des offres tech REJETÉES (top 40)\n\n| code | offres | dans config ? |\n|---|---|---|")
    for c, n in tech_rejetees_codes.most_common(40):
        print(f"| `{c}` | {n} | {'oui' if c in romes else 'non'} |")
    print("\n## Codes ROME les plus fréquents, toutes offres (top 40)\n\n| code | offres |\n|---|---|")
    for c, n in codes.most_common(40):
        print(f"| `{c}` | {n} |")
    print("\n## Exemples d'offres tech rejetées\n\n| intitulé | codes |\n|---|---|")
    for t, l in exemples:
        print(f"| {t.replace('|', '/')} | {', '.join(l) or '(aucun)'} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
