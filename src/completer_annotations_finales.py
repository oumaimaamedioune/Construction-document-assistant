"""Enregistre les annotations vérifiées visuellement dans les PDF sources.

Le script refuse de modifier les annotations déjà validées.
"""

from __future__ import annotations

import json
from pathlib import Path


RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "evaluation"

CCTP = {
    "CCTP-006": ({"diametre": ["diamètre 63mm"]}, "Diamètre du poteau correctement identifié."),
    "CCTP-007": ({"dimension": ["30 x 3 mm"]}, "Dimension du fer plat correctement identifiée."),
    "CCTP-008": ({"dosage": ["300 kg/m3"]}, "Dosage du béton correctement identifié."),
    "CCTP-009": ({}, "15 cm désigne un débord de treillis, pas une épaisseur."),
    "CCTP-010": ({"pourcentage": ["50 %"]}, "Proportion maximale correctement identifiée."),
    "CCTP-011": ({}, "40 cm désigne une profondeur de fondation, pas une épaisseur."),
    "CCTP-012": ({"epaisseur": ["épaisseur 1,25 mm"]}, "Épaisseur du bac acier correctement identifiée."),
    "CCTP-013": ({"grammage": ["250 g/m²"]}, "Grammage de l'armature polyester correctement identifié."),
    "CCTP-014": ({"masse_volumique": ["100kg/m3"]}, "Il s'agit de la masse volumique de la laine de roche, pas d'un dosage."),
    "CCTP-015": ({"resistance": ["7MPa"]}, "Résistance qc minimale correctement identifiée."),
    "CCTP-016": ({"diametre": ["ᴓ 26 cm"]}, "Diamètre du rouleau papier WC ; ce n'est pas une épaisseur."),
    "CCTP-017": ({"diametre": ["ᴓ 32 mm"]}, "Diamètre du tube inox ; ce n'est pas une épaisseur."),
    "CCTP-018": ({"epaisseur": ["Épaisseur minimale 1 mm"]}, "Épaisseur minimale du tube cuivre recuit."),
    "CCTP-019": ({"epaisseur": ["Épaisseur minimale 1 mm"]}, "Épaisseur minimale du tube cuivre écroui."),
    "CCTP-020": ({"diametre": ["diamètres inférieurs à 16 mm"]}, "16 mm est un seuil de diamètre, pas une épaisseur."),
}

DQE = {
    "DQE-006": {
        "numero_poste": "1.4",
        "designation": "Fourniture et pose de tuiles à emboîtement à relief en terre cuite y compris liteaux supports en bois massif, protection fongicide et insecticide, accessoires de fixation en métal inoxydable et y toute sujétion de pose",
        "unite": "m²", "quantite": 344, "prix_unitaire": None, "prix_total": None,
    },
    "DQE-007": {
        "numero_poste": "1.1", "designation": "Installation et repli de chantier",
        "unite": "Ens.", "quantite": 1, "prix_unitaire": 300000, "prix_total": 300000,
    },
    "DQE-008": {
        "numero_poste": "3.4", "designation": "Béton armé pour poteaux dosé 350 kg/m3",
        "unite": "m3", "quantite": 6.19, "prix_unitaire": 110000, "prix_total": 680900,
    },
    "DQE-009": {
        "numero_poste": "3.13", "designation": "Fondation et soubassement en parpains pleins de 0,15m",
        "unite": "m²", "quantite": 141.24, "prix_unitaire": 6000, "prix_total": 847440,
    },
    "DQE-010": {
        "numero_poste": "4.3", "designation": "Enduit de finition des placards",
        "unite": "m²", "quantite": 42.67, "prix_unitaire": 1700, "prix_total": 72539,
    },
    "DQE-011": {
        "numero_poste": "6.1",
        "designation": "Fourniture et pose de 3 fenêtres en panneaux pleins de 1,2m x 1,2 m avec barreaux de défense en fers de 16 mm espacés de 15 cm et protégés par des gaines plastiques",
        "unite": "U", "quantite": 3, "prix_unitaire": 105000, "prix_total": 315000,
    },
    "DQE-012": {
        "numero_poste": "9.1",
        "designation": "Fourniture et pose d'une plaque d'identification de l'ouvrage avec écriture en relief",
        "unite": "U", "quantite": 1, "prix_unitaire": 300000, "prix_total": 300000,
    },
}


def completer_cctp() -> int:
    chemin = DOSSIER / "annotations_cctp.json"
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    nombre = 0
    for annotation in donnees:
        if annotation["id"] not in CCTP:
            continue
        if annotation["statut_annotation"] == "valide":
            raise RuntimeError(f"Refus d'écraser {annotation['id']} déjà validée")
        entites, commentaire = CCTP[annotation["id"]]
        annotation["attendu"] = {
            "materiau": annotation["prediction"].get("materiau"),
            "entites": entites,
        }
        annotation["commentaire"] = commentaire
        annotation["statut_annotation"] = "valide"
        nombre += 1
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")
    return nombre


def completer_dqe() -> int:
    chemin = DOSSIER / "annotations_dqe.json"
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    nombre = 0
    for annotation in donnees:
        if annotation["id"] not in DQE:
            continue
        if annotation["statut_annotation"] == "valide":
            raise RuntimeError(f"Refus d'écraser {annotation['id']} déjà validée")
        annotation["attendu"] = DQE[annotation["id"]]
        annotation["commentaire"] = "Valeurs vérifiées visuellement dans le tableau du PDF."
        annotation["statut_annotation"] = "valide"
        nombre += 1
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")
    return nombre


if __name__ == "__main__":
    print(f"Annotations CCTP ajoutées : {completer_cctp()}")
    print(f"Annotations DQE ajoutées : {completer_dqe()}")
