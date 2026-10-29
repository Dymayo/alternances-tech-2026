"""Catégorisation par mots-clés sur l'intitulé (+ description si disponible).

Volontairement simple et déterministe : des règles lisibles qu'un contributeur
peut corriger par PR, plutôt qu'un classifieur opaque. L'ordre des catégories
compte — la première qui matche gagne (Cyber avant Dev, sinon "développeur
sécurité" tomberait dans Dev).

Correspondance par MOTS, pas par sous-chaînes : jusqu'en v1.1.0, "ssi"
matchait « aSSIstant », « miSSIon », « paSSIon »... Avec les descriptions
complètes de l'export, 94 offres actives sur 136 finissaient en
Cybersécurité (une seule l'était vraiment). Règles :
  - mot-clé de 3 caractères ou moins (soc, ssi, iam, ia, bi, api, qa...)
    → mot entier ;
  - mot-clé plus long → début de mot, pour couvrir les flexions
    (developp → développeur/développement, reseau → réseaux) ;
  - l'intitulé décide ; la description ne sert que si l'intitulé ne
    matche aucune catégorie (une description générique d'entreprise
    mentionne souvent « sécurité » ou « données » sans rapport avec le poste).
"""

from __future__ import annotations

import html
import re

from .models import Offre, normaliser

# (nom de catégorie, emoji, mots-clés déclencheurs — déjà normalisés)
CATEGORIES: list[tuple[str, str, list[str]]] = [
    (
        "Cybersécurité",
        "🔐",
        ["cyber", "securite", "soc ", "pentest", "ssi", "grc", "iam", "forensic"],
    ),
    (
        "Data & IA",
        "🤖",
        [
            "data", "donnees", "machine learning", "deep learning", " ia ", "(ia)",
            "intelligence artificielle", "bi ", "business intelligence",
            "power bi", "analytics", "analyste donnees", "llm", "nlp",
        ],
    ),
    (
        "Embarqué & Électronique",
        "⚙️",
        [
            "embarque", "firmware", "fpga", "microcontroleur", "electronique",
            "iot", "stm32", "vhdl", "hardware", "mecatronique", "automatisme", "automaticien",
        ],
    ),
    (
        "Réseaux, Cloud & Infra",
        "🌐",
        [
            "reseau", "cloud", "devops", "sre", "infrastructure", "systeme",
            "sysadmin", "kubernetes", "aws", "azure", "gcp", "virtualisation",
            "supervision", "telecom",
        ],
    ),
    (
        "Développement",
        "💻",
        [
            "developp", "software", "logiciel", "full stack", "fullstack",
            "front", "back", "web", "mobile", "java", "python", "php", ".net",
            "c++", "javascript", "typescript", "golang", "rust", "api",
            "application", "informatique",
        ],
    ),
    (
        "Produit, Support & Gestion de projet",
        "📱",
        [
            "produit", "product", "chef de projet", "scrum", "support",
            "helpdesk", "moa", "amoa", "fonctionnel", "qa ", "test", "recette",
        ],
    ),
]

AUTRE = ("Autre", "📦")

# Liste ordonnée (catégorie, emoji) pour le rendu — inclut "Autre" en dernier.
ORDRE_RENDU: list[tuple[str, str]] = [(nom, emoji) for nom, emoji, _ in CATEGORIES] + [AUTRE]


def _motif(mot: str) -> str:
    mot = mot.strip()
    debut = r"(?<![a-z0-9])" + re.escape(mot)
    return debut + r"(?![a-z0-9])" if len(mot) <= 3 else debut


# Compilé une fois : une regex par catégorie, alternance de ses mots-clés.
_REGEX: list[tuple[str, re.Pattern[str]]] = [
    (nom, re.compile("|".join(_motif(m) for m in mots))) for nom, _emoji, mots in CATEGORIES
]


def _texte(brut: str) -> str:
    # html.unescape : les intitulés de l'export contiennent des « &amp; ».
    return " " + normaliser(html.unescape(brut)) + " "


def _premiere_categorie(texte: str) -> str | None:
    for nom, regex in _REGEX:
        if regex.search(texte):
            return nom
    return None


def categoriser(offre: Offre) -> str:
    """Assigne une catégorie d'après l'intitulé ; la description (600
    premiers caractères) ne sert qu'en repli, si l'intitulé ne suffit pas."""
    trouvee = _premiere_categorie(_texte(offre.intitule))
    if trouvee is None and offre.description:
        trouvee = _premiere_categorie(_texte(offre.description[:600]))
    return trouvee or AUTRE[0]


def emoji_de(categorie: str) -> str:
    for nom, emoji in ORDRE_RENDU:
        if nom == categorie:
            return emoji
    return AUTRE[1]
