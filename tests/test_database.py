import json
import sys
import tempfile
import unittest
from pathlib import Path


RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from database import (  # noqa: E402
    actualiser_document_cible,
    connexion,
    corriger_extraction,
    detecter_categorie_metier,
    importer_analyses_nlp,
    importer_corpus_et_resultats,
    initialiser_base,
    lister_extractions,
    lister_extractions_metier,
    importer_extractions_metier,
    importer_rapprochements,
    lister_rapprochements,
    enregistrer_decision_rapprochement,
    enregistrer_validation_metier,
    lister_validations_metier,
    enregistrer_validation_extraction,
    lister_validations_extractions,
    statistiques_tableau_de_bord,
)


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "test.db"
        initialiser_base(self.base)

    def tearDown(self):
        self.temp.cleanup()

    def test_schema_et_contraintes(self):
        with connexion(self.base) as conn:
            tables = {
                ligne["name"]
                for ligne in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertTrue({"documents", "extractions", "extractions_metier", "controles_metier", "controles_extractions", "analyses_nlp", "rapprochements", "corrections", "executions"} <= tables)
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            colonnes = {
                ligne["name"] for ligne in conn.execute("PRAGMA table_info(documents)")
            }
            self.assertIn("categorie_metier", colonnes)

    def test_classification_metier(self):
        self.assertEqual(
            detecter_categorie_metier(RACINE / "data" / "Guide_Metier" / "guide.pdf"),
            "GUIDE_METIER",
        )
        self.assertEqual(
            detecter_categorie_metier(
                RACINE / "data" / "Rapports" / "magazine.pdf",
                "RoadNews - WIRTGEN GROUP",
            ),
            "REPORTAGE_TECHNIQUE",
        )
        self.assertEqual(
            detecter_categorie_metier(
                RACINE / "data" / "Rapports" / "rapport-semaine-2.pdf",
                "Rapport hebdomadaire du chantier",
            ),
            "RAPPORT_CHANTIER",
        )

    def test_import_idempotent(self):
        premier = importer_corpus_et_resultats(self.base)
        second = importer_corpus_et_resultats(self.base)
        stats = statistiques_tableau_de_bord(self.base)
        self.assertEqual(premier["extractions_source"], 160)
        self.assertEqual(premier["ajouts"], 159)
        self.assertEqual(premier["doublons_ignores"], 1)
        self.assertEqual(second["ajouts"], 0)
        self.assertEqual(second["doublons_ignores"], 160)
        # Le corpus peut grandir depuis l'interface : le test vérifie le
        # comptage réel de l'import, pas une ancienne taille figée.
        self.assertEqual(stats["documents"], premier["documents"])
        self.assertEqual(stats["extractions"], 159)

    def test_actualisation_cible_ne_traite_qu_un_document(self):
        chemin = RACINE / "data" / "DQE" / "modele-devis-batiment-pdf.pdf"
        element = {
            "type_document": "DQE",
            "fichier_source": chemin.name,
            "page": 1,
            "categorie": "poste_devis",
            "libelle": "Produit A",
            "donnees": {
                "numero_poste": "1",
                "unite": "u",
                "quantite": 4,
                "prix_unitaire": 200,
                "prix_total": 800,
                "controle_calcul": "valide",
                "texte_source": "Produit A 4,00 200,00 € 800,00 €",
            },
        }
        premier = actualiser_document_cible(chemin, [element], self.base)
        second = actualiser_document_cible(chemin, [element], self.base)
        with connexion(self.base) as conn:
            documents = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
            extractions = conn.execute("SELECT COUNT(*) AS n FROM extractions").fetchone()["n"]
            executions = conn.execute("SELECT COUNT(*) AS n FROM executions").fetchone()["n"]
        self.assertEqual(premier["documents"], 1)
        self.assertEqual(second["documents"], 1)
        self.assertEqual(documents, 1)
        self.assertEqual(extractions, 1)
        self.assertEqual(executions, 2)

    def test_correction_conserve_historique(self):
        importer_corpus_et_resultats(self.base)
        extraction = lister_extractions(self.base)[0]
        nouvelles = dict(extraction["donnees"])
        nouvelles["test_correction"] = True
        corriger_extraction(extraction["id"], nouvelles, "Test", chemin_base=self.base)
        with connexion(self.base) as conn:
            ligne = conn.execute(
                "SELECT statut_validation, donnees_json FROM extractions WHERE id=?",
                (extraction["id"],),
            ).fetchone()
            historique = conn.execute(
                "SELECT COUNT(*) AS n FROM corrections WHERE extraction_id=?",
                (extraction["id"],),
            ).fetchone()["n"]
        self.assertEqual(ligne["statut_validation"], "corrige")
        self.assertTrue(json.loads(ligne["donnees_json"])["test_correction"])
        self.assertEqual(historique, 1)

    def test_import_nlp_idempotent_et_lie_aux_extractions(self):
        importer_corpus_et_resultats(self.base)
        premier = importer_analyses_nlp(self.base)
        second = importer_analyses_nlp(self.base)
        with connexion(self.base) as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM analyses_nlp").fetchone()["n"]
            orphelins = conn.execute(
                """SELECT COUNT(*) AS n FROM analyses_nlp n
                   LEFT JOIN extractions e ON e.id=n.extraction_id
                   WHERE e.id IS NULL"""
            ).fetchone()["n"]
        self.assertEqual(premier["analyses_uniques"], 159)
        self.assertEqual(premier["ajouts"], 159)
        self.assertEqual(second["ajouts"], 0)
        self.assertEqual(second["mises_a_jour"], 159)
        self.assertEqual(total, 159)
        self.assertEqual(orphelins, 0)

    def test_import_et_filtres_documents_metier(self):
        importer_corpus_et_resultats(self.base)
        premier = importer_extractions_metier(self.base)
        second = importer_extractions_metier(self.base)
        contrats = lister_extractions_metier(self.base, type_document="CONTRAT")
        guides = lister_extractions_metier(self.base, type_document="GUIDE_METIER")
        self.assertEqual(premier["ajouts"], 225)
        self.assertEqual(second["ajouts"], 0)
        self.assertEqual(len(contrats), 21)
        self.assertEqual(len(guides), 135)
        self.assertTrue(all(e["type_document"] == "CONTRAT" for e in contrats))
        self.assertTrue(all("donnees" in e and "nom_fichier" in e for e in contrats))

    def test_validation_metier_conserve_decision_et_correction(self):
        importer_corpus_et_resultats(self.base)
        importer_extractions_metier(self.base)
        element = lister_extractions_metier(self.base, type_document="CONTRAT")[0]
        with connexion(self.base) as conn:
            conn.execute(
                "UPDATE extractions_metier SET statut_validation='a_verifier' WHERE id=?",
                (element["id"],),
            )
        attente = lister_validations_metier(self.base, a_verifier_seulement=True)
        self.assertTrue(any(e["id"] == element["id"] for e in attente))
        enregistrer_validation_metier(
            element["id"], "corrige", "Paiement Prix", "Paiement sous 30 jours",
            "Vérifié dans la preuve", chemin_base=self.base,
        )
        resultat = next(e for e in lister_validations_metier(self.base) if e["id"] == element["id"])
        self.assertEqual(resultat["decision"], "corrige")
        self.assertEqual(resultat["statut_validation"], "corrige")
        self.assertEqual(resultat["libelle"], "Paiement sous 30 jours")
        self.assertFalse(any(e["id"] == element["id"] for e in lister_validations_metier(self.base, True)))

    def test_validation_cctp_a_verifier_est_dans_la_file_unifiee(self):
        chemin = RACINE / "data" / "CCTP" / "10ST2023_COUPVRAY-TENNIS_CCTP-LOT-1.pdf"
        element = {
            "type_document": "CCTP", "fichier_source": chemin.name,
            "page": 1, "categorie": "mise_en_oeuvre", "libelle": "Mise en œuvre",
            "donnees": {
                "texte_source": "La mise en œuvre devra respecter les prescriptions.",
                "statut_validation": "a_verifier",
            },
        }
        actualiser_document_cible(chemin, [element], self.base)
        attente = lister_validations_extractions(self.base, True)
        self.assertEqual(len(attente), 1)
        enregistrer_validation_extraction(
            attente[0]["id"], "valide", chemin_base=self.base
        )
        resultat = lister_validations_extractions(self.base)
        self.assertEqual(resultat[0]["decision"], "valide")
        self.assertEqual(resultat[0]["statut_validation"], "valide")
        self.assertEqual(lister_validations_extractions(self.base, True), [])

    def test_rapprochements_idempotents_et_sans_orphelins(self):
        importer_corpus_et_resultats(self.base)
        premier = importer_rapprochements(self.base)
        second = importer_rapprochements(self.base)
        with connexion(self.base) as conn:
            postes = conn.execute(
                "SELECT COUNT(DISTINCT extraction_dqe_id) AS n FROM rapprochements WHERE actif=1"
            ).fetchone()["n"]
            orphelins = conn.execute(
                """SELECT COUNT(*) AS n FROM rapprochements r
                   LEFT JOIN extractions d ON d.id=r.extraction_dqe_id
                   LEFT JOIN extractions c ON c.id=r.extraction_cctp_id
                   WHERE d.id IS NULL OR (r.extraction_cctp_id IS NOT NULL AND c.id IS NULL)"""
            ).fetchone()["n"]
            niveaux = {
                ligne["niveau"] for ligne in conn.execute(
                    "SELECT DISTINCT niveau FROM rapprochements WHERE actif=1"
                )
            }
        self.assertEqual(premier["postes_dqe_source"], 102)
        self.assertGreater(premier["lignes_actives"], 102)
        self.assertEqual(second["ajouts"], 0)
        # Plusieurs blocs source CCTP peuvent converger vers la même extraction
        # unique en base : le nombre d'actualisations peut donc dépasser le
        # nombre de lignes actives, sans créer de doublon.
        self.assertGreaterEqual(second["mises_a_jour"], premier["lignes_actives"])
        self.assertEqual(second["lignes_actives"], premier["lignes_actives"])
        self.assertEqual(second["erreurs_liaison"], 0)
        self.assertEqual(postes, 102)
        self.assertEqual(orphelins, 0)
        self.assertIn("sans_correspondance", niveaux)

    def test_decision_rapprochement_est_conservee_apres_reimport(self):
        importer_corpus_et_resultats(self.base)
        importer_rapprochements(self.base)
        candidat = next(r for r in lister_rapprochements(self.base) if r["extraction_cctp_id"])
        enregistrer_decision_rapprochement(
            candidat["id"], "accepte", "Validé par le test", chemin_base=self.base
        )
        importer_rapprochements(self.base)
        resultat = next(r for r in lister_rapprochements(self.base) if r["id"] == candidat["id"])
        self.assertEqual(resultat["decision_humaine"], "accepte")
        self.assertEqual(resultat["commentaire"], "Validé par le test")


if __name__ == "__main__":
    unittest.main()
