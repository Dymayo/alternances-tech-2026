"""Connecteur API La bonne alternance (api.apprentissage.beta.gouv.fr).

API publique de l'État qui agrège les offres d'alternance de La bonne
alternance et de ses partenaires (France Travail, Meteojob, Enedis, Engie,
multidiffuseurs Talentplug/Veritone, ATS Kelio/Wink...). Gratuite, réservée
aux usages non lucratifs — ce qui est le cas de ce repo.

────────────────────────────────────────────────────────────────────────
POURQUOI L'EXPORT EN MASSE ET PAS LA ROUTE DE RECHERCHE
────────────────────────────────────────────────────────────────────────
La route `/job/v1/search` (recherche par code ROME / géoloc) est plafonnée
à **150 résultats par source**, sans pagination. Sa propre documentation
le dit : « il n'est pas possible de récupérer toutes les offres
correspondant aux critères de recherche ». Une boucle sur nos 6 codes ROME
ne ramènerait donc qu'une fraction arbitraire du gisement.

La route `/job/v1/export` expose **la totalité** des offres actives en un
seul appel. C'est la bonne primitive pour construire une liste exhaustive.

Fonctionnement (vérifié dans le code source de l'API, dépôts
mission-apprentissage/api-apprentissage et /labonnealternance) :
  1. GET /job/v1/export  →  {"url": "<lien S3 signé>", "lastUpdate": "..."}
     Le lien n'est **valable que 2 minutes** : on télécharge immédiatement.
  2. Le fichier est un **tableau JSON plat** `[offre, offre, ...]`, chaque
     élément au même format que la réponse de la route de recherche.
     Il contient les offres `status=Active` et `multicast=true` de TOUS les
     partenaires… y compris les « recruteurs_lba » : des entreprises
     ouvertes aux candidatures spontanées, sans offre réelle, dont
     l'intitulé vaut littéralement « recruteurs_lba » (~18 700 lignes, soit
     98,8 % du run du 2026-08-05, qui a dû être annulé). Le fichier
     (export-jobs-to-s3-v2.ts) les concatène explicitement après les
     offres : on les écarte sur `identifier.partner_label`.
  3. Le fichier est régénéré **une fois par jour à 3h du matin, heure de
     Paris** — d'où le cron du workflow calé après cette heure-là.
  4. Débit limité à **2 appels par minute** : un run quotidien = 1 appel.

Le fichier étant volumineux (plusieurs centaines de Mo, indenté à la
génération), il est téléchargé en streaming vers un fichier temporaire
puis parsé **incrémentalement** avec `ijson` : la mémoire reste bornée
quel que soit le volume, contrairement à un `json.load()` qui chargerait
tout d'un coup.

Le filtrage par métier (codes ROME) se fait donc côté client, sur
`offer.rome_codes` — cf. `config.json`.

⚠️ Codes ROME v4 : depuis la refonte ROME 4.0 de France Travail, chaque
ancien code informatique (M1805, M1802...) est devenu un code « parent »
de dizaines de métiers plus précis (M1855 Développeur web, M1811 Data
engineer, M1844 Analyste en cybersécurité...). Les offres portent le code
précis. Filtrer sur les 6 parents seuls ne ramenait qu'une poignée
d'offres, sur la recherche comme sur l'export : config.json liste donc
tous les codes enfants (référentiel v4.60, cf. son champ `_doc`).

Identité des offres : `ville` reprend `workplace.location.address` TEL
QUEL, comme le connecteur de recherche. L'id (`make_id`) en dépend : en
extraire la commune changerait l'id de chaque offre déjà en store, qui
serait alors fermée puis recréée (fausses fermetures dans l'archive,
`first_seen` remis à zéro). Le run du 2026-08-05 a fermé ainsi les 155
offres existantes. Le nettoyage d'affichage relève du rendu, pas de
l'identité.

⚠️ Prérequis : jeton créé sur https://api.apprentissage.beta.gouv.fr,
   stocké dans le secret GitHub `LBA_API_KEY`.

Contrat du connecteur (commun à toutes les sources) :
  - `async fetch(config, client) -> list[Offre]` ;
  - une offre isolée malformée est ignorée (on saute, on ne lève pas) ;
  - une erreur HTTP/réseau remonte : le pipeline l'attrape et marque la
    source en échec, ce qui empêche toute fermeture d'offres ce jour-là.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Iterator
from typing import Any

import httpx
import ijson

from ..models import Offre, make_id

BASE_URL = os.environ.get("LBA_BASE_URL", "https://api.apprentissage.beta.gouv.fr/api")
EXPORT_PATH = "/job/v1/export"

SOURCE = "lba"

# Permet de tester le parsing sur un fichier local, sans jeton ni réseau :
#   LBA_EXPORT_FILE=/chemin/export.json python main.py update
ENV_FICHIER_LOCAL = "LBA_EXPORT_FILE"

# Le lien S3 n'est valable que 2 minutes → on ne traîne pas.
TIMEOUT_DOWNLOAD = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)

# Statuts d'offre retenus (l'export ne devrait contenir que « Active »,
# on reste défensif au cas où le contenu évoluerait).
STATUTS_RETENUS = {"active"}

# Entreprises à candidature spontanée, sans offre : présentes dans l'export,
# jamais dans la liste (cf. docstring du module).
PARTENAIRES_EXCLUS = {"recruteurs_lba"}


# ───────────────────────────────────────────────────────── extraction


def _chemin(donnees: Any, chemin: str) -> Any:
    """Lit 'a.b.c' dans des dicts imbriqués ; None si absent ou vide."""
    courant = donnees
    for cle in chemin.split("."):
        if not isinstance(courant, dict):
            return None
        courant = courant.get(cle)
        if courant is None:
            return None
    return courant if courant not in ("", []) else None


def _premier(donnees: Any, *chemins: str) -> Any:
    for chemin in chemins:
        valeur = _chemin(donnees, chemin)
        if valeur is not None:
            return valeur
    return None


def _contrat(types: Any) -> str:
    """contract.type est une liste (« Apprentissage », « Professionnalisation »)."""
    if isinstance(types, str):
        types = [types]
    if not isinstance(types, list):
        return "apprentissage"
    valeurs = {str(t).strip().lower() for t in types if t}
    if not valeurs:
        return "apprentissage"
    if valeurs == {"professionnalisation"}:
        return "professionnalisation"
    if len(valeurs) > 1:
        return "indifferent"
    return "apprentissage"


def vers_offre(brut: dict) -> Offre | None:
    """Normalise une offre du format LBA v3 vers notre modèle.

    Retourne None si l'offre est inexploitable pour une liste
    (pas d'intitulé, pas d'entreprise, ou statut non actif).
    """
    if not isinstance(brut, dict):
        return None

    partenaire = str(_chemin(brut, "identifier.partner_label") or "").lower()
    intitule = _chemin(brut, "offer.title")
    if partenaire in PARTENAIRES_EXCLUS or str(intitule).lower() in PARTENAIRES_EXCLUS:
        return None

    statut = _chemin(brut, "offer.status")
    if statut is not None and str(statut).lower() not in STATUTS_RETENUS:
        return None

    entreprise = _premier(brut, "workplace.name", "workplace.brand", "workplace.legal_name")
    if not intitule or not entreprise:
        return None

    # Brut, volontairement : l'id en dépend (cf. docstring du module).
    adresse = _chemin(brut, "workplace.location.address")
    ville = str(adresse).strip() if adresse else "France entière"

    date_pub = _chemin(brut, "offer.publication.creation")
    date_pub = str(date_pub)[:10] if isinstance(date_pub, str) and len(date_pub) >= 10 else None

    date_debut = _chemin(brut, "contract.start")
    date_debut = (
        str(date_debut)[:10] if isinstance(date_debut, str) and len(date_debut) >= 10 else None
    )

    duree = _chemin(brut, "contract.duration")
    try:
        duree = int(duree) if duree is not None else None
    except (TypeError, ValueError):
        duree = None

    remote = str(_chemin(brut, "contract.remote") or "").lower()
    teletravail = {"hybrid": "hybride", "remote": "total"}.get(remote, "")

    niveau = _chemin(brut, "offer.target_diploma.label") or ""
    description = _chemin(brut, "offer.description")
    url = _chemin(brut, "apply.url") or ""

    entreprise = str(entreprise).strip()
    intitule = str(intitule).strip()

    return Offre(
        id=make_id(SOURCE, entreprise, intitule, ville),
        source=SOURCE,
        entreprise=entreprise,
        intitule=intitule,
        ville=ville,
        contrat=_contrat(_chemin(brut, "contract.type")),
        niveau=str(niveau).strip(),
        duree_mois=duree,
        teletravail=teletravail,
        url=str(url),
        date_publication=date_pub,
        date_debut=date_debut,
        description=description if isinstance(description, str) else None,
    )


def _concerne_nos_metiers(brut: dict, romes: set[str]) -> bool:
    """Filtre métier côté client : l'export n'est pas filtrable côté serveur."""
    if not romes:
        return True
    codes = _chemin(brut, "offer.rome_codes") or []
    if isinstance(codes, str):
        codes = [codes]
    return any(str(code).strip().upper() in romes for code in codes)


# ───────────────────────────────────────────────────────── streaming


def _parser_fichier(chemin_fichier: str, romes: set[str]) -> list[Offre]:
    """Parse incrémental du tableau JSON : mémoire bornée quel que soit
    le volume du fichier (plusieurs centaines de Mo).

    Zéro offre retenue sur un export non vide = schéma changé ou filtre
    cassé, pas « plus aucune alternance tech en France » : on lève, le
    pipeline marque la source en échec et ne ferme rien."""
    offres: list[Offre] = []
    lus = 0
    with open(chemin_fichier, "rb") as f:
        elements: Iterator[Any] = ijson.items(f, "item")
        for brut in elements:
            lus += 1
            if not isinstance(brut, dict):
                continue
            if not _concerne_nos_metiers(brut, romes):
                continue
            offre = vers_offre(brut)
            if offre is not None:
                offres.append(offre)
    if lus and not offres:
        raise RuntimeError(
            f"export LBA : {lus} éléments lus, 0 offre retenue — "
            "schéma ou codes ROME à vérifier"
        )
    print(f"[INFO] export LBA : {lus} éléments lus, {len(offres)} offres retenues")
    return offres


async def _telecharger(url: str, client: httpx.AsyncClient, chemin_fichier: str) -> int:
    """Télécharge le fichier d'export en streaming. Retourne sa taille."""
    taille = 0
    async with client.stream("GET", url, timeout=TIMEOUT_DOWNLOAD) as reponse:
        reponse.raise_for_status()
        with open(chemin_fichier, "wb") as f:
            async for morceau in reponse.aiter_bytes(chunk_size=1 << 20):
                f.write(morceau)
                taille += len(morceau)
    return taille


async def fetch(config: dict, client: httpx.AsyncClient) -> list[Offre]:
    """Récupère l'export complet, le filtre sur nos codes ROME et le
    normalise. Un seul appel API par run."""
    romes = {str(r).strip().upper() for r in config.get("romes", []) if r}

    fichier_local = os.environ.get(ENV_FICHIER_LOCAL)
    if fichier_local:
        # Mode hors-ligne (tests, développement sans jeton).
        return await asyncio.to_thread(_parser_fichier, fichier_local, romes)

    api_key = os.environ.get("LBA_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "LBA_API_KEY absent : créez un jeton sur "
            "https://api.apprentissage.beta.gouv.fr puis exportez-le, ou "
            f"utilisez {ENV_FICHIER_LOCAL} pour parser un fichier local."
        )

    reponse = await client.get(
        BASE_URL + EXPORT_PATH,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=60,
    )
    reponse.raise_for_status()
    enveloppe = reponse.json()
    url_export = enveloppe.get("url")
    if not url_export:
        raise RuntimeError(f"Réponse d'export inattendue : {enveloppe!r}")
    print(f"[INFO] export LBA du {enveloppe.get('lastUpdate', '?')}")

    # Le lien signé expire au bout de 2 minutes : on enchaîne sans attendre.
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        chemin_fichier = tmp.name
    try:
        taille = await _telecharger(url_export, client, chemin_fichier)
        print(f"[INFO] export téléchargé : {taille / 1_048_576:.1f} Mo")
        return await asyncio.to_thread(_parser_fichier, chemin_fichier, romes)
    finally:
        try:
            os.unlink(chemin_fichier)
        except OSError:
            pass
