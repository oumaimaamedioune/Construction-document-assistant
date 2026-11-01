import sys
import unittest
from pathlib import Path


RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from evaluer_validation_nlp import evaluer_annotations  # noqa: E402


class TestEvaluationValidationNlp(unittest.TestCase):
    def test_scores_avec_erreur_et_oubli(self):
        annotations = [{
            "predictions_nlp": {"materiaux": ["béton", "bois"]},
            "validation": {
                "statut": "corrige",
                "predictions_incorrectes": {"materiaux": ["bois"]},
                "entites_manquantes": {"materiaux": ["acier"]},
            },
        }]
        rapport = evaluer_annotations(annotations)
        metriques = rapport["metriques_globales"]
        self.assertEqual(metriques["vrais_positifs"], 1)
        self.assertEqual(metriques["faux_positifs"], 1)
        self.assertEqual(metriques["faux_negatifs"], 1)
        self.assertEqual(metriques["precision"], 0.5)
        self.assertEqual(metriques["rappel"], 0.5)
        self.assertEqual(rapport["statut"], "final")

    def test_rapport_reste_provisoire(self):
        annotations = [
            {"predictions_nlp": {}, "validation": {"statut": "valide", "predictions_incorrectes": {}, "entites_manquantes": {}}},
            {"predictions_nlp": {}, "validation": {"statut": "a_valider", "predictions_incorrectes": {}, "entites_manquantes": {}}},
        ]
        rapport = evaluer_annotations(annotations)
        self.assertEqual(rapport["statut"], "provisoire")
        self.assertEqual(rapport["avancement"]["valides"], 1)


if __name__ == "__main__":
    unittest.main()

