# Contribuer

## Ajouter ou signaler une offre (sans coder)

Passez par les [formulaires d'issues](../../issues/new/choose). **Ne proposez
pas de PR sur `README.md` ni `data/listings.json`** : ces fichiers sont
générés/gérés par les workflows et votre PR créerait des conflits permanents.
Un mainteneur pose le label `contribution-approuvee` sur votre issue, et un
bot injecte l'offre automatiquement.

## Contribuer au code du moteur

```bash
git clone <ce repo> && cd alternances-tech-2026
pip install -r requirements-dev.txt
pytest                    # la suite doit passer
python main.py render     # génération locale du README
python main.py validate   # intégrité des données
```

Le fetch réel nécessite un jeton API (gratuit, usage non lucratif) :
créez-le sur https://api.apprentissage.beta.gouv.fr puis :

```bash
LBA_API_KEY=xxx python main.py update
```

### Où toucher quoi

| Vous voulez... | Fichier |
| --- | --- |
| Ajouter une source d'offres | `src/alternance_engine/connectors/` (+ 1 ligne dans `pipeline.SOURCES` et `dedupe.PRIORITE_SOURCE`) |
| Corriger une catégorisation | `src/alternance_engine/categorize.py` (règles lisibles, ordre = priorité) |
| Changer les métiers suivis | `config.json` (codes ROME) |
| Modifier le texte du README | `templates/README.template.md` (jamais `README.md`) |
| Modifier les colonnes des tables | `src/alternance_engine/render.py` |

Toute PR passe la CI (`pytest` + `validate` + rendu à blanc).
