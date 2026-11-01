import sys
import unittest
from pathlib import Path


RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from preparer_validation_nlp import (  # noqa: E402
    agrandir_annotations,
    choisir_echantillon,
    construire_annotations,
)


def element(document, page, entites):
    return {
        "type_document": "CCTP",
        "fichier_source": document,
        "page": page,
        "libelle": "Exemple",
        "donnees": {"texte_source": "Texte métier"},
        "analyse_nlp": {"entites": entites},
    }


class TestValidationNlp(unittest.TestCase):
    def test_agrandissement_conserve_validation_existante(self):
        donnees = [
            element("a.pdf", 1, {"materiaux": ["beton"]}),
            element("a.pdf", 2, {"materiaux": ["acier"]}),
            element("a.pdf", 3, {"normes": ["NF EN 206"]}),
        ]
        existantes = construire_annotations(donnees[:1])
        existantes[0]["validation"]["statut"] = "valide"
        resultat = agrandir_annotations(existantes, donnees, 3)
        self.assertEqual(len(resultat), 3)
        self.assertEqual(resultat[0]["validation"]["statut"], "valide")

    def test_echantillon_par_document_et_cas_sans_prediction(self):
        donnees = [
            element("a.pdf", 1, {"materiaux": ["béton", "acier"]}),
            element("a.pdf", 2, {"normes": ["NF EN 206"]}),
            element("a.pdf", 3, {}),
            element("b.pdf", 1, {"materiaux": ["PVC"]}),
            element("b.pdf", 2, {}),
        ]
        selection = choisir_echantillon(donnees, nombre_par_document=2)
        self.assertEqual(len(selection), 4)
        self.assertEqual({e["fichier_source"] for e in selection}, {"a.pdf", "b.pdf"})
        self.assertEqual(sum(not e["analyse_nlp"]["entites"] for e in selection), 2)

    def test_annotations_initiales_ne_sont_pas_validees(self):
        annotations = construire_annotations([element("a.pdf", 1, {"materiaux": ["béton"]})])
        self.assertEqual(annotations[0]["validation"]["statut"], "a_valider")
        self.assertEqual(annotations[0]["predictions_nlp"]["materiaux"], ["béton"])


if __name__ == "__main__":
    unittest.main()
