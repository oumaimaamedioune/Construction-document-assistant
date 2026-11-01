"""Calcule précision, rappel et F1 à partir des validations humaines."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from validation_nlp import CHEMIN_VALIDATION, charger_validations


RACINE = Path(__file__).resolve().parents[1]
CHEMIN_RAPPORT = RACINE / "evaluation" / "rapport_nlp.json"


def cle_valeur(valeur) -> str:
    return json.dumps(valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def calculer_scores(vrais_positifs: int, faux_positifs: int, faux_negatifs: int) -> dict:
    precision = vrais_positifs / (vrais_positifs + faux_positifs) if vrais_positifs + faux_positifs else 0.0
    rappel = vrais_positifs / (vrais_positifs + faux_negatifs) if vrais_positifs + faux_negatifs else 0.0
    f1 = 2 * precision * rappel / (precision + rappel) if precision + rappel else 0.0
    return {
        "vrais_positifs": vrais_positifs,
        "faux_positifs": faux_positifs,
        "faux_negatifs": faux_negatifs,
        "precision": round(precision, 4),
        "rappel": round(rappel, 4),
        "f1": round(f1, 4),
    }


def evaluer_annotations(annotations: list[dict]) -> dict:
    validees = [
        annotation for annotation in annotations
        if annotation.get("validation", {}).get("statut") in {"valide", "corrige"}
    ]
    compteurs = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})

    for annotation in validees:
        predictions = annotation.get("predictions_nlp", {})
        validation = annotation.get("validation", {})
        incorrectes = validation.get("predictions_incorrectes", {})
        manquantes = validation.get("entites_manquantes", {})
        categories = set(predictions) | set(incorrectes) | set(manquantes)

        for categorie in categories:
            valeurs_predites = {cle_valeur(v) for v in predictions.get(categorie, [])}
            valeurs_incorrectes = {cle_valeur(v) for v in incorrectes.get(categorie, [])}
            # Une valeur signalée comme incorrecte doit réellement provenir
            # des prédictions ; l'interface garantit normalement ce contrat.
            valeurs_incorrectes &= valeurs_predites
            compteurs[categorie]["tp"] += len(valeurs_predites - valeurs_incorrectes)
            compteurs[categorie]["fp"] += len(valeurs_incorrectes)
            compteurs[categorie]["fn"] += len(manquantes.get(categorie, []))

    par_categorie = {
        categorie: calculer_scores(valeurs["tp"], valeurs["fp"], valeurs["fn"])
        for categorie, valeurs in sorted(compteurs.items())
    }
    totaux = {
        nom: sum(valeurs[nom] for valeurs in compteurs.values())
        for nom in ("tp", "fp", "fn")
    }
    return {
        "statut": "final" if annotations and len(validees) == len(annotations) else "provisoire",
        "avancement": {
            "valides": len(validees),
            "total": len(annotations),
            "pourcentage": round(100 * len(validees) / len(annotations), 1) if annotations else 0.0,
        },
        "metriques_globales": calculer_scores(totaux["tp"], totaux["fp"], totaux["fn"]),
        "par_categorie": par_categorie,
        "avertissement": (
            "Métriques provisoires : terminer toutes les validations avant de conclure."
            if len(validees) != len(annotations)
            else "Métriques calculées sur la totalité de l'échantillon validé."
        ),
    }


def generer_rapport(
    chemin_validation: Path | str = CHEMIN_VALIDATION,
    chemin_rapport: Path | str = CHEMIN_RAPPORT,
) -> dict:
    annotations = charger_validations(chemin_validation)
    rapport = evaluer_annotations(annotations)
    Path(chemin_rapport).write_text(
        json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    avancement = rapport["avancement"]
    metriques = rapport["metriques_globales"]
    print("=" * 72)
    print("ÉVALUATION DE LA RECONNAISSANCE NLP")
    print("=" * 72)
    print(f"Statut : {rapport['statut']}")
    print(f"Avancement : {avancement['valides']} / {avancement['total']}")
    print(f"Précision : {100 * metriques['precision']:.1f} %")
    print(f"Rappel : {100 * metriques['rappel']:.1f} %")
    print(f"F1 : {100 * metriques['f1']:.1f} %")
    print(rapport["avertissement"])
    print(f"Rapport : {chemin_rapport}")
    return rapport


if __name__ == "__main__":
    generer_rapport()

