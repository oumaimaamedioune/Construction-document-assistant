import sys
import unittest
from pathlib import Path


RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from extract_dqe import analyser_tableau_devis_standard  # noqa: E402


class TestExtractionDqe(unittest.TestCase):
    def test_devis_standard_avec_entete_decalee(self):
        tableau = [
            ["Identification du vendeur", None, None, "", "Client", None],
            ["Devis N°00001", "", "", "", "", ""],
            ["Désignation des produits", None, None, "Quantité", "Prix Unitaire HT", "Total HT"],
            ["Produit A", None, None, "4,00", "200,00€", "800,00€"],
            ["Produit B", None, None, "2,00", "300,00€", "600,00€"],
            ["", "", "", "", "TOTAL HT", "1 400,00€"],
        ]
        postes = analyser_tableau_devis_standard(tableau, 1, "modele.pdf")
        self.assertEqual(len(postes), 2)
        self.assertEqual(postes[0]["designation"], "Produit A")
        self.assertEqual(postes[0]["quantite"], 4.0)
        self.assertEqual(postes[0]["prix_unitaire"], 200.0)
        self.assertEqual(postes[0]["prix_total"], 800.0)
        self.assertEqual(postes[0]["controle_calcul"], "valide")

    def test_tableau_non_reconnu(self):
        self.assertIsNone(
            analyser_tableau_devis_standard([["Texte", "Autre"]], 1, "autre.pdf")
        )


if __name__ == "__main__":
    unittest.main()

