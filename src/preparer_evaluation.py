"""Prépare un échantillon à annoter depuis les résultats du corpus validé.

Les fichiers d'annotation existants ne sont jamais écrasés afin de préserver
le travail de validation humaine.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


RACINE = Path(__file__).resolve().parents[1]
DOSSIER_EVALUATION = RACINE / "evaluation"


def lire_json(chemin: Path):
    return json.loads(chemin.read_text(encoding="utf-8"))


def echantillonner_par_fichier(elements: list[dict], nombre: int) -> list[dict]:
    """Sélection déterministe répartie entre début, milieu et fin."""
    groupes: defaultdict[str, list[dict]] = defaultdict(list)
    for element in elements:
        groupes[element["fichier_source"]].append(element)

    selection: list[dict] = []
    for nom_fichier in sorted(groupes):
        groupe = groupes[nom_fichier]
        if len(groupe) <= nombre:
            selection.extend(groupe)
            continue
        indices = sorted({round(i * (len(groupe) - 1) / (nombre - 1)) for i in range(nombre)})
        selection.extend(groupe[index] for index in indices)
    return selection


def construire_cctp() -> list[dict]:
    donnees = lire_json(RACINE / "resultats_extraction.json")
    elements = [bloc for blocs in donnees.values() for bloc in blocs]
    selection = echantillonner_par_fichier(elements, 5)
    return [
        {
            "id": f"CCTP-{index:03d}",
            "statut_annotation": "a_annoter",
            "fichier_source": bloc["fichier_source"],
            "page": bloc["page"],
            "section": bloc.get("section"),
            "texte_source": bloc["texte_source"],
            "prediction": {
                "materiau": bloc.get("materiau"),
                "entites": bloc.get("entites", {}),
            },
            "attendu": {"materiau": None, "entites": {}},
            "commentaire": "",
        }
        for index, bloc in enumerate(selection, start=1)
    ]


def construire_dqe() -> list[dict]:
    elements = lire_json(RACINE / "resultats_dqe.json")
    selection = echantillonner_par_fichier(elements, 6)
    champs = ("numero_poste", "designation", "unite", "quantite", "prix_unitaire", "prix_total")
    return [
        {
            "id": f"DQE-{index:03d}",
            "statut_annotation": "a_annoter",
            "fichier_source": ligne["fichier_source"],
            "page": ligne["page"],
            "texte_source": ligne.get("texte_source", ""),
            "prediction": {champ: ligne.get(champ) for champ in champs},
            "attendu": {champ: None for champ in champs},
            "commentaire": "",
        }
        for index, ligne in enumerate(selection, start=1)
    ]


def ecrire_sans_ecraser(chemin: Path, contenu: list[dict]) -> bool:
    if chemin.exists():
        print(f"[CONSERVÉ] {chemin.name} existe déjà : aucune modification")
        return False
    chemin.write_text(json.dumps(contenu, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[CRÉÉ] {chemin.name} : {len(contenu)} élément(s) à annoter")
    return True


def main() -> None:
    DOSSIER_EVALUATION.mkdir(exist_ok=True)
    ecrire_sans_ecraser(DOSSIER_EVALUATION / "annotations_cctp.json", construire_cctp())
    ecrire_sans_ecraser(DOSSIER_EVALUATION / "annotations_dqe.json", construire_dqe())
    print("\nRègle : mettre statut_annotation à 'valide' seulement après vérification dans le PDF.")


if __name__ == "__main__":
    main()
