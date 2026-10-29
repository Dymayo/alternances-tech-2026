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
        "contract": {
            "duration": 24, "type": ["Apprentissage"], "remote": "hybrid",
            "start": "2026-09-01T00:00:00.000Z",
        },
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
    {
        # Recruteur à candidature spontanée, tel qu'il figure réellement dans
        # l'export (run du 2026-08-05) : ROME tech, mais aucune offre.
        "identifier": {"id": "r1", "partner_label": "recruteurs_lba"},
        "offer": {"title": "recruteurs_lba", "rome_codes": ["M1805"], "status": "Active"},
        "workplace": {"name": "COMMUTATION AUDIO", "location": {"address": "91370 VERRIERES"}},
        "apply": {"url": "https://labonnealternance.apprentissage.beta.gouv.fr/emploi/recruteurs_lba/1"},
    },
    {
        # Même chose sans partner_label : l'intitulé suffit à l'écarter.
        "offer": {"title": "recruteurs_lba", "rome_codes": ["M1802"], "status": "Active"},
        "workplace": {"name": "AUTRE RECRUTEUR"},
    },
    {
        # Code ROME v4 « enfant » (M1855 Développeur web, parent M1805).
        "identifier": {"id": "ft1", "partner_label": "France Travail"},
        "offer": {"title": "Alternance développeur React", "rome_codes": ["M1855"], "status": "Active"},
        "workplace": {"name": "Doctolib", "location": {"address": "75001 Paris"}},
        "apply": {"url": "https://exemple.fr/offre/7"},
    },
]

CONFIG = {"romes": ["M1805", "M1802", "M1855"]}


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
        "Alternance développeur React",
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
    assert dev.ville == "12 avenue des Champs, 31000 Toulouse"  # brute : l'id en dépend
    assert dev.contrat == "apprentissage"     # "Apprentissage" capitalisé en entrée
    assert dev.teletravail == "hybride"       # "hybrid" en entrée
    assert dev.duree_mois == 24
    assert dev.niveau == "Master, titre ingénieur (Bac+5)"
    assert dev.date_publication == "2026-06-23"
    assert dev.date_debut == "2026-09-01"
    assert dev.source == "lba"
    assert dev.id.startswith("lba:")


def test_contrat_professionnalisation_et_teletravail_total(fichier_export):
    offres = {o.intitule: o for o in _fetch(fichier_export)}
    data = offres["Alternance Data Analyst"]
    assert data.contrat == "professionnalisation"
    assert data.teletravail == "total"
    assert data.ville == "1 rue Test, 92320 Châtillon"


def test_double_type_de_contrat_et_ville_par_defaut(fichier_export):
    offres = {o.intitule: o for o in _fetch(fichier_export)}
    cyber = offres["Ingénieur Cybersécurité"]
    assert cyber.contrat == "indifferent"
    assert cyber.ville == "France entière"    # aucune adresse fournie


def test_recruteurs_lba_exclus(fichier_export):
    """La cause de l'annulation du run du 2026-08-05 (98,8 % de recruteurs)."""
    offres = _fetch(fichier_export)
    assert not any("recruteurs_lba" in o.intitule for o in offres)
    assert not any(o.entreprise in {"COMMUTATION AUDIO", "AUTRE RECRUTEUR"} for o in offres)


def test_code_rome_v4_enfant_retenu(fichier_export):
    offres = _fetch(fichier_export)
    assert any(o.entreprise == "Doctolib" for o in offres)


def test_id_identique_a_la_route_de_recherche():
    """Passer de la recherche à l'export ne doit pas changer les ids : sinon
    toutes les offres en store seraient fermées puis recréées. Offre et id
    réels, tirés de data/listings.json (connecteur de recherche)."""
    brut = {
        "offer": {"title": "Apprenti Développeur IA H/F", "rome_codes": ["M1805"], "status": "Active"},
        "workplace": {"name": "TECMA ARIES", "location": {"address": "10430 Rosières-près-Troyes"}},
    }
    assert lba.vers_offre(brut).id == "lba:00276234d5f2"


def test_zero_offre_retenue_leve(tmp_path):
    """Export non vide mais rien de retenu = schéma cassé : la source doit
    passer en échec (aucune fermeture) au lieu de tout fermer."""
    chemin = tmp_path / "export.json"
    chemin.write_text(json.dumps(EXPORT_FIXTURE[2:3]), encoding="utf-8")  # boulanger seul
    with pytest.raises(RuntimeError, match="0 offre retenue"):
        _fetch(str(chemin))


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
