"""Persistance SQLite locale pour l'assistant d'analyse de documents BTP.

La base conserve les documents, extractions, corrections humaines et
exécutions du pipeline. Les données techniques restent également exportées en
JSON : SQLite apporte l'historique, la recherche et l'intégrité relationnelle.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pdfplumber


RACINE_PROJET = Path(__file__).resolve().parents[1]
DOSSIER_DATA = RACINE_PROJET / "data"
DOSSIER_INSTANCE = RACINE_PROJET / "instance"
CHEMIN_BASE = DOSSIER_INSTANCE / "assistant_btp.db"
VERSION_SCHEMA = 6


def maintenant_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def empreinte_fichier(chemin: Path) -> str:
    sha256 = hashlib.sha256()
    with chemin.open("rb") as fichier:
        for bloc in iter(lambda: fichier.read(1024 * 1024), b""):
            sha256.update(bloc)
    return sha256.hexdigest()


def json_stable(valeur) -> str:
    return json.dumps(valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def cle_extraction(document_id: int, type_document: str, page, categorie: str, libelle: str, donnees) -> str:
    contenu = json_stable(
        {
            "document_id": document_id,
            "type_document": type_document,
            "page": page,
            "categorie": categorie,
            "libelle": libelle,
            "donnees": donnees,
        }
    )
    return hashlib.sha256(contenu.encode("utf-8")).hexdigest()


@contextmanager
def connexion(chemin_base: Path | str = CHEMIN_BASE) -> Iterator[sqlite3.Connection]:
    chemin = Path(chemin_base)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(chemin, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialiser_base(chemin_base: Path | str = CHEMIN_BASE) -> None:
    """Crée le schéma de façon idempotente et active les contraintes."""
    with connexion(chemin_base) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                appliquee_le TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom_fichier TEXT NOT NULL,
                chemin_relatif TEXT NOT NULL,
                type_document TEXT NOT NULL CHECK(type_document IN ('CCTP','DQE','AUTRE')),
                categorie_metier TEXT NOT NULL DEFAULT 'AUTRE',
                sha256 TEXT NOT NULL UNIQUE,
                taille_octets INTEGER NOT NULL CHECK(taille_octets >= 0),
                nombre_pages INTEGER CHECK(nombre_pages IS NULL OR nombre_pages >= 0),
                statut TEXT NOT NULL DEFAULT 'importe'
                    CHECK(statut IN ('importe','traite','sans_extraction','erreur')),
                date_ajout TEXT NOT NULL,
                date_derniere_analyse TEXT,
                message_erreur TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(type_document);
            CREATE INDEX IF NOT EXISTS idx_documents_statut ON documents(statut);

            CREATE TABLE IF NOT EXISTS extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                type_document TEXT NOT NULL CHECK(type_document IN ('CCTP','DQE')),
                page INTEGER CHECK(page IS NULL OR page >= 1),
                categorie TEXT NOT NULL,
                libelle TEXT NOT NULL DEFAULT '',
                section TEXT,
                texte_source TEXT,
                donnees_json TEXT NOT NULL CHECK(json_valid(donnees_json)),
                statut_validation TEXT NOT NULL DEFAULT 'extrait'
                    CHECK(statut_validation IN ('extrait','valide','incomplet','a_verifier','corrige')),
                score_confiance REAL CHECK(score_confiance IS NULL OR (score_confiance >= 0 AND score_confiance <= 1)),
                cle_unique TEXT NOT NULL UNIQUE,
                date_creation TEXT NOT NULL,
                date_modification TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_extractions_document ON extractions(document_id);
            CREATE INDEX IF NOT EXISTS idx_extractions_categorie ON extractions(categorie);
            CREATE INDEX IF NOT EXISTS idx_extractions_statut ON extractions(statut_validation);
            CREATE INDEX IF NOT EXISTS idx_extractions_page ON extractions(document_id, page);

            CREATE TABLE IF NOT EXISTS analyses_nlp (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                extraction_id INTEGER NOT NULL UNIQUE,
                version_nlp TEXT NOT NULL,
                methode TEXT NOT NULL,
                texte_normalise TEXT NOT NULL,
                entites_json TEXT NOT NULL CHECK(json_valid(entites_json)),
                date_analyse TEXT NOT NULL,
                FOREIGN KEY(extraction_id) REFERENCES extractions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_analyses_nlp_extraction
                ON analyses_nlp(extraction_id);

            CREATE TABLE IF NOT EXISTS extractions_metier (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                type_document TEXT NOT NULL
                    CHECK(type_document IN ('CONTRAT','GUIDE_METIER','REPORTAGE_TECHNIQUE','RAPPORT_CHANTIER')),
                page INTEGER CHECK(page IS NULL OR page >= 1),
                categorie TEXT NOT NULL,
                libelle TEXT NOT NULL DEFAULT '',
                texte_source TEXT,
                donnees_json TEXT NOT NULL CHECK(json_valid(donnees_json)),
                qualite_texte TEXT NOT NULL DEFAULT 'bonne'
                    CHECK(qualite_texte IN ('bonne','degradee')),
                statut_validation TEXT NOT NULL DEFAULT 'extrait'
                    CHECK(statut_validation IN ('extrait','a_verifier','valide','corrige')),
                cle_unique TEXT NOT NULL UNIQUE,
                date_creation TEXT NOT NULL,
                date_modification TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_extractions_metier_document ON extractions_metier(document_id);
            CREATE INDEX IF NOT EXISTS idx_extractions_metier_type ON extractions_metier(type_document, categorie);

            CREATE TABLE IF NOT EXISTS controles_metier (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                extraction_metier_id INTEGER NOT NULL UNIQUE,
                decision TEXT NOT NULL
                    CHECK(decision IN ('valide','corrige','rejete')),
                ancienne_categorie TEXT NOT NULL,
                ancienne_valeur TEXT NOT NULL,
                nouvelle_categorie TEXT,
                nouvelle_valeur TEXT,
                commentaire TEXT,
                auteur TEXT NOT NULL DEFAULT 'utilisateur',
                date_controle TEXT NOT NULL,
                FOREIGN KEY(extraction_metier_id) REFERENCES extractions_metier(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_controles_metier_decision
                ON controles_metier(decision, date_controle);

            CREATE TABLE IF NOT EXISTS controles_extractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                extraction_id INTEGER NOT NULL UNIQUE,
                decision TEXT NOT NULL CHECK(decision IN ('valide','corrige','rejete')),
                ancienne_categorie TEXT NOT NULL,
                ancienne_valeur TEXT NOT NULL,
                nouvelle_categorie TEXT,
                nouvelle_valeur TEXT,
                commentaire TEXT,
                auteur TEXT NOT NULL DEFAULT 'utilisateur',
                date_controle TEXT NOT NULL,
                FOREIGN KEY(extraction_id) REFERENCES extractions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_controles_extractions_decision
                ON controles_extractions(decision, date_controle);

            CREATE TABLE IF NOT EXISTS rapprochements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                extraction_dqe_id INTEGER NOT NULL,
                extraction_cctp_id INTEGER,
                rang_candidat INTEGER NOT NULL DEFAULT 1 CHECK(rang_candidat >= 0),
                score REAL CHECK(score IS NULL OR (score >= 0 AND score <= 1)),
                niveau TEXT NOT NULL
                    CHECK(niveau IN ('forte','moyenne','faible','sans_correspondance')),
                justification_json TEXT NOT NULL CHECK(json_valid(justification_json)),
                statut_systeme TEXT NOT NULL
                    CHECK(statut_systeme IN ('candidat_trouve','sans_correspondance')),
                decision_humaine TEXT NOT NULL DEFAULT 'a_valider'
                    CHECK(decision_humaine IN ('a_valider','accepte','rejete','non_requise')),
                commentaire TEXT,
                actif INTEGER NOT NULL DEFAULT 1 CHECK(actif IN (0,1)),
                cle_unique TEXT NOT NULL UNIQUE,
                version_moteur TEXT NOT NULL,
                date_creation TEXT NOT NULL,
                date_modification TEXT NOT NULL,
                FOREIGN KEY(extraction_dqe_id) REFERENCES extractions(id) ON DELETE CASCADE,
                FOREIGN KEY(extraction_cctp_id) REFERENCES extractions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_rapprochements_dqe ON rapprochements(extraction_dqe_id, actif);
            CREATE INDEX IF NOT EXISTS idx_rapprochements_cctp ON rapprochements(extraction_cctp_id, actif);
            CREATE INDEX IF NOT EXISTS idx_rapprochements_decision ON rapprochements(decision_humaine, actif);

            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                extraction_id INTEGER NOT NULL,
                ancienne_valeur_json TEXT NOT NULL CHECK(json_valid(ancienne_valeur_json)),
                nouvelle_valeur_json TEXT NOT NULL CHECK(json_valid(nouvelle_valeur_json)),
                commentaire TEXT,
                auteur TEXT NOT NULL DEFAULT 'utilisateur',
                date_correction TEXT NOT NULL,
                FOREIGN KEY(extraction_id) REFERENCES extractions(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_corrections_extraction ON corrections(extraction_id);

            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_debut TEXT NOT NULL,
                date_fin TEXT,
                duree_secondes REAL CHECK(duree_secondes IS NULL OR duree_secondes >= 0),
                statut TEXT NOT NULL CHECK(statut IN ('en_cours','succes','echec')),
                nb_documents INTEGER NOT NULL DEFAULT 0 CHECK(nb_documents >= 0),
                nb_extractions INTEGER NOT NULL DEFAULT 0 CHECK(nb_extractions >= 0),
                details_json TEXT CHECK(details_json IS NULL OR json_valid(details_json)),
                message_erreur TEXT
            );
            """
        )
        colonnes_documents = {
            ligne["name"] for ligne in conn.execute("PRAGMA table_info(documents)")
        }
        if "categorie_metier" not in colonnes_documents:
            conn.execute(
                "ALTER TABLE documents ADD COLUMN categorie_metier TEXT NOT NULL DEFAULT 'AUTRE'"
            )
        conn.execute(
            "INSERT OR IGNORE INTO schema_version(version, appliquee_le) VALUES (?, ?)",
            (VERSION_SCHEMA, maintenant_iso()),
        )


def detecter_type_document(chemin: Path) -> str:
    dossier = chemin.parent.name.casefold()
    if dossier == "cctp":
        return "CCTP"
    if dossier == "dqe":
        return "DQE"
    return "AUTRE"


def detecter_categorie_metier(chemin: Path, texte_premiere_page: str = "") -> str:
    """Classe le rôle métier du document sans prétendre l'avoir analysé."""
    dossier = chemin.parent.name.casefold().replace("-", "_").replace(" ", "_")
    if dossier == "cctp":
        return "CCTP"
    if dossier == "dqe":
        return "DQE"
    if dossier in {"contrat", "contrats"}:
        return "CONTRAT"
    if dossier in {"guide_metier", "guides_metier", "references"}:
        return "GUIDE_METIER"
    if dossier in {"rapport", "rapports"}:
        premiere_page = texte_premiere_page.casefold()
        if "roadnews" in premiere_page or "wirtgen group" in premiere_page:
            return "REPORTAGE_TECHNIQUE"
        return "RAPPORT_CHANTIER"
    if dossier in {"autres_btp", "autre_btp"}:
        return "AUTRE_BTP"
    return "AUTRE"


def ajouter_ou_actualiser_document(conn: sqlite3.Connection, chemin: Path) -> int:
    empreinte = empreinte_fichier(chemin)
    type_document = detecter_type_document(chemin)
    try:
        with pdfplumber.open(chemin) as pdf:
            nombre_pages = len(pdf.pages)
            texte_premiere_page = pdf.pages[0].extract_text() or "" if pdf.pages else ""
        erreur = None
    except Exception as exc:
        nombre_pages = None
        texte_premiere_page = ""
        erreur = str(exc)
    categorie_metier = detecter_categorie_metier(chemin, texte_premiere_page)
    relatif = chemin.resolve().relative_to(RACINE_PROJET.resolve()).as_posix()
    date = maintenant_iso()
    conn.execute(
        """
        INSERT INTO documents(
            nom_fichier, chemin_relatif, type_document, sha256, taille_octets,
            nombre_pages, statut, date_ajout, message_erreur, categorie_metier
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sha256) DO UPDATE SET
            nom_fichier=excluded.nom_fichier,
            chemin_relatif=excluded.chemin_relatif,
            type_document=excluded.type_document,
            taille_octets=excluded.taille_octets,
            nombre_pages=excluded.nombre_pages,
            message_erreur=excluded.message_erreur,
            categorie_metier=excluded.categorie_metier
        """,
        (
            chemin.name, relatif, type_document, empreinte, chemin.stat().st_size,
            nombre_pages, "erreur" if erreur else "importe", date, erreur,
            categorie_metier,
        ),
    )
    ligne = conn.execute("SELECT id FROM documents WHERE sha256 = ?", (empreinte,)).fetchone()
    return int(ligne["id"])


def enregistrer_document_seul(
    chemin: Path,
    chemin_base: Path | str = CHEMIN_BASE,
) -> int:
    """Enregistre un PDF dans la bibliothèque sans lancer son extraction.

    Le statut ``importe`` signifie que le fichier est conservé et traçable,
    mais que son analyse métier peut être lancée ultérieurement.
    """
    initialiser_base(chemin_base)
    with connexion(chemin_base) as conn:
        document_id = ajouter_ou_actualiser_document(conn, chemin)
        conn.execute(
            """
            UPDATE documents
            SET statut='importe', date_derniere_analyse=NULL, message_erreur=NULL
            WHERE id=?
            """,
            (document_id,),
        )
        return document_id


def statut_extraction(element: dict) -> str:
    statut_explicite = element.get("donnees", {}).get("statut_validation")
    if statut_explicite in {"extrait", "valide", "incomplet", "a_verifier", "corrige"}:
        return statut_explicite
    if element.get("type_document") == "DQE":
        controle = element.get("donnees", {}).get("controle_calcul")
        if controle in {"valide", "incomplet", "a_verifier"}:
            return controle
    return "extrait"


def actualiser_document_cible(
    chemin: Path,
    elements: list[dict],
    chemin_base: Path | str = CHEMIN_BASE,
) -> dict:
    """Met à jour l'analyse d'un seul PDF sans relancer tout le corpus.

    Les lignes déjà validées ou corrigées humainement ne sont jamais
    écrasées. Les autres lignes sont actualisées par leur identité métier
    (page, catégorie et libellé), ce qui conserve leurs identifiants et les
    relations existantes.
    """
    from nlp_btp import analyser_texte

    initialiser_base(chemin_base)
    date_debut = maintenant_iso()
    with connexion(chemin_base) as conn:
        document_id = ajouter_ou_actualiser_document(conn, chemin)
        execution = conn.execute(
            "INSERT INTO executions(date_debut, statut) VALUES (?, 'en_cours')",
            (date_debut,),
        )
        execution_id = int(execution.lastrowid)
        ajouts = mises_a_jour = preserves = analyses_nlp = 0

        for element in elements:
            type_document = str(element.get("type_document") or "")
            page = element.get("page")
            categorie = str(element.get("categorie") or "")
            libelle = str(element.get("libelle") or "")
            donnees = element.get("donnees", {})
            source = str(donnees.get("texte_source") or "")
            cle = cle_extraction(
                document_id, type_document, page, categorie, libelle, donnees,
            )

            if type_document in {"CCTP", "DQE"}:
                ligne = conn.execute(
                    """SELECT id, statut_validation FROM extractions
                       WHERE document_id=? AND type_document=? AND page IS ?
                         AND categorie=? AND libelle=?
                       ORDER BY id LIMIT 1""",
                    (document_id, type_document, page, categorie, libelle),
                ).fetchone()
                statut = statut_extraction(element)
                if ligne and ligne["statut_validation"] in {"valide", "corrige"}:
                    extraction_id = int(ligne["id"])
                    preserves += 1
                elif ligne:
                    extraction_id = int(ligne["id"])
                    conn.execute(
                        """UPDATE extractions SET section=?, texte_source=?, donnees_json=?,
                               statut_validation=?, cle_unique=?, date_modification=?
                           WHERE id=?""",
                        (donnees.get("section"), source, json_stable(donnees), statut,
                         cle, maintenant_iso(), extraction_id),
                    )
                    mises_a_jour += 1
                else:
                    curseur = conn.execute(
                        """INSERT INTO extractions(
                               document_id, type_document, page, categorie, libelle,
                               section, texte_source, donnees_json, statut_validation,
                               cle_unique, date_creation, date_modification)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (document_id, type_document, page, categorie, libelle,
                         donnees.get("section"), source, json_stable(donnees), statut,
                         cle, maintenant_iso(), maintenant_iso()),
                    )
                    extraction_id = int(curseur.lastrowid)
                    ajouts += 1

                texte_nlp = " ".join(partie for partie in (libelle, source) if partie)
                analyse = analyser_texte(texte_nlp)
                conn.execute(
                    """INSERT INTO analyses_nlp(
                           extraction_id, version_nlp, methode, texte_normalise,
                           entites_json, date_analyse)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(extraction_id) DO UPDATE SET
                           version_nlp=excluded.version_nlp,
                           methode=excluded.methode,
                           texte_normalise=excluded.texte_normalise,
                           entites_json=excluded.entites_json,
                           date_analyse=excluded.date_analyse""",
                    (extraction_id, analyse.get("version", "nlp_btp"),
                     analyse.get("methode", "regles_metier"),
                     analyse.get("texte_normalise", ""),
                     json_stable(analyse.get("entites", {})), maintenant_iso()),
                )
                analyses_nlp += 1
                continue

            qualite = str(donnees.get("qualite_texte") or "bonne")
            if qualite not in {"bonne", "degradee"}:
                qualite = "bonne"
            statut = str(donnees.get("statut_validation") or
                         ("a_verifier" if qualite == "degradee" else "extrait"))
            ligne = conn.execute(
                """SELECT id, statut_validation FROM extractions_metier
                   WHERE document_id=? AND page IS ? AND categorie=? AND libelle=?
                   ORDER BY id LIMIT 1""",
                (document_id, page, categorie, libelle),
            ).fetchone()
            if ligne and ligne["statut_validation"] in {"valide", "corrige"}:
                preserves += 1
            elif ligne:
                conn.execute(
                    """UPDATE extractions_metier SET type_document=?, texte_source=?,
                           donnees_json=?, qualite_texte=?, statut_validation=?,
                           cle_unique=?, date_modification=? WHERE id=?""",
                    (type_document, source, json_stable(donnees), qualite, statut,
                     cle, maintenant_iso(), int(ligne["id"])),
                )
                mises_a_jour += 1
            else:
                conn.execute(
                    """INSERT INTO extractions_metier(
                           document_id, type_document, page, categorie, libelle,
                           texte_source, donnees_json, qualite_texte,
                           statut_validation, cle_unique, date_creation, date_modification)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (document_id, type_document, page, categorie, libelle, source,
                     json_stable(donnees), qualite, statut, cle,
                     maintenant_iso(), maintenant_iso()),
                )
                ajouts += 1

        statut_document = "traite" if elements else "sans_extraction"
        conn.execute(
            """UPDATE documents SET statut=?, date_derniere_analyse=?, message_erreur=NULL
               WHERE id=?""",
            (statut_document, maintenant_iso(), document_id),
        )
        details = {
            "mode": "document_cible", "document_id": document_id,
            "ajouts": ajouts, "mises_a_jour": mises_a_jour,
            "validations_preservees": preserves, "analyses_nlp": analyses_nlp,
        }
        conn.execute(
            """UPDATE executions SET date_fin=?, statut='succes', nb_documents=1,
                   nb_extractions=?, details_json=? WHERE id=?""",
            (maintenant_iso(), len(elements), json_stable(details), execution_id),
        )
        return {"statut": statut_document, "documents": 1,
                "elements": len(elements), **details}


def importer_corpus_et_resultats(
    chemin_base: Path | str = CHEMIN_BASE,
    chemin_resultats: Path | str = RACINE_PROJET / "resultats_unifies.json",
) -> dict:
    """Importe le corpus complet et les résultats sans créer de doublons."""
    initialiser_base(chemin_base)
    resultats = json.loads(Path(chemin_resultats).read_text(encoding="utf-8"))
    date_debut = maintenant_iso()

    with connexion(chemin_base) as conn:
        curseur = conn.execute(
            "INSERT INTO executions(date_debut, statut) VALUES (?, 'en_cours')",
            (date_debut,),
        )
        execution_id = int(curseur.lastrowid)
        documents_par_nom: dict[tuple[str, str], int] = {}

        # Seuls les dossiers métier constituent le corpus officiel. Les jeux
        # d'essai (par exemple data/Tests_Externes) restent isolés jusqu'à une
        # intégration volontaire depuis l'interface.
        dossiers_corpus = (
            "CCTP", "DQE", "Contrats", "Guide_Metier", "Rapports", "Autres_BTP",
        )
        fichiers_pdf = sorted(
            (chemin for dossier in dossiers_corpus
             for chemin in (DOSSIER_DATA / dossier).glob("*.pdf")),
            key=lambda p: p.as_posix().casefold(),
        )
        for chemin in fichiers_pdf:
            document_id = ajouter_ou_actualiser_document(conn, chemin)
            documents_par_nom[(detecter_type_document(chemin), chemin.name)] = document_id

        ajouts = 0
        ignores = 0
        documents_avec_extractions: set[int] = set()
        for element in resultats:
            type_document = element["type_document"]
            nom_fichier = element["fichier_source"]
            document_id = documents_par_nom.get((type_document, nom_fichier))
            if document_id is None:
                raise ValueError(f"Document source introuvable : {type_document}/{nom_fichier}")

            donnees = element.get("donnees", {})
            section = donnees.get("section")
            texte_source = donnees.get("texte_source")
            cle = cle_extraction(
                document_id, type_document, element.get("page"),
                element.get("categorie", ""), element.get("libelle") or "", donnees,
            )
            avant = conn.total_changes
            conn.execute(
                """
                INSERT OR IGNORE INTO extractions(
                    document_id, type_document, page, categorie, libelle, section,
                    texte_source, donnees_json, statut_validation, cle_unique,
                    date_creation, date_modification
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id, type_document, element.get("page"),
                    element.get("categorie", ""), element.get("libelle") or "",
                    section, texte_source, json_stable(donnees), statut_extraction(element),
                    cle, maintenant_iso(), maintenant_iso(),
                ),
            )
            if conn.total_changes > avant:
                ajouts += 1
            else:
                ignores += 1
            documents_avec_extractions.add(document_id)

        date_analyse = maintenant_iso()
        for document_id in documents_par_nom.values():
            statut = "traite" if document_id in documents_avec_extractions else "sans_extraction"
            conn.execute(
                "UPDATE documents SET statut=?, date_derniere_analyse=? WHERE id=? AND statut!='erreur'",
                (statut, date_analyse, document_id),
            )

        total_extractions = conn.execute("SELECT COUNT(*) AS n FROM extractions").fetchone()["n"]
        details = {
            "ajouts": ajouts,
            "doublons_ignores": ignores,
            "total_base": total_extractions,
        }
        conn.execute(
            """
            UPDATE executions SET date_fin=?, statut='succes', nb_documents=?,
                nb_extractions=?, details_json=? WHERE id=?
            """,
            (maintenant_iso(), len(fichiers_pdf), len(resultats), json_stable(details), execution_id),
        )
        return {
            "documents": len(fichiers_pdf),
            "extractions_source": len(resultats),
            **details,
        }


def importer_analyses_nlp(
    chemin_base: Path | str = CHEMIN_BASE,
    chemin_resultats: Path | str = RACINE_PROJET / "resultats_nlp.json",
) -> dict:
    """Relie les analyses NLP aux extractions existantes sans doublons."""
    initialiser_base(chemin_base)
    chemin = Path(chemin_resultats)
    if not chemin.exists():
        raise FileNotFoundError(f"Résultats NLP introuvables : {chemin}")
    resultats = json.loads(chemin.read_text(encoding="utf-8"))

    with connexion(chemin_base) as conn:
        documents = {
            (ligne["type_document"], ligne["nom_fichier"]): ligne["id"]
            for ligne in conn.execute("SELECT id, type_document, nom_fichier FROM documents")
        }
        analyses_par_extraction: dict[int, dict] = {}
        sans_correspondance = 0
        for element in resultats:
            type_document = element.get("type_document")
            document_id = documents.get((type_document, element.get("fichier_source")))
            analyse = element.get("analyse_nlp")
            if document_id is None or not analyse:
                sans_correspondance += 1
                continue
            donnees = element.get("donnees", {})
            cle = cle_extraction(
                document_id, type_document, element.get("page"),
                element.get("categorie", ""), element.get("libelle") or "", donnees,
            )
            extraction = conn.execute(
                "SELECT id FROM extractions WHERE cle_unique=?", (cle,)
            ).fetchone()
            if extraction is None:
                sans_correspondance += 1
                continue
            analyses_par_extraction[int(extraction["id"])] = analyse

        ajouts = 0
        mises_a_jour = 0
        for extraction_id, analyse in analyses_par_extraction.items():
            existe = conn.execute(
                "SELECT 1 FROM analyses_nlp WHERE extraction_id=?", (extraction_id,)
            ).fetchone()
            conn.execute(
                """
                INSERT INTO analyses_nlp(
                    extraction_id, version_nlp, methode, texte_normalise,
                    entites_json, date_analyse
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(extraction_id) DO UPDATE SET
                    version_nlp=excluded.version_nlp,
                    methode=excluded.methode,
                    texte_normalise=excluded.texte_normalise,
                    entites_json=excluded.entites_json,
                    date_analyse=excluded.date_analyse
                """,
                (
                    extraction_id, analyse.get("version", "inconnue"),
                    analyse.get("methode", "inconnue"), analyse.get("texte_normalise", ""),
                    json_stable(analyse.get("entites", {})), maintenant_iso(),
                ),
            )
            ajouts += 0 if existe else 1
            mises_a_jour += 1 if existe else 0

        return {
            "analyses_source": len(resultats),
            "analyses_uniques": len(analyses_par_extraction),
            "ajouts": ajouts,
            "mises_a_jour": mises_a_jour,
            "sans_correspondance": sans_correspondance,
        }


def importer_extractions_metier(
    chemin_base: Path | str = CHEMIN_BASE,
    chemin_resultats: Path | str = RACINE_PROJET / "resultats_documents_metier.json",
) -> dict:
    """Importe les contrats, guides et reportages dans une table dédiée."""
    initialiser_base(chemin_base)
    resultats = json.loads(Path(chemin_resultats).read_text(encoding="utf-8"))
    with connexion(chemin_base) as conn:
        documents = {
            (ligne["categorie_metier"], ligne["nom_fichier"]): ligne["id"]
            for ligne in conn.execute("SELECT id, categorie_metier, nom_fichier FROM documents")
        }
        ajouts = mises_a_jour = sans_correspondance = 0
        documents_traites: set[int] = set()
        for element in resultats:
            type_document = element["type_document"]
            document_id = documents.get((type_document, element["fichier_source"]))
            if document_id is None:
                sans_correspondance += 1
                continue
            donnees = element.get("donnees", {})
            qualite = donnees.get("qualite_texte", "bonne")
            statut = donnees.get("statut_validation", "a_verifier" if qualite == "degradee" else "extrait")
            cle = cle_extraction(document_id, type_document, element.get("page"),
                                 element.get("categorie", ""), element.get("libelle", ""), donnees)
            existe = conn.execute("SELECT 1 FROM extractions_metier WHERE cle_unique=?", (cle,)).fetchone()
            conn.execute(
                """INSERT INTO extractions_metier(
                       document_id, type_document, page, categorie, libelle, texte_source,
                       donnees_json, qualite_texte, statut_validation, cle_unique,
                       date_creation, date_modification)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(cle_unique) DO UPDATE SET
                       donnees_json=excluded.donnees_json,
                       qualite_texte=excluded.qualite_texte,
                       statut_validation=excluded.statut_validation,
                       date_modification=excluded.date_modification""",
                (document_id, type_document, element.get("page"), element.get("categorie", ""),
                 element.get("libelle", ""), donnees.get("texte_source", ""), json_stable(donnees),
                 qualite, statut, cle, maintenant_iso(), maintenant_iso()),
            )
            ajouts += 0 if existe else 1
            mises_a_jour += 1 if existe else 0
            documents_traites.add(document_id)
        for document_id in documents_traites:
            conn.execute("UPDATE documents SET statut='traite', date_derniere_analyse=? WHERE id=?",
                         (maintenant_iso(), document_id))
        return {"extractions_source": len(resultats), "ajouts": ajouts,
                "mises_a_jour": mises_a_jour, "sans_correspondance": sans_correspondance}


def _trouver_extraction_rapprochement(
    conn: sqlite3.Connection, type_document: str, source: dict
) -> int | None:
    """Retrouve l'extraction d'origine à partir de sa preuve traçable."""
    parametres: list = [type_document, source.get("fichier_source"), source.get("page"), source.get("libelle", "")]
    condition = ""
    if type_document == "DQE" and source.get("numero_poste") is not None:
        condition = " AND json_extract(e.donnees_json, '$.numero_poste')=?"
        parametres.append(str(source["numero_poste"]))
    ligne = conn.execute(
        """SELECT e.id FROM extractions e
           JOIN documents d ON d.id=e.document_id
           WHERE e.type_document=? AND d.nom_fichier=? AND e.page IS ? AND e.libelle=?"""
        + condition + " ORDER BY e.id LIMIT 1",
        parametres,
    ).fetchone()
    return int(ligne["id"]) if ligne else None


def importer_rapprochements(
    chemin_base: Path | str = CHEMIN_BASE,
    chemin_resultats: Path | str = RACINE_PROJET / "resultats_rapprochement.json",
) -> dict:
    """Stocke les candidats du moteur sans effacer les décisions humaines."""
    initialiser_base(chemin_base)
    resultat = json.loads(Path(chemin_resultats).read_text(encoding="utf-8"))
    version = str(resultat.get("version", "inconnue"))
    with connexion(chemin_base) as conn:
        conn.execute("UPDATE rapprochements SET actif=0")
        ajouts = mises_a_jour = sans_correspondance_source = 0
        erreurs_liaison = 0
        for proposition in resultat.get("rapprochements", []):
            dqe_id = _trouver_extraction_rapprochement(conn, "DQE", proposition["dqe"])
            if dqe_id is None:
                erreurs_liaison += 1
                continue
            candidats = proposition.get("candidats", [])
            if not candidats:
                candidats = [None]
                sans_correspondance_source += 1
            for rang, candidat in enumerate(candidats, 1):
                cctp_id = None
                if candidat:
                    cctp_id = _trouver_extraction_rapprochement(conn, "CCTP", candidat["cctp"])
                    if cctp_id is None:
                        erreurs_liaison += 1
                        continue
                cle_brute = f"{dqe_id}:{cctp_id if cctp_id is not None else 'aucun'}"
                cle = hashlib.sha256(cle_brute.encode("utf-8")).hexdigest()
                existe = conn.execute("SELECT 1 FROM rapprochements WHERE cle_unique=?", (cle,)).fetchone()
                justification = {
                    "similarite_lexicale": candidat.get("similarite_lexicale") if candidat else None,
                    "similarite_entites": candidat.get("similarite_entites") if candidat else None,
                    "mots_techniques_communs": candidat.get("mots_techniques_communs", []) if candidat else [],
                    "entites_communes": candidat.get("entites_communes", []) if candidat else [],
                }
                statut = "candidat_trouve" if candidat else "sans_correspondance"
                decision_defaut = "a_valider" if candidat else "non_requise"
                conn.execute(
                    """INSERT INTO rapprochements(
                           extraction_dqe_id, extraction_cctp_id, rang_candidat, score, niveau,
                           justification_json, statut_systeme, decision_humaine, actif,
                           cle_unique, version_moteur, date_creation, date_modification)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                       ON CONFLICT(cle_unique) DO UPDATE SET
                           rang_candidat=excluded.rang_candidat, score=excluded.score,
                           niveau=excluded.niveau, justification_json=excluded.justification_json,
                           statut_systeme=excluded.statut_systeme, actif=1,
                           version_moteur=excluded.version_moteur,
                           date_modification=excluded.date_modification""",
                    (dqe_id, cctp_id, rang, candidat.get("score") if candidat else None,
                     candidat.get("niveau") if candidat else "sans_correspondance",
                     json_stable(justification), statut, decision_defaut, cle, version,
                     maintenant_iso(), maintenant_iso()),
                )
                ajouts += 0 if existe else 1
                mises_a_jour += 1 if existe else 0
        actifs = conn.execute("SELECT COUNT(*) AS n FROM rapprochements WHERE actif=1").fetchone()["n"]
        return {"postes_dqe_source": len(resultat.get("rapprochements", [])),
                "lignes_actives": actifs, "ajouts": ajouts, "mises_a_jour": mises_a_jour,
                "postes_sans_correspondance": sans_correspondance_source,
                "erreurs_liaison": erreurs_liaison}


def statistiques_tableau_de_bord(chemin_base: Path | str = CHEMIN_BASE) -> dict:
    with connexion(chemin_base) as conn:
        stats = {
            "documents": conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"],
            "extractions": conn.execute("SELECT COUNT(*) AS n FROM extractions").fetchone()["n"],
            "corrections": conn.execute("SELECT COUNT(*) AS n FROM corrections").fetchone()["n"],
            "analyses_nlp": conn.execute("SELECT COUNT(*) AS n FROM analyses_nlp").fetchone()["n"],
            "extractions_metier": conn.execute("SELECT COUNT(*) AS n FROM extractions_metier").fetchone()["n"],
            "rapprochements_actifs": conn.execute("SELECT COUNT(*) AS n FROM rapprochements WHERE actif=1").fetchone()["n"],
            "rapprochements_a_valider": conn.execute(
                "SELECT COUNT(*) AS n FROM rapprochements WHERE actif=1 AND decision_humaine='a_valider'"
            ).fetchone()["n"],
            "par_type": {
                ligne["type_document"]: ligne["n"]
                for ligne in conn.execute("SELECT type_document, COUNT(*) AS n FROM extractions GROUP BY type_document")
            },
            "par_statut": {
                ligne["statut_validation"]: ligne["n"]
                for ligne in conn.execute("SELECT statut_validation, COUNT(*) AS n FROM extractions GROUP BY statut_validation")
            },
        }
        return stats


def lister_analyses_nlp(chemin_base: Path | str = CHEMIN_BASE) -> list[dict]:
    """Retourne les entités NLP avec leur document et leur preuve source."""
    with connexion(chemin_base) as conn:
        lignes = conn.execute(
            """
            SELECT n.id, n.extraction_id, n.version_nlp, n.methode,
                   n.texte_normalise, n.entites_json, n.date_analyse,
                   e.page, e.libelle, e.texte_source, e.type_document,
                   d.nom_fichier
            FROM analyses_nlp n
            JOIN extractions e ON e.id=n.extraction_id
            JOIN documents d ON d.id=e.document_id
            ORDER BY d.nom_fichier, e.page, e.id
            """
        ).fetchall()
        resultats = []
        for ligne in lignes:
            element = dict(ligne)
            element["entites"] = json.loads(element.pop("entites_json"))
            resultats.append(element)
        return resultats


def lister_documents(chemin_base: Path | str = CHEMIN_BASE) -> list[dict]:
    with connexion(chemin_base) as conn:
        lignes = conn.execute(
            """
            SELECT d.*,
                   (SELECT COUNT(*) FROM extractions e WHERE e.document_id=d.id)
                   + (SELECT COUNT(*) FROM extractions_metier m WHERE m.document_id=d.id)
                   AS nombre_extractions
            FROM documents d
            ORDER BY d.date_ajout DESC, d.nom_fichier
            """
        ).fetchall()
        return [dict(ligne) for ligne in lignes]


def lister_extractions_metier(
    chemin_base: Path | str = CHEMIN_BASE,
    type_document: str | None = None,
    categorie: str | None = None,
    qualite: str | None = None,
) -> list[dict]:
    """Retourne les informations métier avec leur document et leur preuve."""
    conditions: list[str] = []
    parametres: list[str] = []
    for colonne, valeur in (
        ("m.type_document", type_document),
        ("m.categorie", categorie),
        ("m.qualite_texte", qualite),
    ):
        if valeur:
            conditions.append(f"{colonne}=?")
            parametres.append(valeur)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    with connexion(chemin_base) as conn:
        lignes = conn.execute(
            """SELECT m.*, d.nom_fichier, d.chemin_relatif
               FROM extractions_metier m
               JOIN documents d ON d.id=m.document_id"""
            + where + " ORDER BY m.type_document, d.nom_fichier, m.page, m.id",
            parametres,
        ).fetchall()
        resultats = []
        for ligne in lignes:
            element = dict(ligne)
            element["donnees"] = json.loads(element.pop("donnees_json"))
            resultats.append(element)
        return resultats


def lister_validations_metier(
    chemin_base: Path | str = CHEMIN_BASE,
    a_verifier_seulement: bool = False,
) -> list[dict]:
    """Retourne la file de validation des contrats, guides et reportages."""
    filtre = "WHERE m.statut_validation='a_verifier' AND c.id IS NULL" if a_verifier_seulement else ""
    with connexion(chemin_base) as conn:
        lignes = conn.execute(
            f"""SELECT m.*, d.nom_fichier, d.chemin_relatif,
                       c.decision, c.ancienne_categorie, c.ancienne_valeur,
                       c.nouvelle_categorie, c.nouvelle_valeur,
                       c.commentaire AS commentaire_controle,
                       c.auteur, c.date_controle
                FROM extractions_metier m
                JOIN documents d ON d.id=m.document_id
                LEFT JOIN controles_metier c ON c.extraction_metier_id=m.id
                {filtre}
                ORDER BY CASE WHEN c.id IS NULL THEN 0 ELSE 1 END,
                         d.nom_fichier, m.page, m.id"""
        ).fetchall()
        resultats = []
        for ligne in lignes:
            element = dict(ligne)
            element["donnees"] = json.loads(element.pop("donnees_json"))
            resultats.append(element)
        return resultats


def enregistrer_validation_metier(
    extraction_metier_id: int,
    decision: str,
    nouvelle_categorie: str | None = None,
    nouvelle_valeur: str | None = None,
    commentaire: str = "",
    auteur: str = "utilisateur",
    chemin_base: Path | str = CHEMIN_BASE,
) -> dict:
    """Valide, corrige ou rejette un extrait métier en gardant sa valeur initiale."""
    if decision not in {"valide", "corrige", "rejete"}:
        raise ValueError("Décision métier invalide")
    with connexion(chemin_base) as conn:
        ligne = conn.execute(
            "SELECT categorie, libelle FROM extractions_metier WHERE id=?",
            (extraction_metier_id,),
        ).fetchone()
        if ligne is None:
            raise ValueError(f"Extraction métier {extraction_metier_id} introuvable")

        categorie_finale = (nouvelle_categorie or ligne["categorie"]).strip()
        valeur_finale = (nouvelle_valeur or ligne["libelle"]).strip()
        if decision == "corrige" and (not categorie_finale or not valeur_finale):
            raise ValueError("La catégorie et la valeur corrigées sont obligatoires")

        conn.execute(
            """INSERT INTO controles_metier(
                   extraction_metier_id, decision, ancienne_categorie, ancienne_valeur,
                   nouvelle_categorie, nouvelle_valeur, commentaire, auteur, date_controle
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(extraction_metier_id) DO UPDATE SET
                   decision=excluded.decision,
                   nouvelle_categorie=excluded.nouvelle_categorie,
                   nouvelle_valeur=excluded.nouvelle_valeur,
                   commentaire=excluded.commentaire,
                   auteur=excluded.auteur,
                   date_controle=excluded.date_controle""",
            (
                extraction_metier_id, decision, ligne["categorie"], ligne["libelle"],
                categorie_finale if decision == "corrige" else None,
                valeur_finale if decision == "corrige" else None,
                commentaire.strip(), auteur.strip() or "utilisateur", maintenant_iso(),
            ),
        )
        if decision == "corrige":
            conn.execute(
                """UPDATE extractions_metier
                   SET categorie=?, libelle=?, statut_validation='corrige', date_modification=?
                   WHERE id=?""",
                (categorie_finale, valeur_finale, maintenant_iso(), extraction_metier_id),
            )
        elif decision == "valide":
            conn.execute(
                """UPDATE extractions_metier
                   SET statut_validation='valide', date_modification=? WHERE id=?""",
                (maintenant_iso(), extraction_metier_id),
            )
        # Un rejet est conservé dans controles_metier. Le texte source reste intact
        # et l'extrait n'est jamais transformé en information validée.
        return {
            "id": extraction_metier_id,
            "decision": decision,
            "categorie": categorie_finale,
            "valeur": valeur_finale,
        }


def lister_validations_extractions(
    chemin_base: Path | str = CHEMIN_BASE,
    a_verifier_seulement: bool = False,
) -> list[dict]:
    """Retourne les extractions CCTP/DQE destinées au contrôle humain."""
    filtre = "WHERE e.statut_validation='a_verifier' AND c.id IS NULL" if a_verifier_seulement else ""
    with connexion(chemin_base) as conn:
        lignes = conn.execute(
            f"""SELECT e.*, d.nom_fichier, d.chemin_relatif,
                       c.decision, c.ancienne_categorie, c.ancienne_valeur,
                       c.nouvelle_categorie, c.nouvelle_valeur,
                       c.commentaire AS commentaire_controle,
                       c.auteur, c.date_controle
                FROM extractions e
                JOIN documents d ON d.id=e.document_id
                LEFT JOIN controles_extractions c ON c.extraction_id=e.id
                {filtre}
                ORDER BY CASE WHEN c.id IS NULL THEN 0 ELSE 1 END,
                         d.nom_fichier, e.page, e.id"""
        ).fetchall()
        resultats = []
        for ligne in lignes:
            element = dict(ligne)
            element["donnees"] = json.loads(element.pop("donnees_json"))
            resultats.append(element)
        return resultats


def enregistrer_validation_extraction(
    extraction_id: int,
    decision: str,
    nouvelle_categorie: str | None = None,
    nouvelle_valeur: str | None = None,
    commentaire: str = "",
    auteur: str = "utilisateur",
    chemin_base: Path | str = CHEMIN_BASE,
) -> dict:
    """Enregistre la décision humaine sur une extraction CCTP ou DQE."""
    if decision not in {"valide", "corrige", "rejete"}:
        raise ValueError("Décision technique invalide")
    with connexion(chemin_base) as conn:
        ligne = conn.execute(
            "SELECT categorie, libelle FROM extractions WHERE id=?", (extraction_id,)
        ).fetchone()
        if ligne is None:
            raise ValueError(f"Extraction {extraction_id} introuvable")
        categorie_finale = (nouvelle_categorie or ligne["categorie"]).strip()
        valeur_finale = (nouvelle_valeur or ligne["libelle"]).strip()
        if decision == "corrige" and (not categorie_finale or not valeur_finale):
            raise ValueError("La catégorie et la valeur corrigées sont obligatoires")
        conn.execute(
            """INSERT INTO controles_extractions(
                   extraction_id, decision, ancienne_categorie, ancienne_valeur,
                   nouvelle_categorie, nouvelle_valeur, commentaire, auteur, date_controle
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(extraction_id) DO UPDATE SET
                   decision=excluded.decision,
                   nouvelle_categorie=excluded.nouvelle_categorie,
                   nouvelle_valeur=excluded.nouvelle_valeur,
                   commentaire=excluded.commentaire,
                   auteur=excluded.auteur,
                   date_controle=excluded.date_controle""",
            (
                extraction_id, decision, ligne["categorie"], ligne["libelle"],
                categorie_finale if decision == "corrige" else None,
                valeur_finale if decision == "corrige" else None,
                commentaire.strip(), auteur.strip() or "utilisateur", maintenant_iso(),
            ),
        )
        if decision == "corrige":
            conn.execute(
                """UPDATE extractions SET categorie=?, libelle=?, statut_validation='corrige',
                       date_modification=? WHERE id=?""",
                (categorie_finale, valeur_finale, maintenant_iso(), extraction_id),
            )
        elif decision == "valide":
            conn.execute(
                """UPDATE extractions SET statut_validation='valide', date_modification=?
                   WHERE id=?""",
                (maintenant_iso(), extraction_id),
            )
        return {
            "id": extraction_id, "decision": decision,
            "categorie": categorie_finale, "valeur": valeur_finale,
        }


def lister_rapprochements(
    chemin_base: Path | str = CHEMIN_BASE,
    actifs_seulement: bool = True,
) -> list[dict]:
    """Retourne les rapprochements avec les deux preuves documentaires."""
    where = "WHERE r.actif=1" if actifs_seulement else ""
    with connexion(chemin_base) as conn:
        lignes = conn.execute(
            f"""SELECT r.*,
                       dqe.page AS dqe_page, dqe.libelle AS dqe_libelle,
                       dqe.texte_source AS dqe_texte_source,
                       json_extract(dqe.donnees_json, '$.numero_poste') AS dqe_numero_poste,
                       json_extract(dqe.donnees_json, '$.unite') AS dqe_unite,
                       doc_dqe.nom_fichier AS dqe_document,
                       cctp.page AS cctp_page, cctp.libelle AS cctp_libelle,
                       cctp.texte_source AS cctp_texte_source, cctp.section AS cctp_section,
                       doc_cctp.nom_fichier AS cctp_document
                FROM rapprochements r
                JOIN extractions dqe ON dqe.id=r.extraction_dqe_id
                JOIN documents doc_dqe ON doc_dqe.id=dqe.document_id
                LEFT JOIN extractions cctp ON cctp.id=r.extraction_cctp_id
                LEFT JOIN documents doc_cctp ON doc_cctp.id=cctp.document_id
                {where}
                ORDER BY doc_dqe.nom_fichier, dqe.page, dqe.id, r.rang_candidat"""
        ).fetchall()
        resultats = []
        for ligne in lignes:
            element = dict(ligne)
            element["justification"] = json.loads(element.pop("justification_json"))
            resultats.append(element)
        return resultats


def enregistrer_decision_rapprochement(
    rapprochement_id: int,
    decision: str,
    commentaire: str = "",
    chemin_base: Path | str = CHEMIN_BASE,
) -> None:
    """Enregistre l'avis du technicien sans modifier les documents sources."""
    if decision not in {"a_valider", "accepte", "rejete"}:
        raise ValueError("Décision de rapprochement invalide")
    with connexion(chemin_base) as conn:
        ligne = conn.execute(
            "SELECT extraction_cctp_id FROM rapprochements WHERE id=? AND actif=1",
            (rapprochement_id,),
        ).fetchone()
        if ligne is None:
            raise ValueError(f"Rapprochement actif {rapprochement_id} introuvable")
        if ligne["extraction_cctp_id"] is None:
            raise ValueError("Un poste sans candidat ne peut pas être accepté ou rejeté")
        conn.execute(
            """UPDATE rapprochements
               SET decision_humaine=?, commentaire=?, date_modification=?
               WHERE id=?""",
            (decision, commentaire.strip(), maintenant_iso(), rapprochement_id),
        )


def lister_extractions(
    chemin_base: Path | str = CHEMIN_BASE,
    document_id: int | None = None,
    type_document: str | None = None,
    statut: str | None = None,
) -> list[dict]:
    conditions = []
    parametres = []
    if document_id is not None:
        conditions.append("e.document_id=?")
        parametres.append(document_id)
    if type_document:
        conditions.append("e.type_document=?")
        parametres.append(type_document)
    if statut:
        conditions.append("e.statut_validation=?")
        parametres.append(statut)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    with connexion(chemin_base) as conn:
        lignes = conn.execute(
            """
            SELECT e.*, d.nom_fichier
            FROM extractions e JOIN documents d ON d.id=e.document_id
            """ + where + " ORDER BY d.nom_fichier, e.page, e.id",
            parametres,
        ).fetchall()
        resultats = []
        for ligne in lignes:
            element = dict(ligne)
            element["donnees"] = json.loads(element.pop("donnees_json"))
            resultats.append(element)
        return resultats


def lister_executions(chemin_base: Path | str = CHEMIN_BASE, limite: int = 20) -> list[dict]:
    with connexion(chemin_base) as conn:
        lignes = conn.execute(
            "SELECT * FROM executions ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
        resultats = []
        for ligne in lignes:
            element = dict(ligne)
            element["details"] = json.loads(element.pop("details_json")) if element.get("details_json") else None
            resultats.append(element)
        return resultats


def lister_corrections(chemin_base: Path | str = CHEMIN_BASE, limite: int = 100) -> list[dict]:
    with connexion(chemin_base) as conn:
        lignes = conn.execute(
            """
            SELECT c.*, d.nom_fichier, e.page, e.libelle
            FROM corrections c
            JOIN extractions e ON e.id=c.extraction_id
            JOIN documents d ON d.id=e.document_id
            ORDER BY c.id DESC LIMIT ?
            """,
            (limite,),
        ).fetchall()
        resultats = []
        for ligne in lignes:
            element = dict(ligne)
            element["ancienne_valeur"] = json.loads(element.pop("ancienne_valeur_json"))
            element["nouvelle_valeur"] = json.loads(element.pop("nouvelle_valeur_json"))
            resultats.append(element)
        return resultats


def corriger_extraction(
    extraction_id: int,
    nouvelles_donnees: dict,
    commentaire: str = "",
    auteur: str = "utilisateur",
    chemin_base: Path | str = CHEMIN_BASE,
) -> None:
    """Modifie une extraction et conserve obligatoirement l'ancienne valeur."""
    with connexion(chemin_base) as conn:
        ligne = conn.execute(
            "SELECT donnees_json FROM extractions WHERE id=?", (extraction_id,)
        ).fetchone()
        if ligne is None:
            raise ValueError(f"Extraction {extraction_id} introuvable")
        ancienne = json.loads(ligne["donnees_json"])
        if ancienne == nouvelles_donnees:
            return
        conn.execute(
            """
            INSERT INTO corrections(
                extraction_id, ancienne_valeur_json, nouvelle_valeur_json,
                commentaire, auteur, date_correction
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                extraction_id, json_stable(ancienne), json_stable(nouvelles_donnees),
                commentaire, auteur, maintenant_iso(),
            ),
        )
        conn.execute(
            """
            UPDATE extractions SET donnees_json=?, statut_validation='corrige',
                date_modification=? WHERE id=?
            """,
            (json_stable(nouvelles_donnees), maintenant_iso(), extraction_id),
        )


if __name__ == "__main__":
    bilan = importer_corpus_et_resultats()
    print(json.dumps(bilan, ensure_ascii=False, indent=2))
    print(json.dumps(statistiques_tableau_de_bord(), ensure_ascii=False, indent=2))
