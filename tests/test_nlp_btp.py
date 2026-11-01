import sys
import unittest
from pathlib import Path


RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from nlp_btp import analyser_texte, nettoyer_texte  # noqa: E402


class TestNlpBtp(unittest.TestCase):
    def test_nettoyage_pdf(self):
        texte = "Canalisa-\n tion   PVC\tØ 100 mm"
        self.assertEqual(nettoyer_texte(texte), "Canalisation PVC Ø 100 mm")

    def test_normalisation_et_reconnaissance(self):
        analyse = analyser_texte("B.A. C25/30 dosé à 350 kg/m3, épaisseur 20cm")
        self.assertIn("béton armé", analyse["entites"]["materiaux"])
        self.assertEqual(analyse["entites"]["classes_beton"], ["C25/30"])
        self.assertIn("350 kg/m³", analyse["entites"]["dosages"])
        self.assertIn("20 cm", analyse["texte_normalise"])

    def test_norme_et_equipement(self):
        analyse = analyser_texte("Canalisations en PVC conformes à NF EN 1401-1, diamètre Ø 125 mm")
        self.assertIn("PVC", analyse["entites"]["materiaux"])
        self.assertIn("canalisation", analyse["entites"]["ouvrages_equipements"])
        self.assertIn("NF EN 1401-1", analyse["entites"]["normes"])
        self.assertIn("Ø 125 mm", analyse["entites"]["diametres"])

    def test_propriete_et_type_ciment_corriges(self):
        analyse = analyser_texte(
            "Béton hydrofugé dosé à 350 kg de ciment type CPJ, classe C25/30."
        )
        self.assertEqual(analyse["entites"]["proprietes"], ["hydrofugé"])
        self.assertEqual(analyse["entites"]["type_ciment"], ["CPJ"])

    def test_absence_de_fausse_entite(self):
        analyse = analyser_texte("Le document sera remis en cinq exemplaires.")
        self.assertEqual(analyse["entites"], {})

    def test_mesure_identique_dedoublonnee(self):
        analyse = analyser_texte("Béton dosé à 350 kg. Béton dosé à 350 kg.")
        self.assertEqual(len(analyse["entites"]["mesures"]), 1)


if __name__ == "__main__":
    unittest.main()
