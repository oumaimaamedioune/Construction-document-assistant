"""Actualise les prédictions des annotations sans toucher aux réponses attendues."""

from __future__ import annotations

import json
from pathlib import Path


RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "evaluation"


def rafraichir_cctp() -> int:
    chemin = DOSSIER / "annotations_cctp.json"
    annotations = json.loads(chemin.read_text(encoding="utf-8"))
    resultats_bruts = json.loads((RACINE / "resultats_extraction.json").read_text(encoding="utf-8"))
    resultats = [bloc for blocs in resultats_bruts.values() for bloc in blocs]
    nombre = 0
    for annotation in annotations:
        correspondance = next(
            (
                bloc for bloc in resultats
                if bloc["fichier_source"] == annotation["fichier_source"]
                and bloc["page"] == annotation["page"]
                and bloc["texte_source"] == annotation["texte_source"]
            ),
            None,
        )
        if correspondance:
            annotation["prediction"] = {
                "materiau": correspondance.get("materiau"),
                "entites": correspondance.get("entites", {}),
            }
            nombre += 1
        elif annotation.get("statut_annotation") == "valide":
            # L'absence d'une ancienne prédiction après correction est un vrai
            # résultat vide, et non une raison de supprimer l'annotation.
            annotation["prediction"] = {"materiau": None, "entites": {}}
            nombre += 1
    chemin.write_text(json.dumps(annotations, ensure_ascii=False, indent=2), encoding="utf-8")
    return nombre


def rafraichir_dqe() -> int:
    chemin = DOSSIER / "annotations_dqe.json"
    annotations = json.loads(chemin.read_text(encoding="utf-8"))
    resultats = json.loads((RACINE / "resultats_dqe.json").read_text(encoding="utf-8"))
    champs = ("numero_poste", "designation", "unite", "quantite", "prix_unitaire", "prix_total")
    nombre = 0
    for annotation in annotations:
        numero = annotation.get("attendu", {}).get("numero_poste") or annotation["prediction"].get("numero_poste")
        correspondance = next(
            (
                poste for poste in resultats
                if poste["fichier_source"] == annotation["fichier_source"]
                and poste["page"] == annotation["page"]
                and poste.get("numero_poste") == numero
            ),
            None,
        )
        if correspondance:
            annotation["prediction"] = {champ: correspondance.get(champ) for champ in champs}
            annotation["texte_source"] = correspondance.get("texte_source", annotation["texte_source"])
            nombre += 1
        elif annotation.get("statut_annotation") == "valide":
            annotation["prediction"] = {champ: None for champ in champs}
            nombre += 1
    chemin.write_text(json.dumps(annotations, ensure_ascii=False, indent=2), encoding="utf-8")
    return nombre


if __name__ == "__main__":
    print(f"CCTP actualisés : {rafraichir_cctp()}")
    print(f"DQE actualisés : {rafraichir_dqe()}")
