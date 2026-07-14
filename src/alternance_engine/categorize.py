"""Catégorisation par mots-clés sur l'intitulé (+ description si disponible).

Volontairement simple et déterministe : des règles lisibles qu'un contributeur
peut corriger par PR, plutôt qu'un classifieur opaque. L'ordre des catégories
compte — la première qui matche gagne (Cyber avant Dev, sinon "développeur
sécurité" tomberait dans Dev).
"""

from __future__ import annotations

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
            "iot", "stm32", "vhdl", "hardware", "mecatronique", "automatisme",
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


def categoriser(offre: Offre) -> str:
    """Assigne une catégorie ; le texte analysé est l'intitulé, complété par
    le début de la description quand la source la fournit."""
    texte = " " + normaliser(offre.intitule) + " "
    if offre.description:
        texte += " " + normaliser(offre.description[:600]) + " "
    for nom, _emoji, mots in CATEGORIES:
        if any(mot in texte for mot in mots):
            return nom
    return AUTRE[0]


def emoji_de(categorie: str) -> str:
    for nom, emoji in ORDRE_RENDU:
        if nom == categorie:
            return emoji
    return AUTRE[1]
