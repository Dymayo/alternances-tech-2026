"""Traitement des contributions communautaires via issue forms GitHub.

Pattern SimplifyJobs : le README étant généré, on n'accepte PAS de PR sur
les données — les contributeurs remplissent un formulaire d'issue structuré
(.github/ISSUE_TEMPLATE/ajouter_offre.yml). Quand un mainteneur pose le
label `contribution-approuvee`, le workflow appelle ce module qui parse le
corps de l'issue et injecte l'offre dans le store.

GitHub rend un issue form en Markdown de la forme :

    ### Nom du champ

    valeur saisie

d'où le parseur ci-dessous.
"""

from __future__ import annotations

import json
import re

from .categorize import categoriser
from .models import Offre, make_id

SOURCE = "communaute"

# Libellés du formulaire (ajouter_offre.yml) → champ du modèle.
CHAMPS = {
    "entreprise": "entreprise",
    "intitulé du poste": "intitule",
    "ville": "ville",
    "lien de candidature": "url",
    "type de contrat": "contrat",
    "niveau visé": "niveau",
    "durée (en mois)": "duree_mois",
    "télétravail": "teletravail",
}

_NO_RESPONSE = "_no response_"


def parse_issue_body(body: str) -> dict:
    """Extrait {label_normalisé: valeur} d'un corps d'issue form."""
    resultat: dict[str, str] = {}
    sections = re.split(r"^### ", body, flags=re.M)
    for section in sections:
        lignes = section.strip().splitlines()
        if not lignes:
            continue
        label = lignes[0].strip().lower()
        valeur = "\n".join(lignes[1:]).strip()
        if valeur.lower() == _NO_RESPONSE:
            valeur = ""
        resultat[label] = valeur
    return resultat


def offre_depuis_issue(body: str) -> Offre:
    champs = parse_issue_body(body)
    valeurs: dict = {}
    for label, attr in CHAMPS.items():
        valeurs[attr] = champs.get(label, "")

    for obligatoire in ("entreprise", "intitule", "ville", "url"):
        if not valeurs.get(obligatoire):
            raise ValueError(f"Champ obligatoire manquant dans l'issue : {obligatoire}")

    contrat = valeurs["contrat"].strip().lower()
    if "pro" in contrat:
        valeurs["contrat"] = "professionnalisation"
    elif "indiff" in contrat:
        valeurs["contrat"] = "indifferent"
    else:
        valeurs["contrat"] = "apprentissage"

    try:
        valeurs["duree_mois"] = int(valeurs["duree_mois"]) if valeurs["duree_mois"] else None
    except ValueError:
        valeurs["duree_mois"] = None

    tt = valeurs["teletravail"].strip().lower()
    valeurs["teletravail"] = (
        "hybride" if "hybride" in tt else "total" if "total" in tt else ""
    )

    offre = Offre(
        id=make_id(SOURCE, valeurs["entreprise"], valeurs["intitule"], valeurs["ville"]),
        source=SOURCE,
        **valeurs,
    )
    offre.categorie = categoriser(offre)
    return offre


def offre_depuis_event(event_path: str) -> Offre:
    """Charge l'event GitHub (GITHUB_EVENT_PATH) et en extrait l'offre."""
    with open(event_path, encoding="utf-8") as f:
        event = json.load(f)
    body = event.get("issue", {}).get("body") or ""
    if not body:
        raise ValueError("Event sans corps d'issue")
    return offre_depuis_issue(body)
