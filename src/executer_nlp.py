"""Enrichit les extractions unifiées sans modifier leur fichier d'origine."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from nlp_btp import analyser_texte


RACINE_PROJET = Path(__file__).resolve().parents[1]
ENTREE = RACINE_PROJET / "resultats_unifies.json"
SORTIE = RACINE_PROJET / "resultats_nlp.json"


def enrichir_resultats() -> list[dict]:
    if not ENTREE.exists():
        raise FileNotFoundError(f"Résultats unifiés introuvables : {ENTREE}")

    elements = json.loads(ENTREE.read_text(encoding="utf-8"))
    enrichis: list[dict] = []
    compteurs: Counter[str] = Counter()

    for element in elements:
        copie = dict(element)
        donnees = element.get("donnees", {})
        texte = " ".join(
            partie for partie in (
                str(element.get("libelle") or ""),
                str(donnees.get("texte_source") or ""),
            ) if partie
        )
        analyse = analyser_texte(texte)
        copie["analyse_nlp"] = analyse
        enrichis.append(copie)
        for categorie, valeurs in analyse["entites"].items():
            compteurs[categorie] += len(valeurs)

    SORTIE.write_text(json.dumps(enrichis, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 72)
    print("ENRICHISSEMENT NLP BTP - LOCAL ET TRAÇABLE")
    print("=" * 72)
    print(f"Éléments analysés : {len(enrichis)}")
    print("Entités reconnues :")
    for categorie, nombre in sorted(compteurs.items()):
        print(f"  - {categorie}: {nombre}")
    print(f"Résultat : {SORTIE}")
    print("Le fichier resultats_unifies.json n'a pas été modifié.")
    return enrichis


if __name__ == "__main__":
    enrichir_resultats()

