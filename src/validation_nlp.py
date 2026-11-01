"""Lecture et sauvegarde sécurisée des validations humaines du NLP."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


RACINE = Path(__file__).resolve().parents[1]
CHEMIN_VALIDATION = RACINE / "evaluation" / "validation_nlp.json"


def charger_validations(chemin: Path | str = CHEMIN_VALIDATION) -> list[dict]:
    fichier = Path(chemin)
    if not fichier.exists():
        return []
    return json.loads(fichier.read_text(encoding="utf-8"))


def parser_entites_manquantes(texte: str) -> dict[str, list[str]]:
    """Convertit ``categorie: valeur 1; valeur 2`` en dictionnaire."""
    resultat: dict[str, list[str]] = {}
    for numero, ligne in enumerate(texte.splitlines(), start=1):
        ligne = ligne.strip()
        if not ligne:
            continue
        if ":" not in ligne:
            raise ValueError(f"Ligne {numero} : utilisez le format categorie: valeur")
        categorie, valeurs = ligne.split(":", 1)
        categorie = categorie.strip()
        valeurs_nettoyees = [valeur.strip() for valeur in valeurs.split(";") if valeur.strip()]
        if not categorie or not valeurs_nettoyees:
            raise ValueError(f"Ligne {numero} incomplète")
        resultat[categorie] = valeurs_nettoyees
    return resultat


def formater_entites_manquantes(entites: dict) -> str:
    return "\n".join(
        f"{categorie}: {'; '.join(map(str, valeurs))}"
        for categorie, valeurs in entites.items()
    )


def construire_entites_corrigees(
    predictions: dict,
    predictions_incorrectes: dict,
    entites_manquantes: dict,
) -> dict:
    """Produit le résultat validé sans modifier les prédictions NLP originales."""

    def cle(valeur) -> str:
        return json.dumps(
            valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    resultat: dict[str, list] = {}
    categories = set(predictions) | set(entites_manquantes)
    for categorie in categories:
        valeurs_incorrectes = {
            cle(valeur) for valeur in predictions_incorrectes.get(categorie, [])
        }
        valeurs = [
            valeur for valeur in predictions.get(categorie, [])
            if cle(valeur) not in valeurs_incorrectes
        ]
        valeurs_connues = {cle(valeur) for valeur in valeurs}
        for valeur in entites_manquantes.get(categorie, []):
            if cle(valeur) not in valeurs_connues:
                valeurs.append(valeur)
                valeurs_connues.add(cle(valeur))
        if valeurs:
            resultat[categorie] = valeurs
    return resultat


def sauvegarder_validation(
    id_validation: int,
    predictions_incorrectes: dict,
    entites_manquantes: dict,
    commentaire: str = "",
    chemin: Path | str = CHEMIN_VALIDATION,
    autoriser_effacement: bool = False,
) -> dict:
    """Sauvegarde atomiquement un contrôle humain et conserve les autres."""
    fichier = Path(chemin)
    validations = charger_validations(fichier)
    annotation = next(
        (element for element in validations if element["id_validation"] == id_validation), None
    )
    if annotation is None:
        raise KeyError(f"Validation {id_validation} introuvable")
    ancienne_validation = annotation.get("validation", {})
    avait_corrections = bool(
        ancienne_validation.get("predictions_incorrectes")
        or ancienne_validation.get("entites_manquantes")
    )
    if avait_corrections and not predictions_incorrectes and not entites_manquantes and not autoriser_effacement:
        raise ValueError(
            "Cette validation contient déjà des corrections. "
            "Confirmez explicitement leur suppression pour la rendre valide."
        )
    statut = "corrige" if predictions_incorrectes or entites_manquantes else "valide"
    entites_corrigees = construire_entites_corrigees(
        annotation.get("predictions_nlp", {}),
        predictions_incorrectes,
        entites_manquantes,
    )
    annotation["validation"] = {
        "statut": statut,
        "predictions_incorrectes": predictions_incorrectes,
        "entites_manquantes": entites_manquantes,
        "entites_corrigees": entites_corrigees,
        "commentaire": commentaire.strip(),
        "date_validation": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    temporaire = fichier.with_suffix(fichier.suffix + ".tmp")
    temporaire.write_text(json.dumps(validations, ensure_ascii=False, indent=2), encoding="utf-8")
    temporaire.replace(fichier)
    return annotation
