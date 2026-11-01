import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analyse_nouveau_document import analyser_nouveau_document, nom_securise, proposer_type


class TestAnalyseNouveauDocument(unittest.TestCase):
    def test_propose_dqe_avec_indices_explicables(self):
        type_document, indices = proposer_type(
            "devis_projet.pdf",
            [{"page": 1, "texte": "Devis quantitatif : quantité, prix unitaire et montant"}],
        )
        self.assertEqual(type_document, "DQE")
        self.assertIn("devis quantitatif", indices)

    def test_nom_securise_conserve_pdf(self):
        self.assertEqual(nom_securise("../Mon devis #1.PDF"), "Mon devis _1.pdf")

    @patch("analyse_nouveau_document.inspecter_pdf")
    def test_document_generique_peut_etre_stocke_sans_analyse_metier(self, inspecter):
        inspecter.return_value = {
            "nombre_pages": 1,
            "pages": [{"page": 1, "texte": "Béton armé conforme à NF EN 206 pour le chantier."}],
            "nombre_caracteres": 52,
            "sha256": "abc",
        }
        resultat = analyser_nouveau_document(Path("note.pdf"), "AUTRE_BTP")
        self.assertTrue(resultat["integrable"])
        self.assertFalse(resultat["analysable"])
        self.assertGreaterEqual(resultat["resume"]["nombre_elements"], 1)

    @patch("analyse_nouveau_document.extraire_contrat", return_value=[])
    @patch("analyse_nouveau_document.inspecter_pdf")
    def test_secours_thematique_fournit_des_preuves_contractuelles(
        self, inspecter, _extraire_contrat
    ):
        inspecter.return_value = {
            "nombre_pages": 12,
            "pages": [{
                "page": 3,
                "texte": (
                    "Le délai d'exécution est fixé à quatre mois. "
                    "Le paiement intervient après validation du décompte. "
                    "Une pénalité est appliquée en cas de retard."
                ),
            }],
            "nombre_caracteres": 150,
            "sha256": "contrat",
        }
        resultat = analyser_nouveau_document(Path("ccap.pdf"), "CONTRAT")
        categories = {e["categorie"] for e in resultat["elements"]}
        self.assertTrue(resultat["secours_thematique_active"])
        self.assertIn("delais_penalites", categories)
        self.assertIn("paiement_prix", categories)
        self.assertTrue(all(e["donnees"]["texte_source"] for e in resultat["elements"]))

    @patch("analyse_nouveau_document.analyser_cctp", return_value=[])
    @patch("analyse_nouveau_document.inspecter_pdf")
    def test_secours_cctp_detecte_prescriptions_techniques(
        self, inspecter, _analyser_cctp
    ):
        inspecter.return_value = {
            "nombre_pages": 30,
            "pages": [{
                "page": 8,
                "texte": (
                    "La mise en oeuvre du béton armé comprend le coffrage et le ferraillage. "
                    "Le béton sera dosé à 350 kg/m3 et contrôlé par éprouvettes. "
                    "Le compactage des remblais devra respecter la densité prescrite."
                ),
            }],
            "nombre_caracteres": 200,
            "sha256": "cctp",
        }
        resultat = analyser_nouveau_document(Path("prescriptions.pdf"), "CCTP")
        categories = {e["categorie"] for e in resultat["elements"]}
        self.assertTrue(resultat["secours_thematique_active"])
        self.assertIn("mise_en_oeuvre", categories)
        self.assertIn("beton_armatures", categories)
        self.assertTrue(all(e["donnees"]["statut_validation"] == "a_verifier" for e in resultat["elements"]))

    @patch("analyse_nouveau_document.analyser_cctp", return_value=[])
    @patch("analyse_nouveau_document.inspecter_pdf")
    def test_secours_ne_confond_pas_maitrise_et_tri_ni_poste_de_controle(
        self, inspecter, _analyser_cctp
    ):
        inspecter.return_value = {
            "nombre_pages": 30,
            "pages": [{
                "page": 1,
                "texte": "Maîtrise d'ouvrage pour la construction du poste de contrôle des fourgons.",
            }],
            "nombre_caracteres": 75,
            "sha256": "ambigu",
        }
        resultat = analyser_nouveau_document(Path("cctp.pdf"), "CCTP")
        categories = {e["categorie"] for e in resultat["elements"]}
        self.assertNotIn("environnement_dechets", categories)
        self.assertNotIn("qualite_controle", categories)


if __name__ == "__main__":
    unittest.main()
