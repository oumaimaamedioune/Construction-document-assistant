"""Calcule les métriques uniquement sur les annotations validées manuellement."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path


RACINE = Path(__file__).resolve().parents[1]
DOSSIER_EVALUATION = RACINE / "evaluation"


def normaliser(valeur):
    if valeur is None:
        return None
    if isinstance(valeur, (int, float)):
        return round(float(valeur), 4)
    texte = unicodedata.normalize("NFKD", str(valeur)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texte.casefold().strip())


def valeurs_entites(entites: dict) -> set[tuple[str, str]]:
    return {
        (categorie, normaliser(valeur))
        for categorie, valeurs in entites.items()
        for valeur in valeurs
    }


def scores(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else 0.0
    rappel = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * rappel / (precision + rappel) if precision + rappel else 0.0
    return {
        "vrais_positifs": tp,
        "faux_positifs": fp,
        "faux_negatifs": fn,
        "precision": round(precision, 4),
        "rappel": round(rappel, 4),
        "f1": round(f1, 4),
    }


def evaluer_cctp(elements: list[dict]) -> dict:
    tp = fp = fn = 0
    for element in elements:
        predits = valeurs_entites(element["prediction"].get("entites", {}))
        attendus = valeurs_entites(element["attendu"].get("entites", {}))
        tp += len(predits & attendus)
        fp += len(predits - attendus)
        fn += len(attendus - predits)
    return scores(tp, fp, fn)


def evaluer_dqe(elements: list[dict]) -> dict:
    champs = ("numero_poste", "designation", "unite", "quantite", "prix_unitaire", "prix_total")
    corrects = total = 0
    par_champ = {}
    for champ in champs:
        champ_correct = champ_total = 0
        for element in elements:
            attendu = element["attendu"].get(champ)
            if attendu is None:
                continue
            champ_total += 1
            champ_correct += normaliser(element["prediction"].get(champ)) == normaliser(attendu)
        par_champ[champ] = {
            "corrects": champ_correct,
            "total_annotes": champ_total,
            "exactitude": round(champ_correct / champ_total, 4) if champ_total else None,
        }
        corrects += champ_correct
        total += champ_total
    return {
        "corrects": corrects,
        "total_annotes": total,
        "exactitude_globale": round(corrects / total, 4) if total else None,
        "par_champ": par_champ,
    }


def charger_valides(nom: str) -> tuple[list[dict], int]:
    chemin = DOSSIER_EVALUATION / nom
    elements = json.loads(chemin.read_text(encoding="utf-8"))
    valides = [e for e in elements if e.get("statut_annotation") == "valide"]
    return valides, len(elements)


def main() -> None:
    cctp, total_cctp = charger_valides("annotations_cctp.json")
    dqe, total_dqe = charger_valides("annotations_dqe.json")
    rapport = {
        "avertissement": "Les métriques portent uniquement sur les éléments validés manuellement.",
        "annotations": {
            "cctp": {"validees": len(cctp), "total": total_cctp},
            "dqe": {"validees": len(dqe), "total": total_dqe},
        },
        "metriques_cctp": evaluer_cctp(cctp) if cctp else None,
        "metriques_dqe": evaluer_dqe(dqe) if dqe else None,
    }
    chemin = DOSSIER_EVALUATION / "rapport_evaluation.json"
    chemin.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    if not cctp and not dqe:
        print("\nAucune métrique calculée : les annotations doivent d'abord être vérifiées.")


if __name__ == "__main__":
    main()
