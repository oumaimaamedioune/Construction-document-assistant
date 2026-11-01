"""Commande simple pour initialiser et remplir la base locale."""

import json

from database import (
    importer_analyses_nlp,
    importer_corpus_et_resultats,
    importer_extractions_metier,
    importer_rapprochements,
    statistiques_tableau_de_bord,
)


if __name__ == "__main__":
    print("Initialisation de la base SQLite...")
    bilan = importer_corpus_et_resultats()
    bilan_nlp = importer_analyses_nlp()
    bilan_metier = importer_extractions_metier()
    bilan_rapprochement = importer_rapprochements()
    print("\nImport terminé :")
    print(json.dumps(bilan, ensure_ascii=False, indent=2))
    print("\nImport NLP :")
    print(json.dumps(bilan_nlp, ensure_ascii=False, indent=2))
    print("\nImport documents métier :")
    print(json.dumps(bilan_metier, ensure_ascii=False, indent=2))
    print("\nImport rapprochements CCTP-DQE :")
    print(json.dumps(bilan_rapprochement, ensure_ascii=False, indent=2))
    print("\nTableau de bord :")
    print(json.dumps(statistiques_tableau_de_bord(), ensure_ascii=False, indent=2))
