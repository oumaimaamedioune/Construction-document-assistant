import json
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from validation_nlp import (  # noqa: E402
    construire_entites_corrigees,
    parser_entites_manquantes,
    sauvegarder_validation,
)


class TestSauvegardeValidationNlp(unittest.TestCase):
    def test_construit_resultat_corrige_sans_modifier_original(self):
        predictions = {"materiaux": ["beton", "acier"], "normes": ["NF EN 206"]}
        resultat = construire_entites_corrigees(
            predictions,
            {"materiaux": ["acier"]},
            {"proprietes": ["hydrofuge"], "materiaux": ["beton"]},
        )
        self.assertEqual(resultat["materiaux"], ["beton"])
        self.assertEqual(resultat["proprietes"], ["hydrofuge"])
        self.assertEqual(predictions["materiaux"], ["beton", "acier"])

    def test_parser_entites_manquantes(self):
        resultat = parser_entites_manquantes("materiaux: béton; acier\nnormes: NF EN 206")
        self.assertEqual(resultat["materiaux"], ["béton", "acier"])
        self.assertEqual(resultat["normes"], ["NF EN 206"])
        with self.assertRaises(ValueError):
            parser_entites_manquantes("ligne sans séparateur")

    def test_sauvegarde_atomique(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "validation.json"
            chemin.write_text(json.dumps([{
                "id_validation": 1,
                "validation": {"statut": "a_valider"},
            }]), encoding="utf-8")
            resultat = sauvegarder_validation(
                1, {"materiaux": ["acier"]}, {"normes": ["NF EN 206"]},
                "Contrôle", chemin,
            )
            self.assertEqual(resultat["validation"]["statut"], "corrige")
            self.assertFalse(chemin.with_suffix(".json.tmp").exists())
            with self.assertRaises(ValueError):
                sauvegarder_validation(1, {}, {}, "", chemin)


if __name__ == "__main__":
    unittest.main()
