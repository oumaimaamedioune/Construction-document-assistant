import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from extract_documents_metier import (  # noqa: E402
    categorie_contrat,
    nettoyer_titre_contrat,
    qualite_texte,
    valeurs_presentes,
)


class TestDocumentsMetier(unittest.TestCase):
    def test_contrat_classe_les_clauses_metier(self):
        self.assertEqual(categorie_contrat("PRIX DES TRAVAUX"), "prix")
        self.assertEqual(categorie_contrat("PAIEMENT"), "paiement")
        self.assertEqual(categorie_contrat("RÉSILIATION"), "resiliation")

    def test_detecte_un_texte_pdf_degrade(self):
        texte = "(cid:71) (cid:80) (cid:81) clause lisible"
        statut, ratio = qualite_texte(texte)
        self.assertEqual(statut, "degradee")
        self.assertGreater(ratio, 0)

    def test_repare_les_titres_degrades_du_contrat(self):
        self.assertEqual(nettoyer_titre_contrat("TRAVAAAUUUX"), "TRAVAUX")

    def test_reportage_reconnait_equipement_et_procede(self):
        texte = "Le finisseur VÖGELE réalise la pose et le compactage de l'enrobé."
        equipements = valeurs_presentes(texte, ("VÖGELE", "HAMM", "finisseur"))
        procedes = valeurs_presentes(texte, ("pose", "compactage", "béton"))
        self.assertEqual(equipements, ["VÖGELE", "finisseur"])
        self.assertEqual(procedes, ["pose", "compactage"])


if __name__ == "__main__":
    unittest.main()
