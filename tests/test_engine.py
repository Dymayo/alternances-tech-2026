"""Tests du moteur — couvrent les invariants relevés dans l'analyse :
cycle de vie du store, isolation des pannes, dédup inter-sources,
limite de taille GitHub, parsing des issue forms."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from alternance_engine import store as store_mod
from alternance_engine.categorize import categoriser
from alternance_engine.contribution import offre_depuis_issue
from alternance_engine.dedupe import dedupe
from alternance_engine.models import Offre, make_id
from alternance_engine.render import GITHUB_FILE_SIZE_LIMIT, inject_block, render

TEMPLATE = (
    "# Titre\n<!-- BEGIN MAJ -->\n<!-- END MAJ -->\n"
    "<!-- BEGIN OFFRES -->\nancien contenu\n<!-- END OFFRES -->\n"
)


def offre(source="lba", entreprise="Acme", intitule="Dev Python", ville="Lyon", **kw) -> Offre:
    return Offre(
        id=make_id(source, entreprise, intitule, ville),
        source=source,
        entreprise=entreprise,
        intitule=intitule,
        ville=ville,
        url="https://exemple.fr/offre",
        **kw,
    )


# ---------------------------------------------------------------- store


def test_merge_nouvelle_offre_pose_first_seen():
    data = {}
    stats = store_mod.merge(data, [offre()], sources_reussies={"lba"})
    assert stats["nouvelles"] == 1
    record = next(iter(data.values()))
    assert record["active"] is True
    assert record["first_seen"]
    assert "description" not in record  # champ transitoire jamais persisté


def test_offre_absente_dun_run_reussi_est_fermee():
    data = {}
    o = offre()
    store_mod.merge(data, [o], sources_reussies={"lba"})
    stats = store_mod.merge(data, [], sources_reussies={"lba"})
    assert stats["fermees"] == 1
    assert data[o.id]["active"] is False
    assert data[o.id]["closed_at"]


def test_source_en_echec_ne_ferme_rien():
    """Isolation des pannes : un fetch raté ne doit jamais fermer d'offres."""
    data = {}
    o = offre()
    store_mod.merge(data, [o], sources_reussies={"lba"})
    stats = store_mod.merge(data, [], sources_reussies=set())
    assert stats["fermees"] == 0
    assert data[o.id]["active"] is True


def test_first_seen_preserve_et_reactivation():
    data = {}
    o = offre()
    store_mod.merge(data, [o], sources_reussies={"lba"}, now="2026-01-01T00:00:00Z")
    store_mod.merge(data, [], sources_reussies={"lba"}, now="2026-01-02T00:00:00Z")
    stats = store_mod.merge(data, [o], sources_reussies={"lba"}, now="2026-01-03T00:00:00Z")
    assert stats["reactivees"] == 1
    assert data[o.id]["first_seen"] == "2026-01-01T00:00:00Z"


def test_purge_des_fermees_anciennes():
    data = {}
    o = offre()
    vieux = "2020-01-01T00:00:00Z"
    store_mod.merge(data, [o], sources_reussies={"lba"}, now=vieux)
    store_mod.merge(data, [], sources_reussies={"lba"}, now=vieux)
    assert store_mod.purger(data) == 1
    assert data == {}


def test_offre_communautaire_perimee():
    data = {}
    o = offre(source="communaute")
    vieux = "2020-01-01T00:00:00Z"
    store_mod.merge(data, [o], sources_reussies=set(), now=vieux)
    assert store_mod.marquer_perimees(data) == 1
    assert data[o.id]["active"] is False


# ---------------------------------------------------------------- dedupe


def test_dedupe_meme_offre_deux_sources_priorite_communaute():
    a = offre(source="lba", niveau="Bac+5")
    b = offre(source="communaute", entreprise="ACME ", intitule="dev  python", ville="LYON")
    gardees = dedupe([a, b])
    assert len(gardees) == 1
    assert gardees[0].source == "communaute"
    assert gardees[0].niveau == "Bac+5"  # champ complété depuis le doublon


def test_dedupe_offres_differentes_conservees():
    assert len(dedupe([offre(), offre(ville="Paris")])) == 2


# ---------------------------------------------------------------- categorize


def test_categorisation():
    assert categoriser(offre(intitule="Alternance développeur web H/F")) == "Développement"
    assert categoriser(offre(intitule="Analyste SOC cybersécurité")) == "Cybersécurité"
    assert categoriser(offre(intitule="Data engineer en alternance")) == "Data & IA"
    assert categoriser(offre(intitule="Ingénieur systèmes embarqués IoT")) == "Embarqué & Électronique"
    assert categoriser(offre(intitule="Chargé de clientèle")) == "Autre"


# ---------------------------------------------------------------- render


def test_inject_block_remplace_lancien_contenu():
    out = inject_block(TEMPLATE, "OFFRES", "NOUVEAU")
    assert "NOUVEAU" in out and "ancien contenu" not in out


def test_render_offre_recente_a_badge_nouveau():
    data = {}
    o = offre()
    store_mod.merge(data, [o], sources_reussies={"lba"})
    readme, inactive = render(data, TEMPLATE)
    assert "🆕" in readme
    assert "Acme" in readme
    assert "Aucune offre archivée" in inactive


def test_render_offre_fermee_part_en_archive():
    data = {}
    o = offre()
    store_mod.merge(data, [o], sources_reussies={"lba"})
    store_mod.merge(data, [], sources_reussies={"lba"})
    readme, inactive = render(data, TEMPLATE)
    assert "Acme" not in readme
    assert "Acme" in inactive


def test_render_respecte_la_limite_github():
    """Garde-fou 512 Kio : le surplus le plus ancien part en archive."""
    data = {}
    offres = [
        offre(intitule=f"Poste {i} " + "x" * 300, ville=f"Ville{i}")
        for i in range(2500)
    ]
    store_mod.merge(data, offres, sources_reussies={"lba"})
    readme, inactive = render(data, TEMPLATE)
    assert len(readme.encode("utf-8")) <= GITHUB_FILE_SIZE_LIMIT
    assert "limite d'affichage" in readme
    assert "Poste" in inactive  # le surplus est bien archivé


def test_age_affiche_en_mois():
    data = {}
    o = offre()
    il_y_a_60j = (datetime.now(UTC) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    store_mod.merge(data, [o], sources_reussies={"lba"}, now=il_y_a_60j)
    readme, _ = render(data, TEMPLATE)
    assert "2mo" in readme


# ---------------------------------------------------------------- contribution


ISSUE_BODY = """### Entreprise

Capgemini

### Intitulé du poste

Alternance Développeur Java (H/F)

### Ville

Nantes (44)

### Lien de candidature

https://www.capgemini.com/fr-fr/carrieres/offre-123

### Type de contrat

Apprentissage

### Niveau visé

Bac+5 (Master, Ingénieur)

### Durée (en mois)

24

### Télétravail

Hybride
"""


def test_parse_issue_form():
    o = offre_depuis_issue(ISSUE_BODY)
    assert o.entreprise == "Capgemini"
    assert o.source == "communaute"
    assert o.contrat == "apprentissage"
    assert o.duree_mois == 24
    assert o.teletravail == "hybride"
    assert o.categorie == "Développement"
    assert o.id.startswith("communaute:")


def test_issue_incomplete_rejettee():
    import pytest

    with pytest.raises(ValueError):
        offre_depuis_issue("### Entreprise\n\nAcme\n")
