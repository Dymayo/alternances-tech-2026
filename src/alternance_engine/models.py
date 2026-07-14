"""Le modèle normalisé unique que chaque source produit.

Principe (repris de l'analyse d'intern_engine) : une seule forme de données
signifie que le pipeline, le store et le rendu ne savent jamais de quelle
source vient une offre — ajouter une source ne touche que son connecteur.

Champs transitoires : `description` n'est utilisée que pendant un run
(catégorisation par mots-clés) et n'est JAMAIS persistée dans le store,
sinon listings.json deviendrait un monolithe de plusieurs Mo (le piège
du listings.json de 11 Mo de SimplifyJobs).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field

# Champs qui existent seulement pendant un run et ne doivent jamais
# être écrits dans data/listings.json.
TRANSIENT_FIELDS = ("description",)

CONTRATS_VALIDES = {"apprentissage", "professionnalisation", "indifferent"}


def normaliser(texte: str) -> str:
    """Minuscule, sans accents, espaces compactés — pour clés de dédup et matching."""
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texte.lower()).strip()


@dataclass
class Offre:
    id: str                     # stable : "<source>:<hash court>" — voir make_id()
    source: str                 # "lba" | "communaute" | ...
    entreprise: str
    intitule: str
    ville: str                  # "Lyon (69)" ; "France entière" si non localisée
    contrat: str = "apprentissage"      # apprentissage | professionnalisation | indifferent
    niveau: str = ""            # niveau visé, ex. "Bac+3", "Bac+5" ("" = non précisé)
    duree_mois: int | None = None
    teletravail: str = ""       # "" | "hybride" | "total"
    url: str = ""
    categorie: str = "Autre"    # assignée par categorize.py
    date_publication: str | None = None  # ISO "YYYY-MM-DD" ou None si inconnue
    description: str | None = None       # TRANSITOIRE — jamais persistée

    def cle_dedup(self) -> tuple[str, str, str]:
        """Clé de déduplication inter-sources : même offre publiée sur
        plusieurs plateformes = (entreprise, intitulé, ville) normalisés."""
        return (
            normaliser(self.entreprise),
            normaliser(self.intitule),
            normaliser(self.ville),
        )

    def to_store(self) -> dict:
        """Dict persistable : sans les champs transitoires ni les None inutiles."""
        d = asdict(self)
        for f in TRANSIENT_FIELDS:
            d.pop(f, None)
        return d


def make_id(source: str, entreprise: str, intitule: str, ville: str) -> str:
    """Id stable et court, indépendant des ids internes (parfois instables)
    des plateformes sources."""
    base = "|".join(normaliser(x) for x in (entreprise, intitule, ville))
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
    return f"{source}:{h}"


def from_store(d: dict) -> Offre:
    """Reconstruit une Offre depuis un enregistrement du store (ignore les
    champs de cycle de vie ajoutés par store.py)."""
    champs = {f.name for f in Offre.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return Offre(**{k: v for k, v in d.items() if k in champs})


# `field` importé pour usage futur (defaults mutables) — évite un import oublié.
_ = field
