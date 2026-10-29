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


def _fermer_offre(data, o, quand):
    store_mod.merge(data, [o], sources_reussies={"lba"}, now=quand)
    store_mod.merge(data, [], sources_reussies={"lba"}, now=quand)


def test_fermee_ancienne_va_en_archive_pas_dans_le_vide(tmp_path):
    """Phase 0 : rien n'est supprimé, tout est déplacé."""
    data = {}
    o = offre(contrat="professionnalisation", date_publication="2019-12-20")
    o.categorie = "Data & IA"
    _fermer_offre(data, o, "2020-01-15T00:00:00Z")

    assert store_mod.archiver(data, str(tmp_path)) == 1
    assert data == {}  # sorti du store...
    lignes = list(store_mod.lire_archive(str(tmp_path)))
    assert len(lignes) == 1  # ...mais présent dans l'archive
    assert (tmp_path / "2020-01.jsonl").exists()  # rangé par mois de fermeture
    r = lignes[0]
    assert r["id"] == o.id
    assert r["first_seen"] == "2020-01-15T00:00:00Z"
    assert r["closed_at"] == "2020-01-15T00:00:00Z"
    assert (r["source"], r["contrat"], r["categorie"], r["ville"]) == (
        "lba", "professionnalisation", "Data & IA", "Lyon",
    )
    assert r["date_publication"] == "2019-12-20"
    assert "active" not in r and "description" not in r


def test_fermee_recente_reste_dans_le_store(tmp_path):
    """Pendant la rétention, l'offre fermée alimente README-Inactive.md."""
    data = {}
    o = offre()
    _fermer_offre(data, o, store_mod.now_iso())
    assert store_mod.archiver(data, str(tmp_path)) == 0
    assert o.id in data
    assert list(store_mod.lire_archive(str(tmp_path))) == []


def test_archive_idempotente(tmp_path):
    """Un run qui plante entre l'archive et le store ne crée pas de doublon."""
    record = {**offre().to_store(), "first_seen": "2020-01-01T00:00:00Z",
              "closed_at": "2020-01-02T00:00:00Z"}
    assert store_mod.ecrire_archive([record], str(tmp_path)) == 1
    assert store_mod.ecrire_archive([record], str(tmp_path)) == 0
    assert len(list(store_mod.lire_archive(str(tmp_path)))) == 1
    assert store_mod.valider_archive(str(tmp_path)) == []


def test_echec_archive_ne_retire_rien_du_store(tmp_path, monkeypatch):
    """Pire cas = report au run suivant, jamais une perte."""
    data = {}
    o = offre()
    _fermer_offre(data, o, "2020-01-15T00:00:00Z")

    def disque_plein(*_a, **_k):
        raise OSError("disque plein")

    monkeypatch.setattr(store_mod, "ecrire_archive", disque_plein)
    try:
        store_mod.archiver(data, str(tmp_path))
    except OSError:
        pass
    assert o.id in data


def test_offre_refermee_donne_deux_episodes(tmp_path):
    data = {}
    o = offre()
    _fermer_offre(data, o, "2020-01-15T00:00:00Z")
    store_mod.archiver(data, str(tmp_path))
    _fermer_offre(data, o, "2020-03-10T00:00:00Z")  # réapparue puis refermée
    store_mod.archiver(data, str(tmp_path))
    lignes = list(store_mod.lire_archive(str(tmp_path)))
    assert [r["closed_at"][:7] for r in lignes] == ["2020-01", "2020-03"]
    assert store_mod.valider_archive(str(tmp_path)) == []


def test_valider_archive_detecte_les_erreurs(tmp_path):
    (tmp_path / "2020-01.jsonl").write_text(
        '{"id": "lba:x", "source": "lba", "entreprise": "A", "intitule": "B",'
        ' "first_seen": "2020-01-01T00:00:00Z", "closed_at": "2020-02-01T00:00:00Z"}\n'
        "pas du json\n",
        encoding="utf-8",
    )
    erreurs = store_mod.valider_archive(str(tmp_path))
    assert any("hors du mois" in e for e in erreurs)
    assert any("JSON invalide" in e for e in erreurs)


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


def test_categorisation_par_mots_pas_par_sous_chaines():
    """Intitulés réels classés Cybersécurité à tort en v1.1.0 ("ssi" dans
    « assistant », "securite" dans une description générique)."""
    assert categoriser(offre(intitule="Assistant MOA Paie en Alternance H/F")) != "Cybersécurité"
    assert categoriser(offre(intitule="Data Engineer - en Alternance H/F")) == "Data & IA"
    assert categoriser(offre(intitule="Technicien Réseau &amp; Télécoms Alternance H/F")) == (
        "Réseaux, Cloud & Infra"
    )
    assert categoriser(
        offre(
            intitule="Développeuse - Développeur Logiciel - Alternance H/F",
            description="Leader de la sécurité et de la data, notre groupe...",
        )
    ) == "Développement"
    assert categoriser(offre(intitule="Ingénieur SSI en alternance")) == "Cybersécurité"


def test_categorisation_description_en_repli():
    o = offre(intitule="Alternant(e) H/F", description="Vous rejoindrez notre équipe DevOps.")
    assert categoriser(o) == "Réseaux, Cloud & Infra"


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


def test_render_colonne_debut():
    """La date de début est affichée en JJ/MM/AAAA, « — » si inconnue."""
    data = {}
    store_mod.merge(
        data,
        [
            offre(entreprise="AvecDebut", date_debut="2026-09-01"),
            offre(entreprise="SansDebut", ville="Nantes"),
        ],
        sources_reussies={"lba"},
    )
    readme, _ = render(data, TEMPLATE)
    assert "| Début |" in readme
    assert "01/09/2026" in readme
    lignes = readme.splitlines()
    entete = next(li for li in lignes if li.startswith("| Entreprise |"))
    ligne_sans = next(li for li in lignes if "SansDebut" in li)
    assert "—" in ligne_sans
    # Le nombre de colonnes doit rester aligné sur l'en-tête.
    assert ligne_sans.count("|") == entete.count("|")


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

### Date de début

01/09/2026

### Télétravail

Hybride
"""


def test_parse_issue_form():
    o = offre_depuis_issue(ISSUE_BODY)
    assert o.entreprise == "Capgemini"
    assert o.source == "communaute"
    assert o.contrat == "apprentissage"
    assert o.duree_mois == 24
    assert o.date_debut == "2026-09-01"
    assert o.teletravail == "hybride"
    assert o.categorie == "Développement"
    assert o.id.startswith("communaute:")


def test_issue_incomplete_rejettee():
    import pytest

    with pytest.raises(ValueError):
        offre_depuis_issue("### Entreprise\n\nAcme\n")
