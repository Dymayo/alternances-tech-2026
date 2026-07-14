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
    "| Entreprise | Poste | Ville | Contrat | Niveau | Candidater | Ajoutée |\n"
    "| --- | --- | --- | --- | --- | :---: | :---: |\n"
)


def _age_court(first_seen: str, now: datetime) -> str:
    jours = (now - _parse_iso(first_seen)).days
    if jours <= 0:
        return "0j"
    if jours < 31:
        return f"{jours}j"
    return f"{jours // 30}mo"


def _ligne(record: dict, now: datetime) -> str:
    e = record.get("entreprise", "")
    poste = record.get("intitule", "")
    nouveau = "🆕 " if (now - _parse_iso(record.get("first_seen", ""))).days < 7 else ""
    ville = record.get("ville", "")
    if record.get("teletravail") == "hybride":
        ville += " 🏠"
    elif record.get("teletravail") == "total":
        ville = "Télétravail total 🏠"
    contrat = {"apprentissage": "Apprentissage", "professionnalisation": "Contrat pro"}.get(
        record.get("contrat", ""), "Indifférent"
    )
    duree = record.get("duree_mois")
    if duree:
        contrat += f" · {duree} mois"
    niveau = record.get("niveau") or "—"
    url = record.get("url", "")
    lien = f"[Postuler ↗]({url})" if url else "—"
    age = _age_court(record.get("first_seen", ""), now)
    # Échappe les pipes pour ne pas casser la table.
    clean = lambda s: str(s).replace("|", "\\|").replace("\n", " ").strip()  # noqa: E731
    return (
        f"| **{clean(e)}** | {nouveau}{clean(poste)} | {clean(ville)} "
        f"| {contrat} | {clean(niveau)} | {lien} | {age} |\n"
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


def _table_inactives(records: list[dict], now: datetime) -> str:
    if not records:
        return "_Aucune offre archivée pour le moment._\n"
    records = sorted(records, key=lambda r: r.get("closed_at") or "", reverse=True)
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


def render(store: dict, template: str, now: datetime | None = None) -> tuple[str, str]:
    """Retourne (README.md, README-Inactive.md).

    Si le README dépasse la limite GitHub, les offres actives les plus
    anciennes sont déplacées vers l'archive jusqu'à repasser sous la limite,
    et un avertissement est injecté.
    """
    now = now or datetime.now(UTC)
    actives = [r for r in store.values() if r.get("active", True)]
    inactives = [r for r in store.values() if not r.get("active", True)]

    deplacees: list[dict] = []
    while True:
        corps = _table_par_categorie(actives, now)
        if deplacees:
            corps = AVERTISSEMENT_TAILLE + corps
        readme = inject_block(template, "OFFRES", corps)
        readme = inject_block(
            readme, "MAJ", f"_Dernière mise à jour : {now.strftime('%d/%m/%Y %H:%M UTC')}_"
        )
        if len(readme.encode("utf-8")) <= GITHUB_FILE_SIZE_LIMIT - SIZE_BUFFER or not actives:
            break
        # Déplace la plus ancienne offre active vers l'archive et regénère.
        actives.sort(key=lambda r: r.get("first_seen", ""))
        deplacees.append(actives.pop(0))

    inactive_md = (
        "# 🔒 Offres archivées\n\n"
        "Offres fermées ou déplacées ici faute de place dans le README principal.\n"
        "Fichier généré automatiquement — ne pas éditer à la main.\n\n"
        + _table_inactives(inactives + deplacees, now)
    )
    return readme, inactive_md
