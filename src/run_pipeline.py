"""Point d'entrée unique du pipeline d'analyse documentaire BTP."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


RACINE_PROJET = Path(__file__).resolve().parents[1]
ETAPES = (
    ("Extraction CCTP", "extract_smart.py"),
    ("Extraction DQE", "extract_dqe.py"),
    ("Unification", "unifier_resultats.py"),
    ("Enrichissement NLP", "executer_nlp.py"),
    ("Rapprochement CCTP-DQE", "rapprocher_cctp_dqe.py"),
    ("Extraction des documents métier", "extract_documents_metier.py"),
    ("Mise à jour de la base SQLite", "initialiser_database.py"),
)


def compter_resultats() -> dict:
    bilan = {"cctp": 0, "dqe": 0, "total_unifie": 0}
    chemin_cctp = RACINE_PROJET / "resultats_extraction.json"
    chemin_dqe = RACINE_PROJET / "resultats_dqe.json"
    chemin_unifie = RACINE_PROJET / "resultats_unifies.json"
    chemin_rapprochement = RACINE_PROJET / "resultats_rapprochement.json"

    if chemin_cctp.exists():
        donnees = json.loads(chemin_cctp.read_text(encoding="utf-8"))
        bilan["cctp"] = sum(len(blocs) for blocs in donnees.values())
    if chemin_dqe.exists():
        donnees = json.loads(chemin_dqe.read_text(encoding="utf-8"))
        bilan["dqe"] = len(donnees)
        bilan["dqes_valides"] = sum(
            ligne.get("controle_calcul") == "valide" for ligne in donnees
        )
        bilan["dqes_a_verifier"] = sum(
            ligne.get("controle_calcul") != "valide" for ligne in donnees
        )
    if chemin_unifie.exists():
        bilan["total_unifie"] = len(json.loads(chemin_unifie.read_text(encoding="utf-8")))
    if chemin_rapprochement.exists():
        rapprochement = json.loads(chemin_rapprochement.read_text(encoding="utf-8"))
        bilan["rapprochement"] = rapprochement.get("statistiques", {})
    chemin_base = RACINE_PROJET / "instance" / "assistant_btp.db"
    if chemin_base.exists():
        from database import statistiques_tableau_de_bord

        bilan["base_sqlite"] = statistiques_tableau_de_bord(chemin_base)
    return bilan


def executer_pipeline() -> None:
    debut = time.perf_counter()
    rapport = {
        "date_execution": datetime.now().isoformat(timespec="seconds"),
        "statut": "succes",
        "etapes": [],
    }

    print("=" * 72)
    print("ASSISTANT BTP - PIPELINE COMPLET")
    print("=" * 72)

    for nom, script in ETAPES:
        print(f"\n>>> {nom}")
        debut_etape = time.perf_counter()
        resultat = subprocess.run(
            [sys.executable, str(Path(__file__).with_name(script))],
            cwd=RACINE_PROJET,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        duree = round(time.perf_counter() - debut_etape, 2)
        rapport["etapes"].append(
            {"nom": nom, "script": script, "statut": "succes" if resultat.returncode == 0 else "echec", "duree_secondes": duree}
        )
        if resultat.returncode != 0:
            rapport["statut"] = "echec"
            break

    rapport["duree_totale_secondes"] = round(time.perf_counter() - debut, 2)
    rapport["resultats"] = compter_resultats()
    chemin_rapport = RACINE_PROJET / "rapport_execution.json"
    chemin_rapport.write_text(json.dumps(rapport, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"Statut : {rapport['statut']}")
    print(f"Bilan : {rapport['resultats']}")
    print(f"Rapport : {chemin_rapport}")
    if rapport["statut"] != "succes":
        raise SystemExit(1)


if __name__ == "__main__":
    executer_pipeline()
