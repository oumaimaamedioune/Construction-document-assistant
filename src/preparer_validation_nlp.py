"""Prépare un échantillon représentatif pour la validation humaine du NLP."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


RACINE = Path(__file__).resolve().parents[1]
ENTREE = RACINE / "resultats_nlp.json"
SORTIE = RACINE / "evaluation" / "validation_nlp.json"
NOMBRE_PAR_DOCUMENT = 4
NOMBRE_CIBLE = 50


def nombre_entites(element: dict) -> int:
    entites = element.get("analyse_nlp", {}).get("entites", {})
    return sum(len(valeurs) for valeurs in entites.values())


def choisir_echantillon(elements: list[dict], nombre_par_document: int = NOMBRE_PAR_DOCUMENT) -> list[dict]:
    """Choisit des cas riches et des cas sans entité dans chaque document."""
    par_document: defaultdict[tuple[str, str], list[dict]] = defaultdict(list)
    for element in elements:
        cle = (element.get("type_document", ""), element.get("fichier_source", ""))
        par_document[cle].append(element)

    selection: list[dict] = []
    for cle in sorted(par_document, key=lambda valeur: (valeur[0], valeur[1].casefold())):
        candidats = par_document[cle]
        avec_entites = sorted(
            (element for element in candidats if nombre_entites(element) > 0),
            key=lambda element: (-nombre_entites(element), element.get("page") or 0),
        )
        sans_entites = sorted(
            (element for element in candidats if nombre_entites(element) == 0),
            key=lambda element: element.get("page") or 0,
        )

        retenus = avec_entites[: max(0, nombre_par_document - 1)]
        if sans_entites and len(retenus) < nombre_par_document:
            retenus.append(sans_entites[0])
        for element in avec_entites[len(retenus):] + sans_entites[1:]:
            if len(retenus) >= nombre_par_document:
                break
            if element not in retenus:
                retenus.append(element)
        selection.extend(retenus)
    return selection


def construire_annotations(elements: list[dict]) -> list[dict]:
    annotations = []
    for numero, element in enumerate(elements, start=1):
        donnees = element.get("donnees", {})
        annotations.append(
            {
                "id_validation": numero,
                "type_document": element.get("type_document"),
                "fichier_source": element.get("fichier_source"),
                "page": element.get("page"),
                "libelle": element.get("libelle"),
                "texte_source": donnees.get("texte_source") or "",
                "donnees_source": donnees,
                "predictions_nlp": element.get("analyse_nlp", {}).get("entites", {}),
                "validation": {
                    "statut": "a_valider",
                    "predictions_incorrectes": {},
                    "entites_manquantes": {},
                    "commentaire": "",
                },
            }
        )
    return annotations


def cle_annotation(element: dict) -> tuple:
    donnees = element.get("donnees", {})
    return (
        element.get("type_document"),
        element.get("fichier_source"),
        element.get("page"),
        element.get("libelle"),
        element.get("texte_source", donnees.get("texte_source") or ""),
    )


def agrandir_annotations(
    existantes: list[dict], elements: list[dict], nombre_cible: int = NOMBRE_CIBLE
) -> list[dict]:
    """Complète l'échantillon sans modifier les validations déjà saisies."""
    resultat = list(existantes)
    sources = {cle_annotation(element): element for element in elements}
    for annotation in resultat:
        source = sources.get(cle_annotation(annotation))
        if source:
            annotation["donnees_source"] = source.get("donnees", {})
            annotation["predictions_nlp"] = source.get("analyse_nlp", {}).get("entites", {})
    cles_existantes = {cle_annotation(element) for element in resultat}
    if len(resultat) >= nombre_cible:
        return resultat

    candidats = choisir_echantillon(elements, nombre_par_document=nombre_cible)
    par_document: defaultdict[tuple[str, str], list[dict]] = defaultdict(list)
    for element in candidats:
        cle_document = (
            element.get("type_document", ""), element.get("fichier_source", "")
        )
        if cle_annotation(element) not in cles_existantes:
            par_document[cle_document].append(element)

    groupes = [par_document[cle] for cle in sorted(par_document)]
    index = 0
    while len(resultat) < nombre_cible and any(groupes):
        groupe = groupes[index % len(groupes)]
        index += 1
        if not groupe:
            continue
        element = groupe.pop(0)
        nouvelle = construire_annotations([element])[0]
        nouvelle["id_validation"] = len(resultat) + 1
        resultat.append(nouvelle)
        cles_existantes.add(cle_annotation(element))
    return resultat


def preparer_validation(forcer: bool = False, nombre_cible: int = NOMBRE_CIBLE) -> list[dict]:
    if not ENTREE.exists():
        raise FileNotFoundError(f"Lancez d'abord : python src\\executer_nlp.py ({ENTREE} absent)")
    if SORTIE.exists() and not forcer:
        existantes = json.loads(SORTIE.read_text(encoding="utf-8"))
        elements = json.loads(ENTREE.read_text(encoding="utf-8"))
        annotations = agrandir_annotations(existantes, elements, nombre_cible)
        SORTIE.write_text(
            json.dumps(annotations, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Validation mise à jour : {SORTIE}")
        print(f"Éléments conservés : {len(existantes)} (aucune annotation écrasée)")
        print(f"Nouvel effectif : {len(annotations)}")
        return annotations

    elements = json.loads(ENTREE.read_text(encoding="utf-8"))
    selection = choisir_echantillon(elements, nombre_par_document=nombre_cible)
    selection = selection[:nombre_cible]
    annotations = construire_annotations(selection)
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(annotations, ensure_ascii=False, indent=2), encoding="utf-8")

    documents = {annotation["fichier_source"] for annotation in annotations}
    avec_predictions = sum(bool(a["predictions_nlp"]) for a in annotations)
    print("=" * 72)
    print("PRÉPARATION DE LA VALIDATION NLP")
    print("=" * 72)
    print(f"Documents représentés : {len(documents)}")
    print(f"Éléments sélectionnés : {len(annotations)}")
    print(f"Avec prédictions NLP : {avec_predictions}")
    print(f"Sans prédiction (contrôle des oublis) : {len(annotations) - avec_predictions}")
    print(f"Fichier : {SORTIE}")
    return annotations


if __name__ == "__main__":
    analyseur = argparse.ArgumentParser()
    analyseur.add_argument(
        "--forcer", action="store_true",
        help="Recrée le fichier et efface les validations existantes.",
    )
    arguments = analyseur.parse_args()
    preparer_validation(forcer=arguments.forcer)
