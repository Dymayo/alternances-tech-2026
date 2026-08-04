"""Tests du connecteur La bonne alternance (route d'export en masse).

Le jeu de données ci-dessous reproduit fidèlement le format v3 de l'API
tel que défini dans le code source officiel (mission-apprentissage) :
tableau JSON plat, contract.type capitalisé, contract.remote en anglais,
adresse postale complète dans workplace.location.address.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from alternance_engine.connectors import la_bonne_alternance as lba

EXPORT_FIXTURE = [
    {
        "identifier": {"id": "6687165396d52b5e01b409545", "partner_label": "offres_emploi_lba"},
        "contract": {"duration": 24, "type": ["Apprentissage"], "remote": "hybrid"},
        "offer": {
            "title": "Développeur / Développeuse web",
            "description": "Conçoit et développe une application web.",
            "rome_codes": ["M1805"],
            "status": "Active",
            "target_diploma": {"level": "7", "label": "Master, titre ingénieur (Bac+5)"},
            "publication": {"creation": "2026-06-23T13:23:01.000Z"},
        },
        "workplace": {
            "name": "Thales",
            "legal_name": "THALES SA",
            "location": {"address": "12 avenue des Champs, 31000 Toulouse"},
        },
        "apply": {"url": "https://exemple.fr/offre/1"},
    },
    {
        # Contrat pro, télétravail total, ROME data.
        "identifier": {"id": "b16a546a", "partner_label": "France Travail"},
        "contract": {"duration": 12, "type": ["Professionnalisation"], "remote": "remote"},
        "offer": {
            "title": "Alternance Data Analyst",
            "rome_codes": ["M1802"],
            "status": "Active",
            "publication": {"creation": "2026-07-01T09:00:00.000Z"},
        },
        "workplace": {"name": "Orange", "location": {"address": "1 rue Test, 92320 Châtillon"}},
        "apply": {"url": "https://exemple.fr/offre/2"},
    },
    {
        # ROME hors périmètre (boulangerie) → doit être filtrée.
        "offer": {"title": "Alternance Boulanger", "rome_codes": ["D1102"], "status": "Active"},
        "workplace": {"name": "Boulangerie Dupont", "location": {"address": "3 rue X, 75001 Paris"}},
        "apply": {"url": "https://exemple.fr/offre/3"},
    },
    {
        # Statut non actif → doit être filtrée même si le ROME correspond.
        "offer": {"title": "Dev C++", "rome_codes": ["M1805"], "status": "Cancelled"},
        "workplace": {"name": "Ancienne Boite", "location": {"address": "1 rue Y, 69000 Lyon"}},
        "apply": {"url": "https://exemple.fr/offre/4"},
    },
    {
        # Sans intitulé → inexploitable, doit être ignorée sans planter.
        "offer": {"rome_codes": ["M1805"], "status": "Active"},
        "workplace": {"name": "Boite Sans Titre"},
    },
    {
        # Les deux types de contrat → "indifferent" ; pas d'adresse.
        "contract": {"type": ["Apprentissage", "Professionnalisation"]},
        "offer": {"title": "Ingénieur Cybersécurité", "rome_codes": ["M1802"], "status": "Active"},
        "workplace": {"name": "Capgemini"},
        "apply": {"url": "https://exemple.fr/offre/6"},
    },
]

CONFIG = {"romes": ["M1805", "M1802"]}


@pytest.fixture
def fichier_export(tmp_path):
    chemin = tmp_path / "export.json"
    chemin.write_text(json.dumps(EXPORT_FIXTURE), encoding="utf-8")
    return str(chemin)


def _fetch(fichier: str) -> list:
    """Exécute le connecteur en mode fichier local (sans réseau ni jeton)."""
    os.environ[lba.ENV_FICHIER_LOCAL] = fichier
    try:
        return asyncio.run(lba.fetch(CONFIG, client=None))  # client inutilisé hors-ligne
    finally:
        os.environ.pop(lba.ENV_FICHIER_LOCAL, None)


def test_parse_export_complet(fichier_export):
    offres = _fetch(fichier_export)
    intitules = {o.intitule for o in offres}
    assert intitules == {
        "Développeur / Développeuse web",
        "Alternance Data Analyst",
        "Ingénieur Cybersécurité",
    }


def test_filtre_rome_hors_perimetre(fichier_export):
    offres = _fetch(fichier_export)
    assert not any("Boulanger" in o.intitule for o in offres)


def test_filtre_statut_non_actif(fichier_export):
    offres = _fetch(fichier_export)
    assert not any(o.entreprise == "Ancienne Boite" for o in offres)


def test_offre_malformee_ignoree_sans_planter(fichier_export):
    offres = _fetch(fichier_export)
    assert not any(o.entreprise == "Boite Sans Titre" for o in offres)


def test_champs_normalises(fichier_export):
    offres = {o.intitule: o for o in _fetch(fichier_export)}
    dev = offres["Développeur / Développeuse web"]
    assert dev.entreprise == "Thales"
    assert dev.ville == "Toulouse"            # extraite de l'adresse postale
    assert dev.contrat == "apprentissage"     # "Apprentissage" capitalisé en entrée
    assert dev.teletravail == "hybride"       # "hybrid" en entrée
    assert dev.duree_mois == 24
    assert dev.niveau == "Master, titre ingénieur (Bac+5)"
    assert dev.date_publication == "2026-06-23"
    assert dev.source == "lba"
    assert dev.id.startswith("lba:")


def test_contrat_professionnalisation_et_teletravail_total(fichier_export):
    offres = {o.intitule: o for o in _fetch(fichier_export)}
    data = offres["Alternance Data Analyst"]
    assert data.contrat == "professionnalisation"
    assert data.teletravail == "total"
    assert data.ville == "Châtillon"


def test_double_type_de_contrat_et_ville_par_defaut(fichier_export):
    offres = {o.intitule: o for o in _fetch(fichier_export)}
    cyber = offres["Ingénieur Cybersécurité"]
    assert cyber.contrat == "indifferent"
    assert cyber.ville == "France entière"    # aucune adresse fournie


def test_extraction_ville():
    assert lba._ville_depuis_adresse("12 avenue des Champs, 31000 Toulouse") == "Toulouse"
    assert lba._ville_depuis_adresse("5 rue de la Paix, 69003 Lyon 3e") == "Lyon 3e"
    assert lba._ville_depuis_adresse("Adresse sans code postal") == "Adresse sans code postal"


def test_sans_jeton_leve_une_erreur_explicite():
    """Sans LBA_API_KEY ni fichier local, l'erreur doit être compréhensible —
    et le pipeline la traitera comme une panne de source (aucune fermeture)."""
    os.environ.pop(lba.ENV_FICHIER_LOCAL, None)
    ancien = os.environ.pop("LBA_API_KEY", None)
    try:
        with pytest.raises(RuntimeError, match="LBA_API_KEY"):
            asyncio.run(lba.fetch(CONFIG, client=None))
    finally:
        if ancien is not None:
            os.environ["LBA_API_KEY"] = ancien
