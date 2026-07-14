"""Connecteur API La bonne alternance (api.apprentissage.beta.gouv.fr).

API publique de l'État qui agrège les offres d'alternance de La bonne
alternance et de ses partenaires (France Travail, Hellowork, Meteojob,
ATS partenaires...) — ~320 000 offres diffusées en 2025. Gratuite pour
un usage non lucratif, ce qui est le cas de ce repo.

⚠️ Prérequis : créer un jeton sur https://api.apprentissage.beta.gouv.fr
   et le stocker dans le secret GitHub `LBA_API_KEY`.
   La route exacte et le format de réponse sont documentés sur
   https://api.apprentissage.beta.gouv.fr/fr/explorer/recherche-offre —
   vérifiez-les à la première mise en route et ajustez `_vers_offre()`
   si le schéma a évolué : c'est le SEUL fichier à toucher (isolation
   par connecteur).

Contrat du connecteur (commun à toutes les sources) :
  - `async fetch(config, client) -> list[Offre]` ;
  - ne lève jamais vers le pipeline pour une offre isolée malformée
    (on saute l'offre, on loggue) ; une erreur HTTP/réseau, elle,
    remonte — le pipeline l'attrape et marque la source en échec.
"""

from __future__ import annotations

import os

import httpx

from ..models import Offre, make_id

BASE_URL = os.environ.get(
    "LBA_BASE_URL", "https://api.apprentissage.beta.gouv.fr/api/job/v1/search"
)

SOURCE = "lba"

# Correspondance niveau de diplôme cible (paramètre API) — cf. docs.
# On interroge sans filtre de niveau et on garde tout : le README affiche
# le niveau, le lecteur filtre avec Ctrl+F.


def _premiere(valeurs: list, *chemins: str):
    """Extrait la première valeur non vide parmi des chemins 'a.b.c' dans un dict."""
    d = valeurs
    for chemin in chemins:
        cible = d
        ok = True
        for cle in chemin.split("."):
            if isinstance(cible, dict) and cle in cible:
                cible = cible[cle]
            else:
                ok = False
                break
        if ok and cible not in (None, "", []):
            return cible
    return None


def _vers_offre(brut: dict) -> Offre | None:
    """Normalise une offre du format LBA vers notre modèle.

    Les noms de champs ci-dessous suivent le schéma publié (offer/workplace/
    apply/contract) avec des chemins de repli pour absorber les variations
    mineures entre versions de l'API.
    """
    intitule = _premiere(brut, "offer.title", "title") or ""
    entreprise = (
        _premiere(brut, "workplace.name", "workplace.legal_name", "company.name") or ""
    )
    if not intitule or not entreprise:
        return None  # offre inexploitable pour une liste — on saute

    ville = (
        _premiere(
            brut,
            "workplace.location.address",
            "workplace.address.city",
            "place.city",
        )
        or "France entière"
    )
    url = _premiere(brut, "apply.url", "url", "contact.url") or ""
    date_pub = _premiere(brut, "offer.publication.creation", "offer.creation", "job.creationDate")
    if isinstance(date_pub, str) and len(date_pub) >= 10:
        date_pub = date_pub[:10]
    else:
        date_pub = None

    contrat = "apprentissage"
    types = _premiere(brut, "contract.type", "job.contractType") or []
    if isinstance(types, str):
        types = [types]
    types_norm = {str(t).lower() for t in types}
    if types_norm == {"professionnalisation"}:
        contrat = "professionnalisation"
    elif len(types_norm) > 1:
        contrat = "indifferent"

    niveau = str(_premiere(brut, "offer.target_diploma.label", "diplomaLevel") or "")
    duree = _premiere(brut, "contract.duration", "job.dureeContrat")
    try:
        duree = int(duree) if duree is not None else None
    except (TypeError, ValueError):
        duree = None

    remote = str(_premiere(brut, "contract.remote", "offer.remote") or "").lower()
    teletravail = {"hybrid": "hybride", "remote": "total"}.get(remote, "")

    description = _premiere(brut, "offer.description", "job.description")

    return Offre(
        id=make_id(SOURCE, entreprise, intitule, str(ville)),
        source=SOURCE,
        entreprise=str(entreprise).strip(),
        intitule=str(intitule).strip(),
        ville=str(ville).strip(),
        contrat=contrat,
        niveau=niveau.strip(),
        duree_mois=duree,
        teletravail=teletravail,
        url=str(url),
        date_publication=date_pub,
        description=description if isinstance(description, str) else None,
    )


async def fetch(config: dict, client: httpx.AsyncClient) -> list[Offre]:
    """Interroge l'API pour chaque code ROME configuré, France entière."""
    api_key = os.environ.get("LBA_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    offres: list[Offre] = []
    for rome in config.get("romes", []):
        resp = await client.get(
            BASE_URL,
            params={"romes": rome},
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        # Le schéma expose les offres sous "jobs" (les "recruteurs_lba",
        # candidatures spontanées sans offre, ne nous intéressent pas ici).
        bruts = data.get("jobs", data if isinstance(data, list) else [])
        for brut in bruts:
            if not isinstance(brut, dict):
                continue
            offre = _vers_offre(brut)
            if offre is not None:
                offres.append(offre)
    return offres
