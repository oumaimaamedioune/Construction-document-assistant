import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rapprocher_cctp_dqe import niveau_score, rapprocher, tokens_metier


def element(type_document, libelle, entites=None):
    return {
        "type_document": type_document, "fichier_source": f"{type_document}.pdf", "page": 1,
        "categorie": "test", "libelle": libelle,
        "donnees": {"texte_source": libelle, "numero_poste": "1", "unite": "m²"},
        "analyse_nlp": {"texte_normalise": libelle, "entites": entites or {}},
    }


class TestRapprochement(unittest.TestCase):
    def test_normalise_les_variantes_btp(self):
        self.assertIn("reseau", tokens_metier("Pose de canalisations et tuyaux"))
        self.assertIn("acier", tokens_metier("Ferraillage métallique"))

    def test_retrouve_une_prescription_proche(self):
        donnees = [
            element("CCTP", "Dalle en béton armé épaisseur 20 cm", {"materiaux": ["béton"]}),
            element("CCTP", "Peinture acrylique sur murs intérieurs", {"materiaux": ["peinture"]}),
            element("DQE", "Réalisation dalle béton armé 20 cm", {"materiaux": ["béton"]}),
        ]
        resultat = rapprocher(donnees, seuil=0.1)
        meilleur = resultat["rapprochements"][0]["candidats"][0]
        self.assertIn("Dalle en béton", meilleur["cctp"]["libelle"])
        self.assertGreater(meilleur["score"], 0.5)
        self.assertIn("beton", meilleur["mots_techniques_communs"])

    def test_ne_force_pas_une_correspondance(self):
        donnees = [element("CCTP", "Peinture murale"), element("DQE", "Ascenseur panoramique")]
        resultat = rapprocher(donnees)
        self.assertEqual(resultat["rapprochements"][0]["statut"], "sans_correspondance")
        self.assertEqual(niveau_score(0.1), "insuffisante")


if __name__ == "__main__":
    unittest.main()
