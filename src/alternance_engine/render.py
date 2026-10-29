"""Génération des READMEs depuis le store.

Deux patterns repris de l'analyse :
  - injection dans un template entre marqueurs `<!-- BEGIN X --> / <!-- END X -->`
    (european-tech-internships) : le texte éditorial vit dans
    templates/README.template.md, jamais dans le code ;
  - garde-fou de la limite de rendu Markdown de GitHub, 512 Kio
    (SimplifyJobs) : au-delà, GitHub tronque silencieusement le rendu,
    donc on insère un avertissement et on bascule le surplus le plus
    ancien vers README-Inactive.md.

README.md      = offres actives, groupées par catégorie, plus récentes en tête.
README-Inactive.md = offres fermées (archivage, pattern SimplifyJobs).
Ces fichiers sont GÉNÉRÉS : ne jamais les éditer à la main.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

from .categorize import ORDRE_RENDU, emoji_de
from .store import _parse_iso

GITHUB_FILE_SIZE_LIMIT = 512_000  # 500 Kio
SIZE_BUFFER = 4_096

AVERTISSEMENT_TAILLE = (
    "\n> ⚠️ **Ce fichier approche la limite d'affichage de GitHub (512 Kio).**\n"
    "> Les offres les plus anciennes ont été déplacées vers "
    "[README-Inactive.md](README-Inactive.md).\n\n"
)

EN_TETE_TABLE = (
    "| Entreprise | Poste | Ville | Contrat | Début | Niveau | Candidater | Ajoutée |\n"
    "| --- | --- | --- | --- | :---: | --- | :---: | :---: |\n"
)


def _age_court(ref: datetime, now: datetime) -> str:
    jours = (now - ref).days
    if jours <= 0:
        return "0j"
    if jours < 31:
        return f"{jours}j"
    return f"{jours // 30}mo"


def _debut_affiche(record: dict) -> str:
    """Colonne « Début » : date de début du contrat au format JJ/MM/AAAA.

    La source ne la renseigne pas toujours (et beaucoup d'offres
    d'alternance restent sur un début « à convenir ») → « — » sinon.
    """
    brut = record.get("date_debut")
    if not brut:
        return "—"
    try:
        return datetime.strptime(str(brut)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return "—"


def _date_reference(record: dict) -> datetime:
    """Date affichée dans la colonne « Ajoutée » et utilisée pour le badge
    🆕 : la date de PUBLICATION de l'offre (côté source) quand on la
    connaît, sinon `first_seen` (date à laquelle nous l'avons ajoutée au
    repo) faute de mieux."""
    date_pub = record.get("date_publication")
    if date_pub:
        try:
            return datetime.strptime(date_pub, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            pass
    return _parse_iso(record.get("first_seen", ""))


def _libelle_contrat(record: dict) -> str:
    """« indifferent » n'a pas le même sens selon la source : côté LBA, l'API
    remplit les deux types quand l'offre n'en précise aucun (« Non précisé ») ;
    côté communauté, le contributeur a choisi « Indifférent » dans le formulaire."""
    contrat = record.get("contrat", "")
    if contrat == "apprentissage":
        return "Apprentissage"
    if contrat == "professionnalisation":
        return "Contrat pro"
    return "Indifférent" if record.get("source") == "communaute" else "Non précisé"


def _ligne(record: dict, now: datetime) -> str:
    e = record.get("entreprise", "")
    poste = record.get("intitule", "")
    ref = _date_reference(record)
    nouveau = "🆕 " if (now - ref).days < 7 else ""
    ville = record.get("ville", "")
    if record.get("teletravail") == "hybride":
        ville += " 🏠"
    elif record.get("teletravail") == "total":
        ville = "Télétravail total 🏠"
    contrat = _libelle_contrat(record)
    duree = record.get("duree_mois")
    if duree:
        contrat += f" · {duree} mois"
    debut = _debut_affiche(record)
    niveau = record.get("niveau") or "—"
    url = record.get("url", "")
    lien = f"[Postuler ↗]({url})" if url else "—"
    age = f"{ref.strftime('%d/%m/%Y')} ({_age_court(ref, now)})"
    # Échappe les pipes pour ne pas casser la table.
    # html.unescape : l'export LBA livre des « &amp; » bruts. Décodés à
    # l'affichage seulement — les modifier dans le store changerait les ids.
    clean = lambda s: html.unescape(str(s)).replace("|", "\\|").replace("\n", " ").strip()  # noqa: E731
    return (
        f"| **{clean(e)}** | {nouveau}{clean(poste)} | {clean(ville)} "
        f"| {contrat} | {debut} | {clean(niveau)} | {lien} | {age} |\n"
    )


def _table_par_categorie(records: list[dict], now: datetime) -> str:
    """Tables actives groupées par catégorie, tri : plus récentes d'abord."""
    blocs: list[str] = []
    total = len(records)
    blocs.append(f"### {total} offres actives\n\n")
    for categorie, emoji in ORDRE_RENDU:
        du_groupe = [r for r in records if r.get("categorie", "Autre") == categorie]
        if not du_groupe:
            continue
        du_groupe.sort(key=lambda r: r.get("first_seen", ""), reverse=True)
        blocs.append(f"## {emoji} {categorie} ({len(du_groupe)})\n\n")
        blocs.append(EN_TETE_TABLE)
        blocs.extend(_ligne(r, now) for r in du_groupe)
        blocs.append("\n")
    return "".join(blocs)


def _table_inactives(records: list[dict], now: datetime, tri: str = "closed_at") -> str:
    if not records:
        return "_Aucune offre archivée pour le moment._\n"
    records = sorted(records, key=lambda r: r.get(tri) or "", reverse=True)
    blocs = [EN_TETE_TABLE]
    for r in records:
        blocs.append(_ligne(r, now))
    return "".join(blocs)


def inject_block(template: str, tag: str, contenu: str) -> str:
    """Injecte `contenu` entre <!-- BEGIN tag --> et <!-- END tag -->."""
    pattern = rf"(<!-- BEGIN {tag} -->)(.*?)(<!-- END {tag} -->)"
    if not re.search(pattern, template, flags=re.S):
        raise ValueError(f"Marqueurs <!-- BEGIN {tag} --> introuvables dans le template")
    return re.sub(
        pattern,
        lambda m: f"{m.group(1)}\n{contenu}\n{m.group(3)}",
        template,
        flags=re.S,
    )


def _readme(template: str, actives: list[dict], deplacees: bool, now: datetime) -> str:
    corps = _table_par_categorie(actives, now)
    if deplacees:
        corps = AVERTISSEMENT_TAILLE + corps
    readme = inject_block(template, "OFFRES", corps)
    return inject_block(
        readme, "MAJ", f"_Dernière mise à jour : {now.strftime('%d/%m/%Y %H:%M UTC')}_"
    )


def _tient(texte: str) -> bool:
    return len(texte.encode("utf-8")) <= GITHUB_FILE_SIZE_LIMIT - SIZE_BUFFER


def render(store: dict, template: str, now: datetime | None = None) -> tuple[str, str]:
    """Retourne (README.md, README-Inactive.md).

    Si le README dépasse la limite GitHub, on garde les offres actives les
    plus récentes qui tiennent ; les autres passent dans README-Inactive.md,
    dans une section à part (elles restent ouvertes), et un avertissement
    est injecté.

    Le nombre d'offres gardées est trouvé par dichotomie (~log2(n) rendus) :
    l'ancienne boucle « retirer la plus ancienne puis tout regénérer » était
    quadratique — plus d'une minute à 3 000 offres, sans fin à 6 000, ordres
    de grandeur atteignables avec l'export complet.

    Les offres fermées de README-Inactive.md sont plafonnées (les plus
    récemment fermées d'abord) : l'historique complet vit dans
    data/archive/ et data/listings.json, le fichier n'est qu'une vitrine.
    """
    now = now or datetime.now(UTC)
    actives = sorted(
        (r for r in store.values() if r.get("active", True)),
        key=lambda r: r.get("first_seen", ""),
        reverse=True,
    )
    inactives = [r for r in store.values() if not r.get("active", True)]

    readme = _readme(template, actives, False, now)
    gardees = len(actives)
    if not _tient(readme):
        bas, haut = 0, len(actives) - 1  # invariant : `bas` offres tiennent
        while bas < haut:
            milieu = (bas + haut + 1) // 2
            if _tient(_readme(template, actives[:milieu], True, now)):
                bas = milieu
            else:
                haut = milieu - 1
        gardees = bas
        readme = _readme(template, actives[:gardees], True, now)
    deplacees = actives[gardees:]

    entete = (
        "# 🔒 Offres archivées\n\n"
        "Fichier généré automatiquement — ne pas éditer à la main.\n\n"
    )
    section_deplacees = ""
    if deplacees:
        section_deplacees = (
            f"## Offres encore ouvertes, déplacées faute de place ({len(deplacees)})\n\n"
            "Le README principal a atteint la limite d'affichage de GitHub : les "
            "offres actives les plus anciennes sont listées ici.\n\n"
            + _table_inactives(deplacees, now, tri="first_seen")
            + "\n"
        )
    inactives.sort(key=lambda r: r.get("closed_at") or "", reverse=True)
    titre_fermees = f"## Offres fermées ({len(inactives)})\n\n"
    fermees_md = _table_inactives(inactives, now)
    n = len(inactives)
    if not _tient(entete + section_deplacees + titre_fermees + fermees_md) and inactives:
        bas, haut = 0, n - 1
        while bas < haut:
            milieu = (bas + haut + 1) // 2
            essai = entete + section_deplacees + titre_fermees + _table_inactives(inactives[:milieu], now)
            if _tient(essai):
                bas = milieu
            else:
                haut = milieu - 1
        n = bas
        fermees_md = (
            f"_{n} plus récentes sur {len(inactives)} — historique complet dans "
            "`data/archive/` et `data/listings.json`._\n\n"
            + _table_inactives(inactives[:n], now)
        )
    return readme, entete + section_deplacees + titre_fermees + fermees_md
