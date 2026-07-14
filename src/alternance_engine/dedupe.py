"""Déduplication inter-sources.

La même offre existe souvent sur plusieurs plateformes (l'API La bonne
alternance agrège déjà France Travail, Hellowork, Meteojob...). La clé de
dédup est (entreprise, intitulé, ville) normalisés — cf. Offre.cle_dedup().

Règle de priorité : en cas de doublon, on garde l'offre de la source la
plus fiable / la plus riche, et on complète ses champs vides avec ceux
du doublon (une source peut connaître la durée, l'autre le télétravail).
"""

from __future__ import annotations

from .models import Offre

# Plus petit = prioritaire. La communauté prime : un humain a vérifié l'offre.
PRIORITE_SOURCE = {"communaute": 0, "lba": 1}

CHAMPS_COMPLETABLES = (
    "niveau",
    "duree_mois",
    "teletravail",
    "url",
    "date_publication",
    "description",
)


def _prio(offre: Offre) -> int:
    return PRIORITE_SOURCE.get(offre.source, 99)


def _completer(gardee: Offre, doublon: Offre) -> None:
    for champ in CHAMPS_COMPLETABLES:
        if not getattr(gardee, champ):
            valeur = getattr(doublon, champ)
            if valeur:
                setattr(gardee, champ, valeur)


def dedupe(offres: list[Offre]) -> list[Offre]:
    """Retourne la liste sans doublons, ordre d'apparition préservé."""
    par_cle: dict[tuple[str, str, str], Offre] = {}
    for offre in offres:
        cle = offre.cle_dedup()
        existante = par_cle.get(cle)
        if existante is None:
            par_cle[cle] = offre
        elif _prio(offre) < _prio(existante):
            _completer(offre, existante)
            par_cle[cle] = offre
        else:
            _completer(existante, offre)
    return list(par_cle.values())
