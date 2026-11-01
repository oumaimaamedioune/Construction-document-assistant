import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from chatbot_btp import (
    _champ_demande,
    _champs_demandes,
    _categorie_inventaire,
    _numero_poste,
    _preuve_directe_avec_limite,
    _reponse_dqe_structuree,
    _reponse_sous_total_dqe,
    _reponse_inventaire_document,
    _materiaux_dans_texte,
    _materiaux_pertinents,
    _nettoyer_extrait_pdf,
    _resume_preuve,
    _demande_synthese_documentaire,
    _synthese_documentaire_depuis_index,
    _preuve_compatible_question,
    _reponse_beton_depuis_index,
    _fenetres_texte_pdf,
    SourceChat,
    enregistrer_avis_chatbot,
)


class TestChatbotBtp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "chat.db"
        connexion = sqlite3.connect(self.base)
        connexion.executescript(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY, nom_fichier TEXT NOT NULL
            );
            CREATE TABLE extractions (
                id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL,
                type_document TEXT NOT NULL, page INTEGER, categorie TEXT,
                libelle TEXT, section TEXT, texte_source TEXT,
                donnees_json TEXT NOT NULL
            );
            """
        )
        connexion.execute(
            "INSERT INTO documents(id, nom_fichier) VALUES (?, ?)",
            (1, "document_Devis.pdf"),
        )
        donnees = {
            "numero_poste": "1.1",
            "designation": "Installation et repli de chantier",
            "unite": "Ens.",
            "quantite": 1,
            "prix_unitaire": 300000,
            "prix_total": 300000,
        }
        connexion.execute(
            """INSERT INTO extractions VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                1, 1, "DQE", 1, "poste_devis", donnees["designation"],
                "Installation, approvisionnement et repli du chantier",
                "1.1 Installation et repli de chantier Ens. 1 300 000 300 000",
                json.dumps(donnees),
            ),
        )
        connexion.commit()
        connexion.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_comprend_poste_et_alias_pu(self):
        self.assertEqual(_numero_poste("Quel est le PU du poste 1.1 ?"), "1.1")
        self.assertEqual(_champ_demande("Quel est le PU du poste 1.1 ?"), "prix_unitaire")
        self.assertEqual(
            _champ_demande("Quel est le prix unitaire du poste 1.1 ?"), "prix_unitaire"
        )
        self.assertEqual(_champ_demande("Quelle est l'unité du poste 1.1 ?"), "unite")

    def test_reponse_exacte_sans_modele_generatif(self):
        reponse = _reponse_dqe_structuree(
            "Dans document_Devis, quelle est l'unité du poste 1.1 ?", self.base
        )
        self.assertIsNotNone(reponse)
        self.assertEqual(reponse.mode, "donnee_structuree")
        self.assertIn("Ens.", reponse.texte)
        self.assertEqual(reponse.sources[0].document, "document_Devis.pdf")
        self.assertEqual(reponse.sources[0].page, 1)

    def test_reponse_complete_du_poste(self):
        reponse = _reponse_dqe_structuree(
            "Donne les informations du poste 1.1 dans document_Devis", self.base
        )
        self.assertIn("300 000", reponse.texte)
        self.assertIn("Quantité", reponse.texte)

    def test_question_multi_champs_dqe_retourne_tous_les_champs_demandes(self):
        question = (
            "Quelle est l'unité, la quantité, le prix unitaire "
            "et le montant du poste 1.1 ?"
        )
        self.assertEqual(
            _champs_demandes(question),
            ["unite", "quantite", "prix_unitaire", "prix_total"],
        )
        reponse = _reponse_dqe_structuree(
            question, self.base, document_cible="document_Devis.pdf"
        )
        self.assertIn("Unité", reponse.texte)
        self.assertIn("Quantité", reponse.texte)
        self.assertIn("Prix unitaire", reponse.texte)
        self.assertIn("Montant", reponse.texte)

    def test_sous_total_dqe_est_calcule_sans_modele_generatif(self):
        connexion = sqlite3.connect(self.base)
        donnees = {
            "numero_poste": "1.2",
            "designation": "Transport de matériaux de construction",
            "unite": "Ens.",
            "quantite": 1,
            "prix_unitaire": 500000,
            "prix_total": 500000,
        }
        connexion.execute(
            "INSERT INTO extractions VALUES (?,?,?,?,?,?,?,?,?)",
            (2, 1, "DQE", 1, "poste_devis", donnees["designation"], None,
             "1.2 Transport de matériaux Ens. 1 500 000 500 000",
             json.dumps(donnees)),
        )
        connexion.commit()
        connexion.close()
        reponse = _reponse_sous_total_dqe(
            "Quel est le SOUS TOTAL I ?", self.base, "document_Devis.pdf"
        )
        self.assertEqual(reponse.mode, "sous_total_dqe")
        self.assertIn("800 000", reponse.texte)
        self.assertIn("Poste 1.1", reponse.texte)
        self.assertIn("Poste 1.2", reponse.texte)

    def test_sous_total_reconnu_depuis_intitule(self):
        reponse = _reponse_sous_total_dqe(
            "Quel est le sous total pour installation et repli du chantier ?",
            self.base,
            "document_Devis.pdf",
        )
        self.assertEqual(reponse.mode, "sous_total_dqe")
        self.assertIn("300 000", reponse.texte)

    def test_prix_unitaire_ne_devient_pas_unite(self):
        reponse = _reponse_dqe_structuree(
            "Quel est le prix unitaire du poste 1.1 dans document_Devis ?", self.base
        )
        self.assertIn("Prix unitaire", reponse.texte)
        self.assertIn("300 000", reponse.texte)

    def test_inventaire_complet_du_devis(self):
        reponse = _reponse_inventaire_document(
            "Donne-moi toutes les informations sur ce devis",
            self.base,
            "document_Devis.pdf",
        )
        self.assertIsNotNone(reponse)
        self.assertEqual(reponse.mode, "inventaire_dqe")
        self.assertIn("inventaire complet", reponse.texte)
        self.assertIn("Installation et repli de chantier", reponse.texte)
        self.assertIn("300 000", reponse.texte)

    def test_inventaire_demande_un_document_precis(self):
        reponse = _reponse_inventaire_document(
            "Liste tous les postes", self.base, None
        )
        self.assertEqual(reponse.mode, "clarification_document")

    def test_categorie_inventaire_affine_un_cctp_generique(self):
        self.assertEqual(
            _categorie_inventaire(
                "materiau", "Terrassements", "Fouille, remblai et compactage"
            ),
            "Terrassement et fondations",
        )
        self.assertEqual(
            _categorie_inventaire(
                "materiau", "Couverture", "Bac acier thermo-acoustique de toiture"
            ),
            "Couverture et étanchéité",
        )

    def test_resume_preuve_ne_se_limite_pas_au_titre(self):
        resume = _resume_preuve("Béton", "Béton dosé à 350 kg/m3 conforme à la NF EN 206.")
        self.assertIn("350 kg/m3", resume)

    def test_resume_preuve_nettoie_pdf_et_signale_fragment(self):
        resume = _resume_preuve(
            "Terrassement",
            "Le matériau sera de compacité´ suffisante lorsque la densité´ sera égale a` 95%"
        )
        self.assertNotIn("´", resume)
        self.assertNotIn("a`", resume)
        self.assertTrue(resume.endswith("…"))

    def test_certification_iso_classee_dans_normes(self):
        self.assertEqual(
            _categorie_inventaire(
                "materiau", "Étanchéité des murs enterrés",
                "Le système qualité a été reconnu conforme aux normes ISO 9001 ou 9002."
            ),
            "Normes et références",
        )

    def test_categorie_reportage_trop_large_est_affinee(self):
        self.assertEqual(
            _categorie_inventaire(
                "cas_chantier_technique", "Compactage des remblais",
                "Les essais de compactage sont réalisés sur le chantier."
            ),
            "Terrassement et fondations",
        )

    def test_corrections_ocr_affichage_sans_modifier_la_base(self):
        nettoye = _nettoyer_extrait_pdf(
            "Conxflits D’Intérêtss - Cesion De Conttrraatt - Sansmotif"
        )
        self.assertIn("Conflits", nettoye)
        self.assertIn("Cession", nettoye)
        self.assertIn("Contrat", nettoye)

    def test_corrections_ocr_des_nombres_du_contrat(self):
        nettoye = _nettoyer_extrait_pdf(
            "article 111444 : dans les quinze (111555) jours"
        )
        self.assertEqual(nettoye, "article 14 : dans les quinze (15) jours")

    def test_un_titre_seul_n_est_pas_presente_comme_clause_complete(self):
        source = SourceChat(
            document="contrat.pdf", page=4, type_document="CONTRAT",
            titre="Paiement", texte="PAIEMENT",
        )
        texte = _preuve_directe_avec_limite(1, source, "PAIEMENT")
        self.assertIn("pas suffisamment lisible", texte)
        self.assertIn("page 4", texte)

    def test_termes_litige_ne_sont_pas_des_stopwords(self):
        # Protection documentaire : ces termes doivent rester discriminants
        # pour écarter une recommandation générale hors sujet.
        from chatbot_btp import _tokens_utiles
        tokens = _tokens_utiles(
            "Quelles recommandations concernent les litiges et les réclamations ?"
        )
        self.assertIn("litiges", tokens)
        self.assertIn("reclamations", tokens)

    def test_quantite_du_poste(self):
        reponse = _reponse_dqe_structuree(
            "Quelle est la quantité du poste 1.1 dans document_Devis ?", self.base
        )
        self.assertIn("Quantité", reponse.texte)
        self.assertIn("1", reponse.texte)

    def test_montant_du_poste(self):
        reponse = _reponse_dqe_structuree(
            "Quel est le montant du poste 1.1 dans document_Devis ?", self.base
        )
        self.assertIn("Montant", reponse.texte)
        self.assertIn("300 000", reponse.texte)

    def test_filtre_documentaire(self):
        reponse = _reponse_dqe_structuree(
            "Quelle est la quantité du poste 1.1 ?",
            self.base,
            document_cible="un_autre_document.pdf",
        )
        self.assertIsNone(reponse)

    def test_enregistrement_avis_sqlite(self):
        enregistrer_avis_chatbot(
            question="Quelle est la quantité du poste 1.1 ?",
            reponse="La quantité est 1.",
            verdict="utile",
            sources=[{"document": "document_Devis.pdf", "page": 1}],
            document_cible="document_Devis.pdf",
            chemin_base=self.base,
        )
        connexion = sqlite3.connect(self.base)
        try:
            avis = connexion.execute(
                "SELECT verdict, document_cible, sources_json FROM avis_chatbot"
            ).fetchone()
        finally:
            connexion.close()
        self.assertEqual(avis[0], "utile")
        self.assertEqual(avis[1], "document_Devis.pdf")
        self.assertEqual(json.loads(avis[2])[0]["page"], 1)

    def test_materiaux_btp_extraits_sans_faux_per(self):
        valeurs = _materiaux_dans_texte(
            "Canalisations en PVC, cuivre, PER, multicouche et acier galvanisé."
        )
        self.assertEqual(
            valeurs, ["PVC", "Cuivre", "Acier galvanisé", "PER", "Multicouche"]
        )
        self.assertNotIn("PER", _materiaux_dans_texte("ce dispositif permet de contrôler"))

    def test_question_plomberie_ecarte_le_beton_hors_sujet(self):
        question = "Quels matériaux sont utilisés pour les réseaux de plomberie ?"
        texte = "Ouvrage en béton. Canalisations sanitaires en PVC et cuivre."
        self.assertEqual(
            _materiaux_pertinents(question, texte),
            ["PVC", "Cuivre"],
        )

    def test_demande_de_resume_est_reconnue_sans_dependre_du_mot_principales(self):
        self.assertTrue(
            _demande_synthese_documentaire(
                "Résume les principales informations techniques trouvées dans le corpus."
            )
        )
        self.assertFalse(
            _demande_synthese_documentaire("Quelles prescriptions concernent le béton ?")
        )

    def test_synthese_regroupe_les_extraits_par_theme_et_conserve_les_sources(self):
        index = [
            ({
                "document_id": 1, "nom_fichier": "cctp.pdf", "type_document": "CCTP",
                "page": 4, "titre": "Terrassements",
                "contenu": "Catégorie : materiau\nTexte source : fouille et remblai compacté",
            }, []),
            ({
                "document_id": 2, "nom_fichier": "contrat.pdf", "type_document": "CONTRAT",
                "page": 7, "titre": "Paiement",
                "contenu": "Catégorie : paiement_prix\nTexte source : paiement des travaux",
            }, []),
        ]
        reponse = _synthese_documentaire_depuis_index(
            "Résume les principales informations techniques du corpus", index
        )
        self.assertIsNotNone(reponse)
        self.assertEqual(reponse.mode, "synthese_documentaire")
        self.assertIn("2 document(s)", reponse.texte)
        self.assertIn("Terrassement et fondations", reponse.texte)
        self.assertNotIn("Les principales fonctionnalités", reponse.texte)
        self.assertEqual(len(reponse.sources), 2)

    def test_garde_fou_refuse_une_preuve_hors_sujet(self):
        ligne = {
            "titre": "Signature d'un avenant",
            "contenu": "Conditions et conséquences de la résiliation du marché.",
        }
        self.assertFalse(_preuve_compatible_question(
            "Quels types de béton et quelles classes de résistance sont mentionnés ?",
            ligne,
        ))
        self.assertTrue(_preuve_compatible_question(
            "Quels types de béton sont mentionnés ?",
            {"titre": "Béton", "contenu": "Béton blanc C25/30."},
        ))

    def test_reponse_beton_structuree_reste_liee_aux_preuves(self):
        index = [
            ({
                "document_id": 1, "nom_fichier": "cctp.pdf", "type_document": "CCTP",
                "page": 8, "titre": "Béton préfabriqué",
                "contenu": "Béton blanc C25/30 dosé à 350 kg/m3 suivant NF EN 206-1.",
            }, []),
            ({
                "document_id": 2, "nom_fichier": "contrat.pdf", "type_document": "CONTRAT",
                "page": 4, "titre": "Avenant", "contenu": "Résiliation du marché.",
            }, []),
        ]
        reponse = _reponse_beton_depuis_index(
            "Quels types de béton et quelles classes de résistance sont mentionnés ?",
            index,
        )
        self.assertEqual(reponse.mode, "beton_structure")
        self.assertIn("Béton blanc", reponse.texte)
        self.assertIn("C25/30", reponse.texte)
        self.assertNotIn("Résiliation", reponse.texte)
        self.assertEqual(len(reponse.sources), 1)


    def test_resistance_armature_non_classee_comme_resistance_beton(self):
        index = [({
            "document_id": 1, "nom_fichier": "cctp.pdf", "type_document": "CCTP",
            "page": 31, "titre": "Béton préfabriqué",
            "contenu": "Béton blanc C25/30. Armatures en acier 500 MPa pour béton armé.",
        }, [])]
        reponse = _reponse_beton_depuis_index(
            "Quels types de béton et quelles classes de résistance sont mentionnés ?",
            index,
        )
        self.assertIsNotNone(reponse)
        self.assertIn("C25/30", reponse.texte)
        self.assertNotIn("500 MPa", reponse.texte)

    def test_fenetres_pdf_conservent_clause_apres_ancienne_limite(self):
        texte = "Introduction contractuelle sans information utile. " * 35
        texte += (
            "L'Entrepreneur doit respecter et faire respecter par ses "
            "sous-traitants les obligations de sécurité du chantier."
        )
        fenetres = _fenetres_texte_pdf(texte)
        self.assertGreater(len(fenetres), 1)
        self.assertTrue(any("sous-traitants" in fenetre for fenetre in fenetres))
        self.assertTrue(all(len(fenetre) <= 1400 for fenetre in fenetres))


if __name__ == "__main__":
    unittest.main()
