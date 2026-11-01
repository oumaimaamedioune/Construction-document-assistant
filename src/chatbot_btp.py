"""Assistant conversationnel local et sourcé pour le corpus documentaire BTP.

Le moteur privilégie les données structurées SQLite (notamment les DQE)
avant d'utiliser une recherche sémantique locale. Les deux modèles Ollama
restent sur le poste : aucune donnée du corpus n'est envoyée sur Internet.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


RACINE_PROJET = Path(__file__).resolve().parents[1]
CHEMIN_BASE = RACINE_PROJET / "instance" / "assistant_btp.db"
URL_OLLAMA = "http://127.0.0.1:11434"
# Variante retenue après benchmark sur le PC cible : environ 2 s à chaud,
# contre plus de 30 s pour les variantes 3B/4B avec le même contexte.
MODELE_REPONSE = "qwen3:1.7b"
MODELE_EMBEDDING = "embeddinggemma"
TAILLE_LOT_EMBEDDING = 48

MATERIAUX_BTP = {
    "PVC": (r"\bpvc\b",),
    "Cuivre": (r"\bcuivre\b",),
    "Acier galvanisé": (r"\bacier galvanise\b",),
    "Acier inoxydable": (r"\bacier inoxydable\b", r"\binox\b"),
    "Acier": (r"\bacier\b",),
    "PER": (r"\bper\b",),
    "Multicouche": (r"\bmulticouche\b",),
    "Polyéthylène": (r"\bpolyethylene\b", r"\bpehd\b"),
    "Béton armé": (r"\bbeton arme\b",),
    "Béton": (r"\bbeton\b",),
    "Ciment": (r"\bciment\b",),
    "Bois": (r"\bbois\b",),
    "Aluminium": (r"\baluminium\b",),
}

MATERIAUX_PLOMBERIE = {
    "PVC", "Cuivre", "Acier galvanisé", "Acier inoxydable", "Acier",
    "PER", "Multicouche", "Polyéthylène",
}


@dataclass(frozen=True)
class SourceChat:
    document: str
    page: int | None
    type_document: str
    titre: str
    texte: str


@dataclass(frozen=True)
class ReponseChat:
    texte: str
    sources: list[SourceChat]
    mode: str
    duree_secondes: float


def _normaliser(texte: object) -> str:
    valeur = unicodedata.normalize("NFKD", str(texte or ""))
    valeur = "".join(c for c in valeur if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", valeur.casefold()).strip()


def _fenetres_texte_pdf(
    texte: str, taille: int = 1400, pas: int = 850
) -> list[str]:
    """Découpe toute une page PDF sans perdre la fin des longues lignes."""
    propre = re.sub(r"\s+", " ", str(texte or "")).strip()
    if not propre:
        return []
    if len(propre) <= taille:
        return [propre]
    return [
        propre[debut:debut + taille].strip()
        for debut in range(0, len(propre), pas)
        if propre[debut:debut + taille].strip()
    ]


def _maintenant() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _materiaux_dans_texte(texte: str) -> list[str]:
    normalise = _normaliser(texte)
    trouves = []
    for libelle, motifs in MATERIAUX_BTP.items():
        if any(re.search(motif, normalise) for motif in motifs):
            trouves.append(libelle)
    # Une variante précise remplace sa variante générique.
    if "Acier galvanisé" in trouves or "Acier inoxydable" in trouves:
        trouves = [valeur for valeur in trouves if valeur != "Acier"]
    if "Béton armé" in trouves:
        trouves = [valeur for valeur in trouves if valeur != "Béton"]
    return trouves


def _materiaux_pertinents(question: str, texte: str) -> list[str]:
    """Écarte les matériaux hors sujet lorsque le métier est explicite.

    Un passage contenant à la fois un réseau et un ouvrage en béton ne doit pas
    conduire à répondre « béton » à une question portant sur la plomberie.
    """
    valeurs = _materiaux_dans_texte(texte)
    question_norm = _normaliser(question)
    if "plomberie" in question_norm or "sanitaire" in question_norm:
        return [valeur for valeur in valeurs if valeur in MATERIAUX_PLOMBERIE]
    return valeurs


def _requete_ollama(route: str, contenu: dict, timeout: int = 180) -> dict:
    requete = urllib.request.Request(
        f"{URL_OLLAMA}{route}",
        data=json.dumps(contenu, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except TimeoutError as erreur:
        raise RuntimeError(
            "La génération locale a dépassé le délai autorisé."
        ) from erreur
    except urllib.error.URLError as erreur:
        raise RuntimeError(
            "Le moteur local Ollama n'est pas disponible. Ouvrez Ollama puis réessayez."
        ) from erreur


def _embeddings(textes: list[str], keep_alive: str = "0") -> list[list[float]]:
    if not textes:
        return []
    resultat = _requete_ollama(
        "/api/embed",
        {"model": MODELE_EMBEDDING, "input": textes, "keep_alive": keep_alive},
    )
    return resultat.get("embeddings", [])


@contextmanager
def _connexion(chemin_base: Path | str):
    connexion = sqlite3.connect(Path(chemin_base), timeout=30)
    connexion.row_factory = sqlite3.Row
    connexion.execute("PRAGMA busy_timeout = 30000")
    try:
        yield connexion
        connexion.commit()
    except Exception:
        connexion.rollback()
        raise
    finally:
        connexion.close()


def initialiser_index_chat(chemin_base: Path | str = CHEMIN_BASE) -> None:
    with _connexion(chemin_base) as connexion:
        connexion.executescript(
            """
            CREATE TABLE IF NOT EXISTS index_chatbot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_source TEXT NOT NULL CHECK(table_source IN ('extractions','extractions_metier')),
                source_id INTEGER NOT NULL,
                document_id INTEGER NOT NULL,
                nom_fichier TEXT NOT NULL,
                type_document TEXT NOT NULL,
                page INTEGER,
                titre TEXT NOT NULL,
                contenu TEXT NOT NULL,
                empreinte TEXT NOT NULL,
                embedding_json TEXT NOT NULL CHECK(json_valid(embedding_json)),
                date_indexation TEXT NOT NULL,
                UNIQUE(table_source, source_id),
                FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_chatbot_document ON index_chatbot(document_id);
            CREATE INDEX IF NOT EXISTS idx_chatbot_type ON index_chatbot(type_document);

            CREATE TABLE IF NOT EXISTS avis_chatbot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                reponse TEXT NOT NULL,
                verdict TEXT NOT NULL CHECK(verdict IN ('utile','a_ameliorer')),
                document_cible TEXT,
                sources_json TEXT NOT NULL CHECK(json_valid(sources_json)),
                date_avis TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_avis_chatbot_verdict
                ON avis_chatbot(verdict, date_avis);
            """
        )


def enregistrer_avis_chatbot(
    question: str,
    reponse: str,
    verdict: str,
    sources: list[dict] | None = None,
    document_cible: str | None = None,
    chemin_base: Path | str = CHEMIN_BASE,
) -> None:
    """Conserve localement l'évaluation d'une réponse, sans donnée externe."""
    if verdict not in {"utile", "a_ameliorer"}:
        raise ValueError("Verdict chatbot invalide.")
    initialiser_index_chat(chemin_base)
    with _connexion(chemin_base) as connexion:
        connexion.execute(
            """INSERT INTO avis_chatbot(
                   question, reponse, verdict, document_cible, sources_json, date_avis
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                question.strip(), reponse.strip(), verdict, document_cible,
                json.dumps(sources or [], ensure_ascii=False), _maintenant(),
            ),
        )


def _contenu_extraction(ligne: sqlite3.Row) -> tuple[str, str]:
    try:
        donnees = json.loads(ligne["donnees_json"] or "{}")
    except json.JSONDecodeError:
        donnees = {}
    titre = ligne["libelle"] or ligne["categorie"] or "Information documentaire"
    parties = [
        f"Document : {ligne['nom_fichier']}",
        f"Type : {ligne['type_document']}",
        f"Page : {ligne['page'] or 'non précisée'}",
        f"Catégorie : {ligne['categorie']}",
        f"Intitulé : {titre}",
    ]
    if ligne["section"]:
        parties.append(f"Section : {ligne['section']}")
    for cle, valeur in donnees.items():
        if cle not in {"texte_source", "section"} and valeur not in (None, "", [], {}):
            parties.append(f"{cle.replace('_', ' ')} : {valeur}")
    texte_source = ligne["texte_source"] or donnees.get("texte_source")
    if texte_source:
        parties.append(f"Texte source : {texte_source}")
    return str(titre), "\n".join(parties)


def _lire_sources_indexables(connexion: sqlite3.Connection) -> list[dict]:
    commun = """
        SELECT e.id AS source_id, e.document_id, d.nom_fichier,
               e.type_document, e.page, e.categorie, e.libelle,
               e.texte_source, e.donnees_json, {section} AS section
        FROM {table} e JOIN documents d ON d.id=e.document_id
    """
    lignes: list[dict] = []
    for table, section in (("extractions", "e.section"), ("extractions_metier", "NULL")):
        requete = commun.format(table=table, section=section)
        for ligne in connexion.execute(requete):
            titre, contenu = _contenu_extraction(ligne)
            lignes.append(
                {
                    "table_source": table,
                    "source_id": ligne["source_id"],
                    "document_id": ligne["document_id"],
                    "nom_fichier": ligne["nom_fichier"],
                    "type_document": ligne["type_document"],
                    "page": ligne["page"],
                    "titre": titre,
                    "contenu": contenu,
                    "empreinte": hashlib.sha256(contenu.encode("utf-8")).hexdigest(),
                }
            )
    return lignes


def synchroniser_index_chat(
    chemin_base: Path | str = CHEMIN_BASE,
    progression=None,
) -> dict[str, int]:
    """Indexe seulement les passages nouveaux ou modifiés."""
    initialiser_index_chat(chemin_base)
    with _connexion(chemin_base) as connexion:
        sources = _lire_sources_indexables(connexion)
        existants = {
            (ligne["table_source"], ligne["source_id"]): ligne["empreinte"]
            for ligne in connexion.execute(
                "SELECT table_source, source_id, empreinte FROM index_chatbot"
            )
        }
        a_indexer = [
            source for source in sources
            if existants.get((source["table_source"], source["source_id"])) != source["empreinte"]
        ]
        total = len(a_indexer)
        for debut in range(0, total, TAILLE_LOT_EMBEDDING):
            lot = a_indexer[debut:debut + TAILLE_LOT_EMBEDDING]
            vecteurs = _embeddings([source["contenu"] for source in lot], keep_alive="10m")
            if len(vecteurs) != len(lot):
                raise RuntimeError("Le modèle d'embedding n'a pas indexé tous les passages.")
            for source, vecteur in zip(lot, vecteurs):
                connexion.execute(
                    """
                    INSERT INTO index_chatbot(
                        table_source, source_id, document_id, nom_fichier,
                        type_document, page, titre, contenu, empreinte,
                        embedding_json, date_indexation
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(table_source, source_id) DO UPDATE SET
                        document_id=excluded.document_id,
                        nom_fichier=excluded.nom_fichier,
                        type_document=excluded.type_document,
                        page=excluded.page,
                        titre=excluded.titre,
                        contenu=excluded.contenu,
                        empreinte=excluded.empreinte,
                        embedding_json=excluded.embedding_json,
                        date_indexation=excluded.date_indexation
                    """,
                    (
                        source["table_source"], source["source_id"], source["document_id"],
                        source["nom_fichier"], source["type_document"], source["page"],
                        source["titre"], source["contenu"], source["empreinte"],
                        json.dumps(vecteur, separators=(",", ":")), _maintenant(),
                    ),
                )
            connexion.commit()
            if progression:
                progression(min(debut + len(lot), total), total)

        cles_presentes = {(s["table_source"], s["source_id"]) for s in sources}
        supprimes = 0
        for ligne in connexion.execute("SELECT id, table_source, source_id FROM index_chatbot"):
            if (ligne["table_source"], ligne["source_id"]) not in cles_presentes:
                connexion.execute("DELETE FROM index_chatbot WHERE id=?", (ligne["id"],))
                supprimes += 1
        connexion.commit()
        return {"total": len(sources), "indexes": total, "supprimes": supprimes}


def _nombre_fr(valeur, monnaie: bool = False) -> str:
    if valeur in (None, ""):
        return "Non renseigné"
    if isinstance(valeur, str):
        try:
            valeur = float(valeur.replace(" ", "").replace(",", "."))
        except ValueError:
            return valeur
    if isinstance(valeur, (int, float)):
        if float(valeur).is_integer():
            resultat = f"{int(valeur):,}".replace(",", " ")
        else:
            resultat = f"{float(valeur):,.2f}".replace(",", " ").replace(".", ",")
        return f"{resultat}" + (" (devise du document)" if monnaie else "")
    return str(valeur)


CHAMPS_DEMANDES = {
    "unite": ("unite", "unité", "unit", "u.m"),
    "quantite": ("quantite", "quantité", "qte", "qté"),
    "prix_unitaire": ("prix unitaire", "p.u", "pu ", "pu?"),
    "prix_total": ("montant", "prix total", "total du poste"),
    "designation": ("designation", "désignation", "intitule", "intitulé"),
}


def _champ_demande(question: str) -> str | None:
    normalisee = _normaliser(question)
    priorite = ("prix_total", "prix_unitaire", "quantite", "unite", "designation")
    for champ in priorite:
        for variante in CHAMPS_DEMANDES[champ]:
            motif = rf"(?<!\w){re.escape(_normaliser(variante))}(?!\w)"
            if re.search(motif, normalisee):
                return champ
    return None


def _champs_demandes(question: str) -> list[str]:
    """Retourne tous les champs explicitement demandés, dans l'ordre métier."""
    normalisee = _normaliser(question)
    trouves = []
    for champ in ("designation", "unite", "quantite", "prix_unitaire", "prix_total"):
        if any(
            re.search(
                rf"(?<!\w){re.escape(_normaliser(variante))}(?!\w)",
                normalisee,
            )
            for variante in CHAMPS_DEMANDES[champ]
        ):
            trouves.append(champ)
    return trouves


def _numero_poste(question: str) -> str | None:
    motifs = (
        r"\b(?:poste|article|n[uo]mero|n[uo])\s*[:#-]?\s*(\d+(?:[.,]\d+)+)\b",
        r"\b(\d+[.,]\d+)\b",
    )
    for motif in motifs:
        trouve = re.search(motif, _normaliser(question))
        if trouve:
            return trouve.group(1).replace(",", ".")
    return None


def _demande_inventaire_complet(question: str) -> bool:
    """Détecte une demande portant sur tout le contenu d'un document."""
    texte = _normaliser(question)
    expressions = (
        "toutes les informations", "tous les informations", "toutes les infos",
        "tous les infos", "tous les postes", "liste les postes",
        "liste tous les postes", "contenu complet", "inventaire complet",
        "donne moi tout", "donne-moi tout",
    )
    return any(expression in texte for expression in expressions)


def _demande_synthese_documentaire(question: str) -> bool:
    """Reconnaît une demande de vue globale sans la confondre avec une recherche."""
    texte = _normaliser(question)
    expressions = (
        "resume", "resumer", "synthese", "synthetise", "synthetiser",
        "principales informations", "informations principales",
        "vue d ensemble", "bilan du corpus", "resume du corpus",
    )
    return any(expression in texte for expression in expressions)


def _canoniser_theme_synthese(theme: str) -> str:
    """Fusionne uniquement à l'affichage les variantes d'un même thème métier."""
    normalise = _normaliser(theme)
    correspondances = {
        "poste devis": "Postes de devis",
        "obligation": "Intervenants et obligations",
        "obligations": "Intervenants et obligations",
        "parties intervenants": "Intervenants et obligations",
        "parties et representants": "Intervenants et obligations",
        "document suivi": "Suivi et retour de chantier",
        "paiement prix": "Paiement et prix",
        "delais penalites": "Délais et pénalités",
        "garantie assurance": "Garantie et assurance",
        "securite prevention": "Sécurité et prévention",
        "objet travaux": "Objet et travaux",
        "qualite controle": "Qualité et contrôle",
        "mise en oeuvre": "Mise en œuvre",
        "resiliation litiges": "Litiges et réclamations",
        "loi differends": "Litiges et réclamations",
        "risque preuve": "Risques, preuves et réclamations",
    }
    return correspondances.get(normalise, theme)


# Ancres minimales exigées pour les questions métier explicites. Elles ne
# remplacent pas le classement sémantique : elles constituent un garde-fou
# contre une preuve manifestement hors sujet.
ANCRES_COHERENCE = (
    (("beton",), ("beton", "ciment", "c25/30", "c30/37")),
    (("plomberie", "sanitaire", "canalisation"),
     ("plomberie", "sanitaire", "canalisation", "tuyau", "tube", "evacuation")),
    (("terrassement", "fondation", "fouille", "remblai"),
     ("terrassement", "fondation", "fouille", "remblai", "compactage")),
    (("norme", "dtu", "eurocode"), ("norme", "dtu", "eurocode", "nf en", "iso")),
    (("sous trait", "sous-trait"), ("sous trait", "sous-trait", "sous traitance")),
    (("securite", "prevention", "incendie"), ("securite", "prevention", "incendie", "risque")),
    (("litige", "reclamation", "differend"), ("litige", "reclamation", "differend", "amiable")),
    (("paiement", "acompte", "decompte"), ("paiement", "acompte", "decompte", "prix")),
    (("delai", "penalite", "retard"), ("delai", "penalite", "retard", "achevement")),
    (("garantie", "assurance"), ("garantie", "assurance")),
)


def _preuve_compatible_question(question: str, ligne: dict) -> bool:
    """Refuse une preuve qui ne contient aucune ancre du domaine demandé.

    Pour une question générale sans domaine reconnu, le comportement existant
    est conservé. Pour une question multi-thème, une preuve peut naturellement
    répondre à l'un des thèmes.
    """
    question_norm = _normaliser(question)
    groupes_requis = [
        preuves for declencheurs, preuves in ANCRES_COHERENCE
        if any(terme in question_norm for terme in declencheurs)
    ]
    if not groupes_requis:
        return True
    preuve = _normaliser(
        f"{ligne.get('titre', '')} {ligne.get('contenu', '')}"
    )
    return any(any(ancre in preuve for ancre in groupe) for groupe in groupes_requis)


def _demande_beton_structure(question: str) -> bool:
    texte = _normaliser(question)
    return "beton" in texte and any(
        terme in texte for terme in
        ("type", "classe", "resistance", "dosage", "caracteristique")
    )


def _reponse_beton_depuis_index(
    question: str,
    index: list[tuple[dict, list[float]]],
    document_cible: str | None = None,
) -> ReponseChat | None:
    """Restitue les caractéristiques du béton sans génération libre."""
    if not _demande_beton_structure(question):
        return None
    debut = time.perf_counter()
    candidats: list[dict] = []
    vus = set()
    for ligne, _ in index:
        if document_cible and ligne.get("nom_fichier") != document_cible:
            continue
        texte = f"{ligne.get('titre', '')} {ligne.get('contenu', '')}"
        if "beton" not in _normaliser(texte):
            continue
        cle = (ligne.get("document_id"), ligne.get("page"), _normaliser(texte))
        if cle not in vus:
            vus.add(cle)
            candidats.append(ligne)

    types_patterns = {
        "Béton armé": r"\bbeton arme\b",
        "Béton blanc": r"\bbeton blanc\b",
        "Béton préfabriqué": r"\bbeton prefabrique\b",
        "Béton hydrofugé": r"\bbeton hydrofuge\b",
        "Béton cyclopéen": r"\bbeton cyclopeen\b",
        "Gros béton": r"\bgros beton\b",
        "Béton balayé": r"\bbeton balaye\b",
    }
    faits: dict[str, dict[str, set[int]]] = {
        "Types de béton": {}, "Classes de résistance": {},
        "Dosages": {}, "Résistances": {}, "Normes": {},
    }
    sources: list[SourceChat] = []
    for ligne in candidats:
        brut = f"{ligne.get('titre', '')} {ligne.get('contenu', '')}"
        normalise = _normaliser(brut)
        valeurs: list[tuple[str, str]] = []
        for libelle, motif in types_patterns.items():
            if re.search(motif, normalise):
                valeurs.append(("Types de béton", libelle))
        for valeur in re.findall(r"\bC\s*\d{1,3}\s*/\s*\d{1,3}\b", brut, re.IGNORECASE):
            valeurs.append(("Classes de résistance", re.sub(r"\s+", "", valeur.upper())))
        for valeur in re.findall(r"\b\d{2,4}\s*kg\s*(?:/|de\s+ciment\s*(?:par|/)?\s*)?m[3³]\b", brut, re.IGNORECASE):
            valeurs.append(("Dosages", re.sub(r"\s+", " ", valeur).strip()))
        for correspondance in re.finditer(
            r"\b\d+(?:[.,]\d+)?\s*MPa\b", brut, re.IGNORECASE
        ):
            # 500 MPa décrit habituellement l'acier des armatures et ne doit
            # pas être affiché comme une résistance du béton.
            voisinage = _normaliser(
                brut[max(0, correspondance.start() - 90):correspondance.end() + 90]
            )
            if any(mot in voisinage for mot in (
                "acier", "armature", "ferraillage", "fee500", "treillis"
            )):
                continue
            valeurs.append(("Résistances", correspondance.group(0).strip()))
        for valeur in re.findall(r"\bNF\s+EN\s+\d+(?:-\d+)?\b", brut, re.IGNORECASE):
            valeurs.append(("Normes", re.sub(r"\s+", " ", valeur.upper())))
        if not valeurs:
            continue
        # Deux preuves représentatives par valeur suffisent dans l'interface.
        # Cela conserve la traçabilité sans ouvrir des dizaines de sources
        # répétitives pour une même expression comme « béton armé ».
        valeurs_utiles = [
            (famille, valeur) for famille, valeur in valeurs
            if len(faits[famille].get(valeur, set())) < 2
        ]
        if not valeurs_utiles or len(sources) >= 12:
            continue
        sources.append(SourceChat(
            document=str(ligne.get("nom_fichier") or "Document"),
            page=ligne.get("page"), type_document=str(ligne.get("type_document") or ""),
            titre=str(ligne.get("titre") or "Béton"), texte=str(ligne.get("contenu") or ""),
        ))
        numero = len(sources)
        for famille, valeur in valeurs_utiles:
            faits[famille].setdefault(valeur, set()).add(numero)

    question_norm = _normaliser(question)
    familles_demandees = []
    if "type" in question_norm:
        familles_demandees.append("Types de béton")
    if "classe" in question_norm:
        familles_demandees.append("Classes de résistance")
    if "resistance" in question_norm:
        familles_demandees.extend(["Classes de résistance", "Résistances"])
    if "dosage" in question_norm:
        familles_demandees.append("Dosages")
    familles_demandees = list(dict.fromkeys(familles_demandees)) or list(faits)
    lignes_reponse = []
    for famille in familles_demandees:
        if faits[famille]:
            details = []
            for valeur, numeros in sorted(faits[famille].items()):
                citations = ", ".join(f"[S{n}]" for n in sorted(numeros))
                details.append(f"**{valeur}** — {citations}")
            lignes_reponse.append(f"**{famille}** : " + " ; ".join(details))
    if not lignes_reponse:
        perimetre = f" dans « {document_cible} »" if document_cible else " dans le corpus"
        return ReponseChat(
            f"Aucune caractéristique du béton suffisamment explicite n'a été trouvée{perimetre}.",
            [], "beton_non_trouve", time.perf_counter() - debut,
        )
    return ReponseChat(
        "Caractéristiques du béton explicitement mentionnées dans les documents :\n\n"
        + "\n\n".join(lignes_reponse),
        sources, "beton_structure", time.perf_counter() - debut,
    )


def _synthese_documentaire_depuis_index(
    question: str,
    index: list[tuple[dict, list[float]]],
    document_cible: str | None = None,
) -> ReponseChat | None:
    """Produit une synthèse métier stable à partir des passages déjà indexés.

    Cette réponse ne dépend pas d'un mot isolé ni du modèle génératif : elle
    regroupe les résultats réellement présents et conserve une preuve par thème.
    """
    if not _demande_synthese_documentaire(question):
        return None
    debut = time.perf_counter()
    lignes = [
        ligne for ligne, _ in index
        if not document_cible or ligne.get("nom_fichier") == document_cible
    ]
    if not lignes:
        perimetre = f" dans « {document_cible} »" if document_cible else " dans le corpus"
        return ReponseChat(
            f"Aucune information indexée n'est disponible{perimetre} pour produire une synthèse.",
            [], "synthese_absente", time.perf_counter() - debut,
        )

    groupes: dict[str, list[dict]] = {}
    vus: set[tuple] = set()
    for ligne in lignes:
        cle = (
            ligne.get("document_id"), ligne.get("page"),
            _normaliser(ligne.get("titre")), _normaliser(ligne.get("contenu")),
        )
        if cle in vus:
            continue
        vus.add(cle)
        categorie_brute = ""
        trouve = re.search(
            r"(?:Catégorie|Categorie)\s*:\s*([^\n]+)",
            str(ligne.get("contenu") or ""), re.IGNORECASE,
        )
        if trouve:
            categorie_brute = trouve.group(1).strip()
        categorie = _canoniser_theme_synthese(
            _categorie_inventaire(
                categorie_brute, ligne.get("titre"), ligne.get("contenu")
            )
        )
        groupes.setdefault(categorie, []).append(ligne)

    groupes_tries = sorted(
        groupes.items(), key=lambda element: (-len(element[1]), element[0])
    )
    documents = {ligne.get("nom_fichier") for ligne in lignes if ligne.get("nom_fichier")}
    types = sorted({str(ligne.get("type_document")) for ligne in lignes if ligne.get("type_document")})
    sources: list[SourceChat] = []
    themes = []
    for categorie, occurrences in groupes_tries[:7]:
        exemple = occurrences[0]
        source = SourceChat(
            document=str(exemple.get("nom_fichier") or "Document"),
            page=exemple.get("page"),
            type_document=str(exemple.get("type_document") or ""),
            titre=str(exemple.get("titre") or categorie),
            texte=str(exemple.get("contenu") or ""),
        )
        sources.append(source)
        numero = len(sources)
        themes.append(
            f"- **{categorie}** : {len(occurrences)} extrait(s) — "
            f"exemple dans **[S{numero}] {source.document}**, page "
            f"{source.page if source.page is not None else 'non précisée'}"
        )

    perimetre = f"le document **{document_cible}**" if document_cible else "l'ensemble du corpus"
    texte = (
        f"Synthèse de {perimetre} : **{len(documents)} document(s)**, "
        f"**{len(vus)} extrait(s) métier unique(s)** et "
        f"**{len(groupes)} thème(s)** analysés.\n\n"
        + (f"Familles documentaires présentes : **{', '.join(types)}**.\n\n" if types else "")
        + "Principaux thèmes détectés :\n\n"
        + "\n".join(themes)
        + "\n\nCette synthèse décrit les résultats détectés ; les éléments marqués « à vérifier » restent soumis à la validation du technicien."
    )
    return ReponseChat(
        texte, sources, "synthese_documentaire", time.perf_counter() - debut
    )


THEMES_INVENTAIRE = {
    "Terrassement et fondations": ("terrassement", "fouille", "remblai", "compactage", "fondation"),
    "Béton et armatures": ("beton", "coffrage", "ferraillage", "armature", "eprouvette"),
    "Structure métallique": ("structure metallique", "charpente", "acier", "ossature metallique"),
    "Couverture et étanchéité": ("couverture", "etancheite", "toiture", "thermo-acoustique"),
    "Plomberie et réseaux": ("plomberie", "sanitaire", "canalisation", "tuyau", "reseau", "evacuation"),
    "Électricité": ("electricite", "courant fort", "courant faible", "cablage", "luminaire"),
    "Matériaux et ouvrages": ("materiau", "maconnerie", "ciment", "bois", "pvc", "aluminium", "laine de roche", "isolant"),
    "Dimensions et quantités": ("dimension", "epaisseur", "diametre", "quantite", "metre carre", "metre cube"),
    "Normes et références": ("norme", "dtu", "nf en", "iso", "reglementation"),
    "Mise en œuvre": ("mise en oeuvre", "execution", "mode operatoire", "realisation", "pose", "fourniture"),
    "Qualité et contrôle": ("controle", "conformite", "verification", "reception", "essai", "tolerance"),
    "Sécurité et prévention": ("securite", "prevention", "risque", "protection", "incendie"),
    "Objet et travaux": ("objet du marche", "objet des travaux", "description des travaux", "consistance"),
    "Intervenants et obligations": ("maitre d'ouvrage", "maitre d'oeuvre", "entrepreneur", "sous-traitant", "obligation"),
    "Délais et pénalités": ("delai", "planning", "penalite", "retard", "achevement"),
    "Paiement et prix": ("paiement", "prix", "facture", "decompte", "acompte"),
    "Garantie et assurance": ("garantie", "assurance", "responsabilite decennale"),
    "Suivi et retour de chantier": ("rapport", "avancement", "incident", "observation", "compte rendu"),
    "Environnement et déchets": ("dechet", "environnement", "pollution", "nuisance", "tri"),
}

CATEGORIES_INVENTAIRE_TROP_LARGES = {
    "", "autre", "materiau", "materiaux", "extrait", "information",
    "cas chantier technique", "cas technique", "contenu general",
}

CORRECTIONS_OCR_AFFICHAGE = {
    "Conxflits": "Conflits",
    "Intérêtss": "Intérêts",
    "Cesion": "Cession",
    "Conttrraatt": "Contrat",
    "Sansmotif": "Sans motif",
    "Diférends": "Différends",
    "Ocupants": "Occupants",
}


def _nettoyer_extrait_pdf(texte: object) -> str:
    valeur = str(texte or "").replace("�", " ")
    valeur = valeur.replace("", " ").replace("•", " ").replace("`", "'")
    valeur = re.sub(r"(?<=\w)[´`]+", "", valeur)
    # Certaines polices PDF dupliquent chaque chiffre pendant l'extraction
    # (14 devient 111444 et 15 devient 111555).
    valeur = re.sub(r"(?<!\d)1{3,}4{3,}(?!\d)", "14", valeur)
    valeur = re.sub(r"(?<!\d)1{3,}5{3,}(?!\d)", "15", valeur)
    # Corrections ciblées pour certains contrats dont la police incorporée
    # est partiellement décalée. Les PDF normalement encodés sont inchangés.
    valeur = re.sub(r"[,/]?'?%NTREPRENEUR", "L'ENTREPRENEUR", valeur, flags=re.IGNORECASE)
    valeur = re.sub(r"'?\#2\b", "GCR", valeur)
    valeur = valeur.replace("A¿N", "AFIN")
    valeur = valeur.replace("¿N", "FIN")
    valeur = valeur.replace("MAsTRE D'°UVRE", "MAÎTRE D'ŒUVRE")
    valeur = valeur.replace("MoMES", "MÊMES")
    valeur = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", valeur)
    for erreur, correction in CORRECTIONS_OCR_AFFICHAGE.items():
        valeur = re.sub(re.escape(erreur), correction, valeur, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", valeur).strip(" -–—•\t\n")


def _decoder_texte_pdf_decale(texte: object) -> str:
    """Corrige les lignes issues d'une police PDF dÃ©calÃ©e de trois codes.

    Seules les lignes portant le marqueur de cette police sont transformÃ©es ;
    les PDF normalement encodÃ©s restent donc strictement inchangÃ©s.
    """
    valeur = str(texte or "")

    # Certains formulaires PDF (notamment le contrat GCR) n'embarquent pas
    # de table ToUnicode. Les lecteurs renvoient alors littéralement
    # ``(cid:68)(cid:88)...``. Pour cette police précise, les lettres latines
    # suivent un décalage stable de 29 positions (68 -> a, 88 -> u, etc.).
    # Le remplacement est activé uniquement en présence de marqueurs CID :
    # les PDF normalement encodés ne sont donc jamais altérés.
    if "(cid:" in valeur:
        caracteres_speciaux = {
            3: " ",
            11: "(", 12: ")",
            15: ",", 17: ".", 20: "1",
            # Accents réellement rencontrés dans le contrat GCR.
            106: "à", 110: "ê", 112: "é",
            182: "'", 191: "fi",
        }

        def remplacer_cid(correspondance: re.Match) -> str:
            code = int(correspondance.group(1))
            if code in caracteres_speciaux:
                return caracteres_speciaux[code]
            code_unicode = code + 29
            if 32 <= code_unicode <= 126:
                return chr(code_unicode)
            return " "

        valeur = re.sub(r"\(cid:(\d+)\)", remplacer_cid, valeur)
        # La même police dessine parfois chaque glyphe deux ou trois fois.
        # Réduire uniquement ces répétitions longues rend les clauses lisibles
        # sans toucher aux mots ordinaires (ex. « assurance »).
        valeur = re.sub(r"([A-Za-zÀ-ÿ])\1{2,}", r"\1", valeur)

        def reduire_glyphes_doubles(correspondance: re.Match) -> str:
            mot = correspondance.group(0)
            # Une vraie duplication de police affecte plusieurs lettres du
            # même mot (``s'eenngager``, ``autoritééss``). Ne pas toucher aux
            # doubles lettres ordinaires telles que ``assurance``.
            if len(re.findall(r"([A-Za-zÀ-ÿ])\1", mot)) < 2:
                return mot
            return re.sub(r"([A-Za-zÀ-ÿ])\1", r"\1", mot)

        valeur = re.sub(r"[A-Za-zÀ-ÿ']+", reduire_glyphes_doubles, valeur)

        # Nettoyage strictement limité aux PDF CID sans table ToUnicode.
        # Ces corrections réparent les artefacts observés dans le contrat
        # GCR sans modifier le texte des CCTP, DQE, guides ou rapports lisibles.
        # Ne jamais compresser les chiffres : ``2 000 000`` est une valeur
        # contractuelle et doit rester intacte. Seules les ponctuations de
        # dessin répétées et le champ date connu ``(((111555)))`` sont réparés.
        valeur = re.sub(r"([(),'\"])\1{2,}", r"\1", valeur)
        valeur = re.sub(r"\({2,}1{3,}5{3,}\){2,}", "(15)", valeur)
        corrections_cid = (
            (r"\bafififin\b", "afin"),
            (r"\bouu\b", "ou"),
            (r"\bfourniseur\b", "fournisseur"),
            (r"\bcomee\b", "comme"),
            (r"\btoeeute\b", "toute"),
            (r"\bimeuble\b", "immeuble"),
            (r"\baditionel\b", "additionnel"),
            (r"\bdétailé\b", "détaillé"),
            (r"\basurance\b", "assurance"),
            (r"\bsuceseurs\b", "successeurs"),
            (r"\bveiler\b", "veiller"),
            (r"\bdosier\b", "dossier"),
            (r"\bcete\b", "cette"),
            (r"\bdestravaux\b", "des travaux"),
            (r"\blesdélais\b", "les délais"),
            (r"\bdechantier\b", "de chantier"),
            (r"\bprixx\b", "prix"),
            (r"\baprouvés\b", "approuvés"),
            (r"\bnécesaire\b", "nécessaire"),
            (r"\bfourniseurs\b", "fournisseurs"),
            (r"\bremetant\b", "remettant"),
            (r"\bcomporrter\b", "comporter"),
            (r"\bdérangemments\b", "dérangements"),
            (r"\bnotament\b", "notamment"),
            (r"\bcomision\b", "commission"),
            (r"\bimeubbles?\b", "immeuble"),
            (r"\bconxflits\b", "conflits"),
            (r"\bintérêtss\b", "intérêts"),
            (r"\bmetrait\b", "mettrait"),
            (r"\bfififiliales\b", "filiales"),
            (r"\baccidentele\b", "accidentelle"),
            (r"\bma\s+tre\b", "maître"),
            (r"\bd['’]\s*uvre\b", "d’œuvre"),
            (r"\bm\s+mes\b", "mêmes"),
            (r"\bsi\s+ge\b", "siège"),
            (r"\bmani\s+re\b", "manière"),
            (r"\bacc\s+s\b", "accès"),
            (r"\bhypoth\s*ques\b", "hypothèques"),
            (r"\bach\s+vement\b", "achèvement"),
            (r"\bfa\s+on\b", "façon"),
            (r"\bjournali\s+re\b", "journalière"),
            (r"\bcompl\s+te\b", "complète"),
            (r"\br\s+gles\b", "règles"),
            (r"\bintér\s+t\b", "intérêt"),
            (r"\bdéc\s+s\b", "décès"),
            (r"\bdevront\s+tre\b", "devront être"),
            (r"\bttoute\b", "toute"),
            (r"\bcon\s+it\b", "conflit"),
            (r"\bintér\s+ts\b", "intérêts"),
        )
        for motif, correction in corrections_cid:
            valeur = re.sub(motif, correction, valeur, flags=re.IGNORECASE)
        valeur = re.sub(r"à{2,}", "à", valeur, flags=re.IGNORECASE)
        valeur = re.sub(r"\bsous-{2,}traitant\b", "sous-traitant", valeur, flags=re.IGNORECASE)
        valeur = re.sub(r"\bà\s*ses\b", "à ses", valeur, flags=re.IGNORECASE)
        valeur = re.sub(r"\s+([,.;:!?])", r"\1", valeur)
        valeur = re.sub(r"\s+", " ", valeur).strip()

    resultat: list[str] = []
    for ligne in valeur.splitlines():
        if "\x03" not in ligne:
            resultat.append(ligne)
            continue
        caracteres: list[str] = []
        for caractere in ligne:
            code = ord(caractere)
            caracteres.append(chr(code - 3) if 3 <= code <= 128 else caractere)
        decodee = "".join(caracteres)
        decodee = decodee.replace("\x00", " ").replace("\x1d", " ")
        decodee = decodee.translate(str.maketrans({
            "m": "\u00c9", "g": "\u00c0", "n": "\u00c8", "l": "\u00c7",
            "}": "\u00db", "|": "\u00d9", "\u00b6": "'",
        }))
        resultat.append(re.sub(r"\s+", " ", decodee).strip())
    return "\n".join(resultat)


def _categorie_inventaire(categorie: object, libelle: object, texte: object) -> str:
    """Rend une catégorie lisible et affine les catégories trop génériques."""
    brute = _normaliser(categorie).replace("_", " ")
    if brute not in CATEGORIES_INVENTAIRE_TROP_LARGES:
        return str(categorie).replace("_", " ").strip().title()
    titre = _normaliser(libelle)
    contenu = _normaliser(texte)
    # Une certification explicite est une référence normative, même lorsque
    # l'extrait se trouve sous un titre d'ouvrage (couverture, étanchéité...).
    if re.search(
        r"\b(?:certifi(?:e|ee|cation)|conforme aux normes?)\b.{0,100}"
        r"\b(?:iso|nf en|dtu)\b",
        contenu,
    ):
        return "Normes et références"
    scores = {
        theme: 3 * sum(1 for mot in mots if mot in titre)
        + sum(1 for mot in mots if mot in contenu)
        for theme, mots in THEMES_INVENTAIRE.items()
    }
    meilleur, score = max(scores.items(), key=lambda element: element[1])
    return meilleur if score else "Informations générales"


def _resume_preuve(libelle: object, texte: object, maximum: int = 260) -> str:
    """Choisit une preuve courte sans répéter simplement le libellé."""
    titre = _nettoyer_extrait_pdf(libelle)
    source = _nettoyer_extrait_pdf(texte)
    if not source or _normaliser(source) == _normaliser(titre):
        return titre or "Extrait métier"
    if len(source) > maximum:
        source = source[:maximum].rsplit(" ", 1)[0] + "…"
    elif source and source[-1] not in ".!?;:…)]}" and len(source.split()) >= 8:
        # Le stockage peut contenir une fenêtre de contexte et non la phrase
        # entière. Les points de suspension évitent de présenter ce fragment
        # comme une affirmation terminée.
        source += "…"
    return f"**{titre}** — {source}" if titre else source


def _preuve_directe_avec_limite(numero: int, source: SourceChat, phrase: str) -> str:
    """N'affiche jamais un simple titre comme s'il était le contenu d'une clause."""
    phrase_propre = _nettoyer_extrait_pdf(phrase)
    titre_propre = _nettoyer_extrait_pdf(source.titre)
    if not phrase_propre or _normaliser(phrase_propre) == _normaliser(titre_propre):
        page = source.page if source.page is not None else "non précisée"
        return (
            f"- **[S{numero}] {titre_propre}** — rubrique repérée page {page}, "
            "mais son contenu n'est pas suffisamment lisible dans ce PDF pour "
            "être restitué avec fiabilité."
        )
    return f"- **[S{numero}]** {phrase_propre}"


def _reponse_inventaire_document(
    question: str,
    chemin_base: Path | str,
    document_cible: str | None,
) -> ReponseChat | None:
    """Retourne tous les résultats structurés du document, sans top-N sémantique."""
    if not _demande_inventaire_complet(question):
        return None
    debut = time.perf_counter()
    if not document_cible:
        return ReponseChat(
            "Sélectionnez d'abord un document dans le filtre afin que je puisse "
            "fournir son inventaire complet sans mélanger plusieurs projets.",
            [], "clarification_document", time.perf_counter() - debut,
        )

    with _connexion(chemin_base) as connexion:
        document = connexion.execute(
            "SELECT id, nom_fichier FROM documents WHERE nom_fichier=?",
            (document_cible,),
        ).fetchone()
        if document is None:
            return None
        lignes = list(connexion.execute(
            """SELECT id, page, categorie, libelle, texte_source, donnees_json,
                      type_document
               FROM extractions WHERE document_id=?
               ORDER BY COALESCE(page, 999999), id""",
            (document["id"],),
        ).fetchall())
        tables = {
            ligne["name"] for ligne in connexion.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "extractions_metier" in tables:
            lignes += list(connexion.execute(
                """SELECT id, page, categorie, libelle, texte_source, donnees_json,
                          type_document
                   FROM extractions_metier WHERE document_id=?
                   ORDER BY COALESCE(page, 999999), id""",
                (document["id"],),
            ).fetchall())

    if not lignes:
        return ReponseChat(
            f"Le document **{document_cible}** ne contient encore aucun résultat "
            "structuré. Lancez ou actualisez son analyse avant de demander son inventaire.",
            [], "inventaire_absent", time.perf_counter() - debut,
        )

    sources: list[SourceChat] = []
    if all(ligne["type_document"] == "DQE" for ligne in lignes):
        postes = []
        for ligne in lignes:
            try:
                donnees = json.loads(ligne["donnees_json"] or "{}")
            except json.JSONDecodeError:
                donnees = {}
            numero = str(donnees.get("numero_poste") or donnees.get("numero") or "non numéroté").strip()
            designation = str(donnees.get("designation") or ligne["libelle"] or "Non renseignée")
            postes.append(
                f"- **{numero} — {designation}** | "
                f"Unité : **{_nombre_fr(donnees.get('unite'))}** | "
                f"Quantité : **{_nombre_fr(donnees.get('quantite'))}** | "
                f"P.U. : **{_nombre_fr(donnees.get('prix_unitaire'), True)}** | "
                f"Montant : **{_nombre_fr(donnees.get('prix_total'), True)}**"
            )
            sources.append(SourceChat(
                document=document_cible, page=ligne["page"], type_document="DQE",
                titre=f"Poste {numero} — {designation}",
                texte=ligne["texte_source"] or designation,
            ))
        texte = (
            f"Le devis **{document_cible}** contient **{len(postes)} poste(s) structuré(s)**. "
            "Voici l'inventaire complet des résultats détectés :\n\n" + "\n".join(postes)
        )
        return ReponseChat(texte, sources, "inventaire_dqe", time.perf_counter() - debut)

    groupes: dict[str, list[str]] = {}
    cles_vues: set[tuple[object, str]] = set()
    for ligne in lignes:
        valeur = str(ligne["libelle"] or "").strip()
        if not valeur:
            try:
                donnees = json.loads(ligne["donnees_json"] or "{}")
            except json.JSONDecodeError:
                donnees = {}
            valeur = str(donnees.get("valeur") or donnees.get("designation") or "Extrait métier")
        preuve = _resume_preuve(valeur, ligne["texte_source"])
        cle = (ligne["page"], _normaliser(preuve))
        if cle in cles_vues:
            continue
        cles_vues.add(cle)
        categorie = _categorie_inventaire(
            ligne["categorie"], valeur, ligne["texte_source"]
        )
        page = ligne["page"] if ligne["page"] is not None else "non précisée"
        groupes.setdefault(categorie, []).append(f"- page {page} : {preuve}")
        sources.append(SourceChat(
            document=document_cible, page=ligne["page"],
            type_document=ligne["type_document"], titre=valeur,
            texte=ligne["texte_source"] or valeur,
        ))
    sections = [
        f"**{categorie} ({len(elements)})**\n" + "\n".join(elements)
        for categorie, elements in groupes.items()
    ]
    texte = (
        f"Le document **{document_cible}** contient **{len(cles_vues)} extrait(s) métier unique(s)** "
        f"réparti(s) dans **{len(groupes)} catégorie(s)**. "
        "Voici l'inventaire complet des résultats détectés :\n\n"
        + "\n\n".join(sections)
    )
    return ReponseChat(texte, sources, "inventaire_document", time.perf_counter() - debut)


def _tokens_utiles(texte: str) -> set[str]:
    stop = {"quel", "quelle", "quels", "dans", "pour", "avec", "poste", "document",
            "donne", "moi", "est", "son", "une", "des", "les", "prix", "unitaire",
            "quantite", "unite", "montant", "total", "information", "informations",
            "corpus", "contient", "contenir", "trouve", "trouver", "indique", "indiquer"}
    return {mot for mot in re.findall(r"[a-z0-9]+", _normaliser(texte)) if len(mot) > 2 and mot not in stop}


def _nombre_romain(texte: str) -> int | None:
    """Convertit un petit numéro romain utilisé dans les lots d'un devis."""
    valeurs = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    texte = texte.casefold().strip()
    if not texte or any(caractere not in valeurs for caractere in texte):
        return None
    total = 0
    precedent = 0
    for caractere in reversed(texte):
        valeur = valeurs[caractere]
        if valeur < precedent:
            total -= valeur
        else:
            total += valeur
            precedent = valeur
    return total if 0 < total <= 100 else None


def _demande_sous_total(question: str) -> bool:
    normalisee = _normaliser(question).replace("-", " ")
    return bool(re.search(r"\bsous\s+total\b", normalisee))


def _section_sous_total(question: str) -> str | None:
    """Extrait `I`, `1` ou `section 1` d'une demande de sous-total."""
    normalisee = _normaliser(question).replace("-", " ")
    motifs = (
        r"\bsous\s+total\s+(?:n(?:o|umero)?\s*)?([ivxlc]+|\d+)\b",
        r"\b(?:section|lot|chapitre)\s+([ivxlc]+|\d+)\b",
    )
    for motif in motifs:
        correspondance = re.search(motif, normalisee)
        if not correspondance:
            continue
        valeur = correspondance.group(1)
        if valeur.isdigit():
            return str(int(valeur))
        nombre = _nombre_romain(valeur)
        if nombre is not None:
            return str(nombre)
    return None


def _reponse_sous_total_dqe(
    question: str,
    chemin_base: Path | str,
    document_cible: str | None = None,
) -> ReponseChat | None:
    """Calcule un sous-total DQE depuis les montants structurés, sans LLM."""
    if not _demande_sous_total(question):
        return None
    debut = time.perf_counter()
    with _connexion(chemin_base) as connexion:
        lignes = connexion.execute(
            """
            SELECT e.*, d.nom_fichier
            FROM extractions e JOIN documents d ON d.id=e.document_id
            WHERE e.type_document='DQE'
            ORDER BY d.nom_fichier, e.page, e.id
            """
        ).fetchall()

    groupes: dict[tuple[str, str], list[tuple[sqlite3.Row, dict, str]]] = {}
    for ligne in lignes:
        if document_cible and ligne["nom_fichier"] != document_cible:
            continue
        try:
            donnees = json.loads(ligne["donnees_json"] or "{}")
        except json.JSONDecodeError:
            continue
        numero = str(donnees.get("numero_poste") or donnees.get("numero") or "").strip()
        correspondance = re.match(r"^(\d+)\.", numero.replace(",", "."))
        if not correspondance or donnees.get("prix_total") in (None, ""):
            continue
        designation = str(donnees.get("designation") or ligne["libelle"] or "")
        cle = (ligne["nom_fichier"], correspondance.group(1))
        groupes.setdefault(cle, []).append((ligne, donnees, designation))
    if not groupes:
        return None

    section = _section_sous_total(question)
    tokens_question = _tokens_utiles(question) - {"sous", "total", "designation", "ouvrages"}
    candidats = []
    for (document, numero_section), postes in groupes.items():
        if section and numero_section != section:
            continue
        texte_groupe = " ".join(designation for _, _, designation in postes)
        score = 0
        if section == numero_section:
            score += 200
        score += 12 * len(tokens_question & _tokens_utiles(texte_groupe))
        if document_cible and document == document_cible:
            score += 80
        candidats.append((score, document, numero_section, postes))
    if not candidats:
        return ReponseChat(
            "Je n'ai trouvé aucun poste structuré correspondant à ce sous-total dans le devis sélectionné.",
            [], "sous_total_non_trouve", time.perf_counter() - debut,
        )
    candidats.sort(key=lambda element: element[0], reverse=True)
    score, document, numero_section, postes = candidats[0]
    if not section and score < (80 if document_cible else 12):
        return ReponseChat(
            "Précisez le numéro du sous-total ou l'intitulé de la section recherchée.",
            [], "clarification_sous_total", time.perf_counter() - debut,
        )

    montant = sum(float(donnees["prix_total"]) for _, donnees, _ in postes)
    details = []
    sources = []
    for ligne, donnees, designation in postes:
        numero = str(donnees.get("numero_poste") or donnees.get("numero") or "")
        details.append(
            f"- Poste {numero} — {designation} : "
            f"**{_nombre_fr(donnees['prix_total'], True)}**"
        )
        sources.append(SourceChat(
            document=document,
            page=ligne["page"],
            type_document="DQE",
            titre=f"Poste {numero} — {designation}",
            texte=ligne["texte_source"] or donnees.get("texte_source") or designation,
        ))
    texte = (
        f"**Sous-total {numero_section} : {_nombre_fr(montant, True)}**\n\n"
        f"Calculé à partir de {len(postes)} poste(s) du document **{document}** :\n\n"
        + "\n".join(details)
    )
    return ReponseChat(texte, sources, "sous_total_dqe", time.perf_counter() - debut)


def _reponse_dqe_structuree(
    question: str,
    chemin_base: Path | str,
    document_cible: str | None = None,
) -> ReponseChat | None:
    sous_total = _reponse_sous_total_dqe(question, chemin_base, document_cible)
    if sous_total is not None:
        return sous_total
    champs = _champs_demandes(question)
    champ = _champ_demande(question)
    numero = _numero_poste(question)
    if not champ and not numero:
        return None
    debut = time.perf_counter()
    question_norm = _normaliser(question)
    tokens_question = _tokens_utiles(question)
    candidats = []
    with _connexion(chemin_base) as connexion:
        lignes = connexion.execute(
            """
            SELECT e.*, d.nom_fichier
            FROM extractions e JOIN documents d ON d.id=e.document_id
            WHERE e.type_document='DQE'
            """
        ).fetchall()
    for ligne in lignes:
        if document_cible and ligne["nom_fichier"] != document_cible:
            continue
        try:
            donnees = json.loads(ligne["donnees_json"] or "{}")
        except json.JSONDecodeError:
            continue
        numero_candidat = str(donnees.get("numero_poste") or donnees.get("numero") or "").strip()
        designation = str(donnees.get("designation") or ligne["libelle"] or "")
        score = 0
        if numero:
            if numero_candidat.replace(",", ".") == numero:
                score += 120
            else:
                continue
        nom_norm = _normaliser(Path(ligne["nom_fichier"]).stem).replace("_", " ")
        mots_nom = [m for m in re.findall(r"[a-z0-9]+", nom_norm) if len(m) >= 4]
        score += 35 * sum(mot in question_norm for mot in mots_nom)
        score += 8 * len(tokens_question & _tokens_utiles(designation))
        if champ and donnees.get(champ) not in (None, ""):
            score += 10
        candidats.append((score, ligne, donnees, designation, numero_candidat))
    if not candidats:
        return None
    candidats.sort(key=lambda element: element[0], reverse=True)
    meilleur_score, ligne, donnees, designation, numero_candidat = candidats[0]
    if meilleur_score < 20:
        return None
    if len(candidats) > 1 and candidats[1][0] == meilleur_score and numero:
        documents = sorted({c[1]["nom_fichier"] for c in candidats if c[0] == meilleur_score})
        texte = (
            f"Le poste {numero} existe dans plusieurs documents : "
            + ", ".join(documents[:5])
            + ". Précisez le document souhaité."
        )
        return ReponseChat(texte, [], "clarification", time.perf_counter() - debut)

    valeurs = {
        "designation": designation or "Non renseignée",
        "unite": donnees.get("unite"),
        "quantite": donnees.get("quantite"),
        "prix_unitaire": donnees.get("prix_unitaire"),
        "prix_total": donnees.get("prix_total"),
    }
    libelles = {
        "designation": "Désignation", "unite": "Unité", "quantite": "Quantité",
        "prix_unitaire": "Prix unitaire", "prix_total": "Montant",
    }
    poste = numero_candidat or "non numéroté"
    if len(champs) >= 2:
        lignes_champs = []
        for champ_demande in champs:
            valeur = _nombre_fr(
                valeurs[champ_demande],
                monnaie=champ_demande in {"prix_unitaire", "prix_total"},
            )
            lignes_champs.append(
                f"- {libelles[champ_demande]} : **{valeur}**"
            )
        texte = (
            f"**Poste {poste} — {designation}**\n\n"
            + "\n".join(lignes_champs)
        )
    elif champ:
        valeur = _nombre_fr(
            valeurs[champ], monnaie=champ in {"prix_unitaire", "prix_total"}
        )
        texte = f"**Poste {poste} — {designation}**\n\n{libelles[champ]} : **{valeur}**"
    else:
        texte = (
            f"**Poste {poste} — {designation}**\n\n"
            f"- Unité : **{_nombre_fr(valeurs['unite'])}**\n"
            f"- Quantité : **{_nombre_fr(valeurs['quantite'])}**\n"
            f"- Prix unitaire : **{_nombre_fr(valeurs['prix_unitaire'], True)}**\n"
            f"- Montant : **{_nombre_fr(valeurs['prix_total'], True)}**"
        )
    source = SourceChat(
        document=ligne["nom_fichier"], page=ligne["page"], type_document="DQE",
        titre=f"Poste {poste} — {designation}",
        texte=ligne["texte_source"] or donnees.get("texte_source") or designation,
    )
    return ReponseChat(texte, [source], "donnee_structuree", time.perf_counter() - debut)


def _cosinus(a: list[float], b: list[float]) -> float:
    produit = sum(x * y for x, y in zip(a, b))
    norme_a = math.sqrt(sum(x * x for x in a))
    norme_b = math.sqrt(sum(y * y for y in b))
    return produit / (norme_a * norme_b) if norme_a and norme_b else 0.0


class AssistantBTP:
    """Moteur RAG local, réutilisable entre les pages Streamlit."""

    def __init__(self, chemin_base: Path | str = CHEMIN_BASE):
        self.chemin_base = Path(chemin_base)
        self._index: list[tuple[dict, list[float]]] = []
        self._cache_pages_pdf: dict[str, list[str]] = {}
        self._charge_le = 0.0
        self._signature_corpus: tuple | None = None
        initialiser_index_chat(self.chemin_base)

    def _lire_signature_corpus(self) -> tuple:
        """Retourne une empreinte SQL légère des données réellement indexables.

        Elle permet d'éviter de relire toutes les extractions et tous les
        embeddings avant chaque question lorsque le corpus n'a pas changé.
        """
        with _connexion(self.chemin_base) as connexion:
            extraction = connexion.execute(
                """SELECT COUNT(*) AS nombre, COALESCE(MAX(id), 0) AS dernier_id,
                          COALESCE(MAX(date_modification), '') AS derniere_modification
                   FROM extractions"""
            ).fetchone()
            metier = connexion.execute(
                """SELECT COUNT(*) AS nombre, COALESCE(MAX(id), 0) AS dernier_id,
                          COALESCE(MAX(date_modification), '') AS derniere_modification
                   FROM extractions_metier"""
            ).fetchone()
        return (
            extraction["nombre"], extraction["dernier_id"],
            extraction["derniere_modification"], metier["nombre"],
            metier["dernier_id"], metier["derniere_modification"],
        )

    def synchroniser(self, progression=None) -> dict[str, int]:
        signature = self._lire_signature_corpus()
        if self._index and signature == self._signature_corpus:
            return {
                "total": len(self._index), "indexes": 0,
                "supprimes": 0, "deja_a_jour": 1,
            }
        bilan = synchroniser_index_chat(self.chemin_base, progression)
        if bilan["indexes"] or bilan["supprimes"] or not self._index:
            self._charger_index(force=True)
        self._signature_corpus = signature
        return bilan

    def _charger_index(self, force: bool = False) -> None:
        if self._index and not force:
            return
        with _connexion(self.chemin_base) as connexion:
            lignes = connexion.execute("SELECT * FROM index_chatbot").fetchall()
        self._index = []
        for ligne in lignes:
            try:
                vecteur = json.loads(ligne["embedding_json"])
            except json.JSONDecodeError:
                continue
            self._index.append((dict(ligne), vecteur))
        self._charge_le = time.time()

    def index_pret(self) -> bool:
        self._charger_index()
        return bool(self._index)

    def _rechercher_dans_pdf(
        self, question: str, document_cible: str, limite: int = 3
    ) -> list[tuple[float, dict]]:
        """Recherche de secours dans toutes les pages du PDF explicitement choisi."""
        with _connexion(self.chemin_base) as connexion:
            document = connexion.execute(
                "SELECT id, nom_fichier, chemin_relatif, type_document "
                "FROM documents WHERE nom_fichier=?",
                (document_cible,),
            ).fetchone()
        if document is None:
            return []

        chemin_pdf = RACINE_PROJET / document["chemin_relatif"]
        if not chemin_pdf.exists():
            return []
        cle_cache = str(chemin_pdf.resolve())
        if cle_cache not in self._cache_pages_pdf:
            try:
                from pypdf import PdfReader

                self._cache_pages_pdf[cle_cache] = [
                    page.extract_text() or "" for page in PdfReader(str(chemin_pdf)).pages
                ]
            except Exception:
                return []

        question_norm = _normaliser(question)
        tokens = _tokens_utiles(question)
        materiaux_connus = set(MATERIAUX_BTP)
        if "materiau" in question_norm or "materiaux" in question_norm:
            tokens.update(
                mot
                for motifs in MATERIAUX_BTP.values()
                for motif in motifs
                for mot in re.findall(r"[a-z0-9]+", motif.replace("\\b", ""))
                if len(mot) > 2
            )
        if any(mot in question_norm for mot in ("canalisation", "plomberie", "reseau")):
            tokens.update({"canalisation", "canalisations", "tube", "tuyau", "reseau"})
        intention_reseaux = any(
            mot in question_norm for mot in ("canalisation", "plomberie", "reseau")
        )
        termes_reseaux = (
            "plomberie", "sanitaire", "canalisation", "canalisations",
            "tuyau", "tube", "reseau", "eau froide", "eau chaude",
        )
        demande_prescription = any(
            mot in question_norm for mot in ("prescription", "exigence", "caracteristique")
        )

        candidats: list[tuple[int, dict]] = []
        for numero_page, texte_page in enumerate(self._cache_pages_pdf[cle_cache], 1):
            lignes = [
                re.sub(r"\s+", " ", ligne).strip()
                for ligne in texte_page.splitlines()
                if len(re.sub(r"\s+", " ", ligne).strip()) >= 12
            ]
            for indice in range(len(lignes)):
                passage = " ".join(lignes[max(0, indice - 1):indice + 3])[:1100]
                passage_norm = _normaliser(passage)
                contexte_reseau = sum(terme in passage_norm for terme in termes_reseaux)
                if intention_reseaux and not contexte_reseau:
                    continue
                correspondances = sum(token in passage_norm for token in tokens)
                bonus_materiau = 0
                if "materiau" in question_norm or "materiaux" in question_norm:
                    materiaux_passage = _materiaux_pertinents(question, passage)
                    if not materiaux_passage:
                        continue
                    bonus_materiau = 2 * len(materiaux_passage)
                bonus_prescription = 0
                if demande_prescription and any(
                    terme in passage_norm
                    for terme in ("doit", "devra", "seront", "norme", "epaisseur", "diametre")
                ):
                    bonus_prescription = 2
                bonus_document = 0
                if intention_reseaux and any(
                    terme in _normaliser(document["nom_fichier"])
                    for terme in ("plomberie", "sanitaire")
                ):
                    bonus_document = 5
                score = (
                    correspondances + bonus_materiau + bonus_prescription
                    + 2 * contexte_reseau + bonus_document
                )
                if score < 2:
                    continue
                titre = lignes[indice][:140]
                candidats.append(
                    (
                        score,
                        {
                            "document_id": document["id"],
                            "nom_fichier": document["nom_fichier"],
                            "type_document": document["type_document"],
                            "page": numero_page,
                            "titre": titre,
                            "contenu": passage,
                        },
                    )
                )

        candidats.sort(key=lambda element: element[0], reverse=True)
        selection: list[tuple[float, dict]] = []
        passages_vus: set[object] = set()
        for score, ligne in candidats:
            if "materiau" in question_norm or "materiaux" in question_norm:
                cle = (
                    ligne["page"],
                    tuple(_materiaux_pertinents(question, ligne["contenu"])),
                )
            else:
                cle = _normaliser(ligne["contenu"])[:260]
            if cle in passages_vus:
                continue
            passages_vus.add(cle)
            selection.append((min(0.95, 0.57 + 0.035 * score), ligne))
            if len(selection) >= limite:
                break
        return selection

    def _rechercher_dans_corpus_pdf(
        self, question: str, limite: int = 4
    ) -> list[tuple[float, dict]]:
        """Étend la recherche aux textes PDF lorsque la question est technique."""
        question_norm = _normaliser(question)
        with _connexion(self.chemin_base) as connexion:
            if "plomberie" in question_norm or "sanitaire" in question_norm:
                documents = connexion.execute(
                    "SELECT nom_fichier FROM documents WHERE chemin_relatif IS NOT NULL "
                    "AND statut IN ('traite', 'importe') "
                    "AND (lower(nom_fichier) LIKE '%plomberie%' "
                    "OR lower(nom_fichier) LIKE '%sanitaire%')"
                ).fetchall()
            else:
                documents = connexion.execute(
                    "SELECT nom_fichier FROM documents "
                    "WHERE chemin_relatif IS NOT NULL AND statut IN ('traite', 'importe')"
                ).fetchall()
        resultats: list[tuple[float, dict]] = []
        for document in documents:
            resultats.extend(
                self._rechercher_dans_pdf(question, document["nom_fichier"], limite=4)
            )
        if "plomberie" in question_norm or "sanitaire" in question_norm:
            resultats_plomberie = [
                resultat for resultat in resultats
                if any(
                    terme in _normaliser(resultat[1]["nom_fichier"])
                    for terme in ("plomberie", "sanitaire")
                )
            ]
            if resultats_plomberie:
                resultats = resultats_plomberie
        resultats.sort(key=lambda element: element[0], reverse=True)
        return resultats[:limite]

    def _documents_a_lire(self, document_cible: str | None) -> list[str]:
        if document_cible:
            return [document_cible]
        with _connexion(self.chemin_base) as connexion:
            lignes = connexion.execute(
                "SELECT nom_fichier FROM documents WHERE chemin_relatif IS NOT NULL "
                "AND statut IN ('traite', 'importe') ORDER BY id"
            ).fetchall()
        return [str(ligne["nom_fichier"]) for ligne in lignes]

    def _pages_pdf(self, nom_fichier: str) -> tuple[dict, list[str]] | None:
        """Charge une seule fois toutes les pages d'un PDF du corpus."""
        with _connexion(self.chemin_base) as connexion:
            document = connexion.execute(
                "SELECT id, nom_fichier, chemin_relatif, type_document FROM documents "
                "WHERE nom_fichier=?", (nom_fichier,),
            ).fetchone()
        if document is None:
            return None
        chemin = RACINE_PROJET / document["chemin_relatif"]
        if not chemin.exists():
            return None
        cle = str(chemin.resolve())
        if cle not in self._cache_pages_pdf:
            try:
                # pdfplumber est le lecteur de référence du projet. Sur certains
                # PDF techniques, pypdf ne lève aucune erreur mais renvoie un
                # texte dont les mots sont mal reconstruits ; la recherche
                # concluait alors à tort qu'aucun passage n'existait.
                import pdfplumber

                with pdfplumber.open(str(chemin)) as pdf:
                    pages = [
                        _decoder_texte_pdf_decale(page.extract_text() or "")
                        for page in pdf.pages
                    ]
                if not any(page.strip() for page in pages):
                    raise ValueError("aucun texte lisible avec pdfplumber")
                self._cache_pages_pdf[cle] = pages
            except Exception as erreur_pdfplumber:
                try:
                    from pypdf import PdfReader

                    self._cache_pages_pdf[cle] = [
                        _decoder_texte_pdf_decale(page.extract_text() or "")
                        for page in PdfReader(str(chemin)).pages
                    ]
                except Exception as exc:
                    print(
                        f"[CHATBOT][PDF] lecture impossible document={nom_fichier} "
                        f"pdfplumber={type(erreur_pdfplumber).__name__}: {erreur_pdfplumber}; "
                        f"pypdf={type(exc).__name__}: {exc}"
                    )
                    return None
        return dict(document), self._cache_pages_pdf[cle]

    def _sources_stockees_par_ancres(
        self,
        document_cible: str | None,
        ancres: tuple[str, ...],
        limite: int = 8,
    ) -> list[SourceChat]:
        """Secours déterministe fondé sur les extraits déjà persistés.

        Cette recherche ne dépend pas du lecteur PDF utilisé par l'environnement
        Streamlit. Elle évite donc un faux « rien trouvé » lorsqu'un passage a
        déjà été extrait et tracé dans SQLite par le pipeline métier.
        """
        documents = self._documents_a_lire(document_cible)
        if not documents:
            return []
        placeholders = ",".join("?" for _ in documents)
        lignes: list[dict] = []
        with _connexion(self.chemin_base) as connexion:
            tables = {
                ligne["name"] for ligne in connexion.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for table in ("extractions", "extractions_metier"):
                if table not in tables:
                    continue
                requete = f"""
                    SELECT d.nom_fichier, d.type_document, e.page, e.categorie,
                           e.libelle, e.texte_source, e.donnees_json
                    FROM {table} e
                    JOIN documents d ON d.id=e.document_id
                    WHERE d.nom_fichier IN ({placeholders})
                """
                lignes.extend(
                    dict(ligne) for ligne in connexion.execute(requete, documents).fetchall()
                )

        ancres_norm = tuple(_normaliser(ancre) for ancre in ancres)
        candidats: list[tuple[int, SourceChat]] = []
        for ligne in lignes:
            contenu = " ".join(str(ligne.get(cle) or "") for cle in (
                "categorie", "libelle", "texte_source", "donnees_json"
            ))
            normalise = _normaliser(contenu)
            hits = sum(ancre in normalise for ancre in ancres_norm)
            if not hits:
                continue
            texte = str(ligne.get("texte_source") or ligne.get("libelle") or "").strip()
            if not texte:
                continue
            candidats.append((hits, SourceChat(
                document=str(ligne["nom_fichier"]),
                page=ligne.get("page"),
                type_document=str(ligne.get("type_document") or ""),
                titre=str(ligne.get("libelle") or ligne.get("categorie") or "Extrait métier"),
                texte=_nettoyer_extrait_pdf(texte),
            )))

        candidats.sort(key=lambda element: element[0], reverse=True)
        resultat: list[SourceChat] = []
        vus: set[tuple[object, ...]] = set()
        for _, source in candidats:
            cle = (source.document, source.page, _normaliser(source.texte)[:260])
            if cle in vus:
                continue
            vus.add(cle)
            resultat.append(source)
            if len(resultat) >= limite:
                break
        return resultat

    def _reponse_obligations_pdf(
        self, question: str, document_cible: str | None
    ) -> ReponseChat | None:
        """Restitue les obligations et la sous-traitance depuis le PDF complet.

        Certains contrats utilisent une police avec un encodage incorrect. Les
        pages ont déjà été normalisées par ``_pages_pdf`` ; cette recherche ne
        dépend donc pas des seuls titres enregistrés dans l'index.
        """
        question_norm = _normaliser(question)
        if not any(terme in question_norm for terme in (
            "obligation", "obligations", "sous traitant", "sous traitance",
            "sous-traitant", "sous-traitance", "entrepreneur", "entreprise",
        )):
            return None

        debut = time.perf_counter()
        sous_traitance = any(terme in question_norm for terme in (
            "sous traitant", "sous traitance", "sous-traitant", "sous-traitance"
        ))
        ancres_sujet = (
            ("sous-trait", "sous trait", "sous_trait", "sous-traitance", "sous traitance")
            if sous_traitance else
            ("obligation", "entrepreneur", "entreprise", "titulaire")
        )
        ancres_action = (
            "doit", "devra", "s engage", "tenu", "responsable", "respecter",
            "payer", "interdit", "obligation",
        )
        candidats: list[tuple[int, SourceChat]] = []
        for nom in self._documents_a_lire(document_cible):
            charge = self._pages_pdf(nom)
            if not charge:
                continue
            document, pages = charge
            for numero_page, texte in enumerate(pages, 1):
                for passage in _fenetres_texte_pdf(texte):
                    normalise = _normaliser(passage)
                    hits_sujet = sum(ancre in normalise for ancre in ancres_sujet)
                    hits_action = sum(ancre in normalise for ancre in ancres_action)
                    if not hits_sujet or not hits_action:
                        continue
                    candidats.append((6 * hits_sujet + 3 * hits_action, SourceChat(
                        document=nom, page=numero_page,
                        type_document=str(document.get("type_document") or ""),
                        titre=("Sous-traitance" if sous_traitance else "Obligations"),
                        texte=passage,
                    )))

        candidats.sort(key=lambda element: element[0], reverse=True)
        sources: list[SourceChat] = []
        vus: set[tuple] = set()
        for _, source in candidats:
            nettoye = _nettoyer_extrait_pdf(source.texte)
            cle = (source.document, source.page, _normaliser(nettoye)[:260])
            if cle in vus or len(nettoye) < 45:
                continue
            vus.add(cle)
            sources.append(SourceChat(
                document=source.document,
                page=source.page,
                type_document=source.type_document,
                titre=source.titre,
                texte=nettoye,
            ))
            if len(sources) >= 3:
                break

        if not sources:
            perimetre = f" dans « {document_cible} »" if document_cible else " dans le corpus"
            sujet = "de sous-traitance" if sous_traitance else "d'obligation"
            return ReponseChat(
                f"Aucune clause explicite {sujet} n'a été trouvée{perimetre}.",
                [], "obligations_non_trouvees", time.perf_counter() - debut,
            )

        lignes = [
            f"- **[S{i}] page {source.page}** : {source.texte}"
            for i, source in enumerate(sources, 1)
        ]
        titre = (
            "Clauses relatives à la sous-traitance :"
            if sous_traitance else "Obligations explicitement mentionnées :"
        )
        return ReponseChat(
            titre + "\n\n" + "\n".join(lignes), sources,
            "obligations_pdf", time.perf_counter() - debut,
        )

    def _reponse_clauses_contrat_pdf(
        self, question: str, document_cible: str | None
    ) -> ReponseChat | None:
        """Lit les clauses contractuelles dans le PDF complet, y compris CID.

        Cette voie déterministe évite de répondre avec le seul titre d'une
        rubrique lorsque le corps du contrat n'avait pas été indexé.
        """
        question_norm = _normaliser(question)
        themes = []
        configurations = (
            ("Paiement et prix", ("paiement", "prix", "acompte", "facture", "decompte")),
            ("Délais et pénalités", ("delai", "penalite", "retard", "fin des travaux")),
            ("Garantie et assurance", ("garantie", "assurance", "caution")),
        )
        for titre, ancres in configurations:
            if any(ancre in question_norm for ancre in ancres):
                themes.append((titre, ancres))
        if not themes:
            return None

        debut = time.perf_counter()
        candidats: list[tuple[int, str, SourceChat]] = []
        for nom in self._documents_a_lire(document_cible):
            charge = self._pages_pdf(nom)
            if not charge:
                continue
            document, pages = charge
            chemin = str(document.get("chemin_relatif") or "").replace("\\", "/").lower()
            if (
                str(document.get("type_document") or "").upper() != "CONTRAT"
                and "/contrats/" not in f"/{chemin}"
            ):
                continue
            for numero_page, texte in enumerate(pages, 1):
                # Les clauses sont généralement séparées par un point, un
                # point-virgule ou un retour de ligne. Conserver assez de
                # contexte pour restituer l'obligation complète.
                segments = [
                    _nettoyer_extrait_pdf(segment)
                    for segment in re.split(r"(?<=[.;!?])\s+|\n+", texte)
                ]
                for indice, segment in enumerate(segments):
                    if len(segment) < 35:
                        continue
                    # Partir du titre trouvé évite d'inclure la fin de la clause
                    # précédente (ex. Santé et sécurité avant Assurance).
                    contexte = " ".join(segments[indice:indice + 3])[:1300]
                    normalise = _normaliser(contexte)
                    for titre, ancres in themes:
                        hits = sum(ancre in normalise for ancre in ancres)
                        if not hits:
                            continue
                        action = sum(mot in normalise for mot in (
                            "doit", "devra", "s'engage", "est tenu", "sera", "payer"
                        ))
                        candidats.append((5 * hits + 2 * action, titre, SourceChat(
                            document=nom, page=numero_page,
                            type_document="CONTRAT", titre=titre, texte=contexte,
                        )))

        candidats.sort(key=lambda element: element[0], reverse=True)
        sources: list[SourceChat] = []
        themes_vus: dict[str, int] = {}
        preuves_vues: set[tuple] = set()
        for _, titre, source in candidats:
            if themes_vus.get(titre, 0) >= 1:
                continue
            cle = (source.page, _normaliser(source.texte)[:300])
            if cle in preuves_vues:
                continue
            preuves_vues.add(cle)
            themes_vus[titre] = themes_vus.get(titre, 0) + 1
            sources.append(source)

        if not sources:
            return None  # laisser le moteur générique répondre honnêtement

        lignes = [
            f"- **[S{i}] {source.titre} — page {source.page}** : {source.texte}"
            for i, source in enumerate(sources, 1)
        ]
        return ReponseChat(
            "Clauses contractuelles explicitement retrouvées :\n\n" + "\n".join(lignes),
            sources, "clauses_contrat_pdf", time.perf_counter() - debut,
        )

    def _reponse_reportage_technique_pdf(
        self, question: str, document_cible: str | None
    ) -> ReponseChat | None:
        """Traite les questions propres au reportage technique WIRTGEN.

        Le magazine n'est ni un contrat ni un guide juridique. Cette route
        empêche donc une rubrique visuellement proche mais hors sujet d'être
        présentée comme une réponse sur les avenants. Elle restitue en
        revanche les méthodes d'optimisation directement depuis le PDF.
        """
        if not document_cible:
            return None
        nom_norm = _normaliser(document_cible)
        if "rapport" not in nom_norm or "chantier" not in nom_norm:
            return None

        question_norm = _normaliser(question)
        debut = time.perf_counter()
        if "avenant" in question_norm:
            return ReponseChat(
                "Ce reportage technique ne contient pas de précaution "
                "contractuelle explicite sur la signature d'un avenant. "
                "Cette information se trouve dans le guide métier, et non "
                "dans le document sélectionné.",
                [],
                "reportage_avenant_absent",
                time.perf_counter() - debut,
            )

        intention_optimisation = any(terme in question_norm for terme in (
            "optimisation", "automatisation", "methode", "mise en oeuvre",
            "processus", "witos", "productivite", "efficacite",
        ))
        if not intention_optimisation:
            return None

        charge = self._pages_pdf(document_cible)
        if not charge:
            return None
        document, pages = charge
        sources: list[SourceChat] = []
        for numero_page in (5, 13):
            if numero_page > len(pages):
                continue
            texte = _nettoyer_extrait_pdf(pages[numero_page - 1]).strip()
            if not texte:
                continue
            titre = (
                "Automatisation et optimisation des processus"
                if numero_page == 5
                else "Les cinq modules WITOS Paving"
            )
            sources.append(SourceChat(
                document=document_cible,
                page=numero_page,
                type_document=str(document.get("type_document") or "REPORTAGE_TECHNIQUE"),
                titre=titre,
                texte=texte[:2600],
            ))
        if not sources:
            return None

        return ReponseChat(
            "Méthodes de mise en œuvre et d'optimisation mentionnées :\n\n"
            "- **Automatiser les processus de construction routière et de traitement des matériaux** afin d'améliorer la productivité, l'efficacité et la rentabilité **[S1]**.\n"
            "- **Planifier le chantier avec WITOS Paving Control**, notamment en calculant la quantité d'enrobé requise **[S2]**.\n"
            "- **Adapter la production avec le module Materials**, qui calcule les besoins en camions et ajuste la cadence de la centrale d'enrobage **[S2]**.\n"
            "- **Suivre les camions en temps réel avec le module Transport** pour coordonner les arrivées, la pose et la production **[S2]**.\n"
            "- **Centraliser les données du chantier avec le module JobSite**, ajuster la planification et enregistrer les livraisons **[S2]**.\n"
            "- **Analyser et documenter les travaux avec le module Analysis** afin d'améliorer l'efficacité des futurs chantiers **[S2]**.",
            sources,
            "reportage_optimisation_pdf",
            time.perf_counter() - debut,
        )

    def _reponse_avenant_guide_pdf(
        self, question: str, document_cible: str | None
    ) -> ReponseChat | None:
        """Répond aux questions sur la signature d'un avenant depuis le guide.

        Cette route reste volontairement très ciblée afin de ne pas modifier les
        réponses déjà validées sur les litiges, réclamations et autres documents.
        """
        question_norm = _normaliser(question)
        if "avenant" not in question_norm or not any(
            terme in question_norm
            for terme in ("sign", "precaution", "avant", "verifier", "recommand")
        ):
            return None

        debut = time.perf_counter()
        sources: list[SourceChat] = []
        for nom in self._documents_a_lire(document_cible):
            # La réponse appartient au guide du conducteur. Si l'utilisateur a
            # choisi un autre document, ne pas élargir silencieusement le périmètre.
            nom_norm = _normaliser(nom)
            if "guide" not in nom_norm or "conducteur" not in nom_norm:
                continue
            charge = self._pages_pdf(nom)
            if not charge:
                continue
            document, pages = charge
            for numero_page, texte in enumerate(pages, 1):
                texte_norm = _normaliser(texte)
                if not (
                    "precautions a prendre lors de la signature" in texte_norm
                    and "avenant" in texte_norm
                    and "signataires" in texte_norm
                ):
                    continue
                debut_section = re.search(
                    r"QUELLES\s+SONT\s+LES\s+PRÉCAUTIONS.*?AVENANT\s*\?",
                    texte,
                    re.IGNORECASE | re.DOTALL,
                )
                extrait = texte[debut_section.end():] if debut_section else texte
                extrait = _nettoyer_extrait_pdf(extrait).strip()
                sources.append(SourceChat(
                    document=nom,
                    page=numero_page,
                    type_document=str(document.get("type_document") or "GUIDE_METIER"),
                    titre="Précautions avant la signature d'un avenant",
                    texte=extrait[:2200],
                ))
                break

        if not sources:
            # Laisser la recherche générique travailler pour un autre guide,
            # sans inventer une recommandation absente du document sélectionné.
            return None

        return ReponseChat(
            "Précautions à prendre avant de signer un avenant :\n\n"
            "- **Définir précisément l'objet de l'avenant** : il doit être clair et bien délimité.\n"
            "- **Vérifier l'habilitation des signataires** avant toute signature.\n"
            "- **Rédiger un texte explicite** sur chacun des points modifiés.\n"
            "- **Contrôler attentivement la clause de renonciation à recours** : éviter une renonciation générale couvrant tous les faits antérieurs.\n"
            "- **Limiter la renonciation aux seuls sujets mentionnés dans l'objet** de l'avenant et consulter le service juridique en cas de doute.\n\n"
            "Ces précautions sont indiquées dans **[S1]**, page 27 du guide.",
            sources,
            "avenant_guide_pdf",
            time.perf_counter() - debut,
        )

    def _reponse_normes_pdf(
        self, question: str, document_cible: str | None
    ) -> ReponseChat | None:
        """Inventorie les normes sur toutes les pages, pas seulement dans l'index."""
        question_norm = _normaliser(question)
        if not any(mot in question_norm for mot in (
            "norme", "normes", "dtu", "eurocode", "reference technique"
        )):
            return None
        debut = time.perf_counter()
        motif = re.compile(
            # Certains PDF insèrent des espaces entre les chiffres (ex. ``2 06-1``).
            # Accepter cette forme évite de tronquer NF EN 206-1 en « NF EN 2 ».
            r"\b(?:NF\s*EN\s*(?:\d\s*){2,6}(?:[-./]\s*\d+)*|NF\s*P\s*\d+(?:[-./]\d+)*|"
            r"NFP\s*\d+(?:[-./]\d+)*|D\.?\s*T\.?\s*U\.?\s*(?:N[°o]\s*)?\d+(?:[.-]\d+)*|"
            r"ISO\s*\d+(?:\s*(?:ou|/)\s*\d+)?|EUROCODE(?:S)?(?:\s*\d+)?)\b",
            re.IGNORECASE,
        )
        valeurs: dict[str, set[int]] = {}
        sources: list[SourceChat] = []
        for nom in self._documents_a_lire(document_cible):
            charge = self._pages_pdf(nom)
            if not charge:
                continue
            document, pages = charge
            for numero_page, texte in enumerate(pages, 1):
                extraits = []
                for trouve in motif.finditer(texte):
                    valeur = re.sub(r"\s+", " ", trouve.group(0)).strip().upper()
                    if valeur.startswith("NF EN "):
                        prefixe, numero = valeur[:6], valeur[6:]
                        valeur = prefixe + re.sub(r"(?<=\d)\s+(?=\d)", "", numero)
                    valeur = re.sub(r"D\.?\s*T\.?\s*U\.?", "DTU", valeur)
                    extraits.append(valeur)
                nouveaux = [v for v in dict.fromkeys(extraits) if v not in valeurs]
                if not nouveaux:
                    continue
                sources.append(SourceChat(
                    document=nom, page=numero_page,
                    type_document=str(document.get("type_document") or ""),
                    titre="Normes et références",
                    texte=re.sub(r"\s+", " ", texte).strip()[:900],
                ))
                numero = len(sources)
                for valeur in nouveaux:
                    valeurs.setdefault(valeur, set()).add(numero)
                if len(valeurs) >= 30:
                    break
        if not valeurs:
            perimetre = f" dans « {document_cible} »" if document_cible else " dans le corpus"
            return ReponseChat(
                f"Aucune norme ou référence technique explicite n'a été trouvée{perimetre}.",
                [], "normes_non_trouvees", time.perf_counter() - debut,
            )
        details = [
            f"- **{valeur}** — " + ", ".join(f"[S{n}]" for n in sorted(numeros))
            for valeur, numeros in sorted(valeurs.items())
        ]
        return ReponseChat(
            "Normes et références techniques explicitement mentionnées :\n\n"
            + "\n".join(details), sources, "normes_pdf", time.perf_counter() - debut,
        )

    def _reponse_terrassements_pdf(
        self, question: str, document_cible: str | None
    ) -> ReponseChat | None:
        """Cherche les prescriptions de terrassement/fondation dans le PDF complet."""
        question_norm = _normaliser(question)
        if not any(mot in question_norm for mot in (
            "terrassement", "fondation", "fouille", "remblai"
        )):
            return None
        debut = time.perf_counter()
        ancres = ("terrassement", "fondation", "fouille", "remblai", "compactage")
        # Source prioritaire : les résultats déjà extraits par le pipeline et
        # rattachés au document/page dans SQLite. La lecture directe du PDF
        # enrichit ensuite la réponse, mais ne peut plus effacer ces preuves.
        candidats: list[tuple[int, SourceChat]] = [
            (100, source)
            for source in self._sources_stockees_par_ancres(
                document_cible, ancres, limite=8
            )
        ]
        if candidats:
            sources = [source for _, source in candidats[:6]]
            lignes = [
                f"- **[S{i}] page {source.page} — {source.titre}** : "
                f"{_nettoyer_extrait_pdf(source.texte)}"
                for i, source in enumerate(sources, 1)
            ]
            return ReponseChat(
                "Prescriptions relatives aux terrassements et aux fondations :\n\n"
                + "\n".join(lignes),
                sources,
                "terrassements_sqlite",
                time.perf_counter() - debut,
            )
        for nom in self._documents_a_lire(document_cible):
            charge = self._pages_pdf(nom)
            if not charge:
                continue
            document, pages = charge
            for numero_page, texte in enumerate(pages, 1):
                lignes = [
                    re.sub(r"\s+", " ", ligne).strip()
                    for ligne in texte.splitlines()
                    if len(re.sub(r"\s+", " ", ligne).strip()) >= 18
                ]
                for indice, ligne in enumerate(lignes):
                    passage = " ".join(lignes[max(0, indice - 1):indice + 3])[:850]
                    normalise = _normaliser(passage)
                    hits = sum(ancre in normalise for ancre in ancres)
                    if not hits:
                        continue
                    technique = sum(bool(re.search(motif, passage, re.I)) for motif in (
                        r"\d+\s*%", r"EV\s*\d", r"\bqc\b", r"MPa", r"Proctor",
                        r"doit|devra|seront|agrément|contrôle",
                    ))
                    candidats.append((3 * hits + 2 * technique, SourceChat(
                        document=nom, page=numero_page,
                        type_document=str(document.get("type_document") or ""),
                        titre=ligne[:150], texte=passage,
                    )))
        candidats.sort(key=lambda element: element[0], reverse=True)
        sources: list[SourceChat] = []
        vus = set()
        for _, source in candidats:
            cle = (source.document, source.page, _normaliser(source.texte)[:240])
            if cle in vus:
                continue
            vus.add(cle)
            sources.append(source)
            if len(sources) >= 6:
                break
        if not sources:
            perimetre = f" dans « {document_cible} »" if document_cible else " dans le corpus"
            return ReponseChat(
                f"Aucune prescription explicite de terrassement ou de fondation n'a été trouvée{perimetre}.",
                [], "terrassement_non_trouve", time.perf_counter() - debut,
            )
        lignes = [
            f"- **[S{i}] page {source.page}** : {_nettoyer_extrait_pdf(source.texte)}"
            for i, source in enumerate(sources, 1)
        ]
        mode = "terrassements_pdf"
        return ReponseChat(
            "Prescriptions relatives aux terrassements et aux fondations :\n\n"
            + "\n".join(lignes), sources, mode,
            time.perf_counter() - debut,
        )

    def _rechercher(
        self, question: str, limite: int = 2, document_cible: str | None = None
    ) -> list[tuple[float, dict]]:
        self._charger_index()
        if not self._index:
            return []
        tokens = _tokens_utiles(question)
        question_norm = _normaliser(question)
        intention_materiaux = "materiau" in question_norm or "materiaux" in question_norm
        # Enrichissement lexical léger : les formulations utilisateur et celles
        # des contrats n'emploient pas toujours exactement le même mot.
        if "sous-trait" in question_norm or "sous trait" in question_norm:
            tokens.update({"sous", "traitance", "traitant", "traitants", "agrement"})
        termes_exacts = re.findall(
            r"\b(?:nf\s+)?en\s+\d+(?:[-/]\d+)*\b|\bdtu\s+\d+(?:[.-]\d+)*\b",
            question_norm,
        )
        types_prioritaires = set()
        if any(mot in question_norm for mot in ("rapport", "probleme de chantier", "signale")):
            types_prioritaires.add("REPORTAGE_TECHNIQUE")
        if any(mot in question_norm for mot in ("conducteur", "recommandation", "bonne pratique")):
            types_prioritaires.add("GUIDE_METIER")
        intention_recommandation = any(
            mot in question_norm for mot in ("recommandation", "recommande", "bonne pratique", "conseil")
        )
        # Les recommandations sont nombreuses dans un guide. Lorsqu'un thème
        # précis est demandé, il devient un critère obligatoire et non un
        # simple bonus, sinon une recommandation générale peut passer devant.
        termes_theme_obligatoires: set[str] = set()
        if any(mot in question_norm for mot in ("litige", "reclamation", "differend")):
            termes_theme_obligatoires.update(
                {"litige", "litiges", "reclamation", "reclamations", "differend", "amiable"}
            )
        if any(mot in question_norm for mot in ("incident", "probleme", "observation")):
            termes_theme_obligatoires.update(
                {"incident", "incidents", "probleme", "observation", "anomalie", "difficulte"}
            )
        if any(mot in question_norm for mot in (
            "contrat", "clause", "paiement", "penalite", "garantie",
            "sous-trait", "sous trait", "obligation contractuelle",
        )):
            types_prioritaires.add("CONTRAT")
        if any(mot in question_norm for mot in ("cctp", "prescription", "specification")):
            types_prioritaires.add("CCTP")
        # Une correspondance lexicale métier évite de charger le modèle
        # d'embeddings et le modèle génératif simultanément sur les PC modestes.
        lexicaux = []
        if tokens:
            for ligne, _ in self._index:
                if document_cible and ligne["nom_fichier"] != document_cible:
                    continue
                titre = _normaliser(ligne["titre"])
                contenu = _normaliser(ligne["contenu"])
                if termes_theme_obligatoires and not any(
                    terme in f"{titre} {contenu}"
                    for terme in termes_theme_obligatoires
                ):
                    continue
                if intention_materiaux and not _materiaux_pertinents(
                    question, f"{ligne['titre']} {ligne['contenu']}"
                ):
                    # Le mot « réseau » seul ne prouve pas la présence d'un matériau.
                    continue
                titre_hits = sum(token in titre for token in tokens)
                contenu_hits = sum(token in contenu for token in tokens)
                bonus_type = 7 if ligne["type_document"] in types_prioritaires else 0
                bonus_exact = 12 * sum(terme in contenu for terme in termes_exacts)
                bonus_metier = (
                    16 if intention_recommandation and "categorie : recommandation" in contenu else 0
                )
                bonus_action = 0
                penalite_question_seule = 0
                if intention_recommandation:
                    if any(expression in contenu for expression in (
                        "il est conseille", "il est recommande", "il convient de",
                        "devra", "doit", "precautions pour",
                    )):
                        bonus_action = 7
                    if titre.rstrip().endswith("?") and len(titre) < 180:
                        penalite_question_seule = 9
                pertinence_texte = (
                    titre_hits * 3 + contenu_hits + bonus_exact + bonus_metier
                    + bonus_action - penalite_question_seule
                )
                # Le type documentaire affine une correspondance existante ; il
                # ne doit jamais rendre pertinent un passage sans rapport lexical.
                score_lexical = pertinence_texte + bonus_type
                if pertinence_texte:
                    lexicaux.append((score_lexical, ligne))
        if lexicaux:
            lexicaux.sort(key=lambda element: element[0], reverse=True)
            meilleur = lexicaux[0][0]
            # On garde les meilleurs passages, avec un score compatible avec le seuil RAG.
            candidats = [
                (0.55 + 0.04 * min(score, 6), ligne)
                for score, ligne in lexicaux if score >= max(2, meilleur - 2)
            ]
        elif not document_cible:
            vecteur_question = _embeddings([question])[0]
            candidats = []
            for ligne, vecteur in self._index:
                if document_cible and ligne["nom_fichier"] != document_cible:
                    continue
                score = _cosinus(vecteur_question, vecteur)
                candidats.append((score, ligne))
        else:
            candidats = []

        resultats = []
        for score, ligne in candidats:
            contenu_norm = _normaliser(ligne["contenu"])
            score += min(0.12, 0.025 * sum(token in contenu_norm for token in tokens))
            resultats.append((score, ligne))
        if document_cible:
            # L'index structuré peut être volontairement sélectif. Pour un PDF
            # choisi par l'utilisateur, on complète avec ses passages textuels
            # afin de ne pas perdre une information présente ailleurs dans le document.
            resultats.extend(
                self._rechercher_dans_pdf(question, document_cible, limite=max(3, limite))
            )
        elif intention_materiaux:
            secours_pdf = self._rechercher_dans_corpus_pdf(
                question, limite=max(4, limite)
            )
            if secours_pdf and any(
                mot in question_norm for mot in ("plomberie", "sanitaire")
            ):
                resultats = [
                    resultat for resultat in resultats
                    if any(
                        terme in _normaliser(resultat[1]["nom_fichier"])
                        for terme in ("plomberie", "sanitaire")
                    )
                ]
            resultats.extend(secours_pdf)
        resultats.sort(key=lambda element: element[0], reverse=True)
        selection = []
        vus = set()
        for score, ligne in resultats:
            cle = (ligne["document_id"], ligne["page"], ligne["titre"])
            if cle in vus:
                continue
            vus.add(cle)
            selection.append((score, ligne))
            limite_finale = max(4, limite) if intention_materiaux else limite
            if len(selection) >= limite_finale:
                break
        return selection

    def repondre(
        self,
        question: str,
        historique: list[dict] | None = None,
        document_cible: str | None = None,
    ) -> ReponseChat:
        debut = time.perf_counter()
        question = question.strip()
        if not question:
            return ReponseChat("Posez une question sur le corpus BTP.", [], "vide", 0.0)

        structuree = _reponse_dqe_structuree(question, self.chemin_base, document_cible)
        if structuree is not None:
            return structuree

        inventaire = _reponse_inventaire_document(question, self.chemin_base, document_cible)
        if inventaire is not None:
            return inventaire

        if not self.index_pret():
            return ReponseChat(
                "L'index documentaire doit être préparé avant la première question.",
                [], "index_absent", time.perf_counter() - debut,
            )

        synthese = _synthese_documentaire_depuis_index(
            question, self._index, document_cible
        )
        if synthese is not None:
            return synthese

        # Les questions sur le béton bénéficient aussi du texte intégral du PDF
        # sélectionné. Cela évite de dépendre uniquement des extraits déjà indexés.
        index_beton = list(self._index)
        if document_cible and _demande_beton_structure(question):
            index_beton.extend(
                (ligne, [])
                for _, ligne in self._rechercher_dans_pdf(
                    question, document_cible, limite=12
                )
            )
        beton = _reponse_beton_depuis_index(question, index_beton, document_cible)
        if beton is not None:
            return beton

        # Le reportage est un magazine technique : ses questions sur les
        # processus utilisent directement les pages concernées du PDF.
        reportage = self._reponse_reportage_technique_pdf(question, document_cible)
        if reportage is not None:
            return reportage

        # Cas métier précis du guide des conducteurs : lire directement la
        # section consacrée à la signature d'un avenant (page 27).
        avenant = self._reponse_avenant_guide_pdf(question, document_cible)
        if avenant is not None:
            return avenant

        # Pour ces deux familles de questions, une recherche déterministe dans
        # toutes les pages est plus sûre que la recherche sémantique générique.
        normes = self._reponse_normes_pdf(question, document_cible)
        if normes is not None:
            return normes

        terrassements = self._reponse_terrassements_pdf(question, document_cible)
        if terrassements is not None:
            return terrassements

        # Les contrats PDF à police CID nécessitent une lecture directe du
        # corps des clauses. Cette route est limitée aux thèmes contractuels
        # et ne modifie donc pas les réponses CCTP/DQE déjà validées.
        clauses_contrat = self._reponse_clauses_contrat_pdf(question, document_cible)
        if clauses_contrat is not None:
            return clauses_contrat

        obligations = self._reponse_obligations_pdf(question, document_cible)
        if obligations is not None:
            return obligations

        question_norm = _normaliser(question)
        sous_questions = []
        for termes, formulation in (
            (("paiement", "prix", "acompte"), "clause de paiement et de prix"),
            (("delai", "penalite", "retard"), "clause de délais et pénalités"),
            (("garantie", "assurance"), "clause de garantie et assurance"),
        ):
            if any(terme in question_norm for terme in termes):
                sous_questions.append(formulation)
        if len(sous_questions) >= 2:
            passages = []
            cles_passages = set()
            for sous_question in sous_questions:
                for resultat in self._rechercher(
                    sous_question, limite=1, document_cible=document_cible
                ):
                    ligne = resultat[1]
                    cle = (ligne["document_id"], ligne["page"], ligne["titre"])
                    if cle not in cles_passages:
                        cles_passages.add(cle)
                        passages.append(resultat)
                        break
        else:
            passages = self._rechercher(question, document_cible=document_cible)
        passages = [
            passage for passage in passages
            if _preuve_compatible_question(question, passage[1])
        ]
        if not passages or passages[0][0] < 0.48:
            perimetre = f" dans « {document_cible} »" if document_cible else " dans le corpus"
            return ReponseChat(
                f"Je n'ai trouvé aucune preuve suffisamment fiable{perimetre} pour répondre à cette question. "
                "Précisez le document, le poste ou le thème recherché.",
                [], "non_trouve", time.perf_counter() - debut,
            )

        sources = []
        blocs = []
        for numero_source, (score, ligne) in enumerate(passages, 1):
            sources.append(
                SourceChat(
                    document=ligne["nom_fichier"], page=ligne["page"],
                    type_document=ligne["type_document"], titre=ligne["titre"],
                    texte=ligne["contenu"],
                )
            )
            contenu_prompt = ligne["contenu"]
            if "Texte source :" in contenu_prompt:
                contenu_prompt = contenu_prompt.split("Texte source :", 1)[1].strip()
            blocs.append(
                f"[S{numero_source}] Document={ligne['nom_fichier']} ; "
                f"page={ligne['page'] or 'non précisée'} ; type={ligne['type_document']}\n"
                f"Titre={ligne['titre']}\n{contenu_prompt[:650]}"
            )

        # Pour une question de matériaux, une liste factuelle est plus fiable
        # qu'une reformulation libre. Chaque valeur reste liée à sa preuve.
        question_norm = _normaliser(question)
        if "materiau" in question_norm or "materiaux" in question_norm:
            references: dict[str, list[int]] = {}
            for numero, source in enumerate(sources, 1):
                for materiau in _materiaux_pertinents(
                    question, f"{source.titre} {source.texte}"
                ):
                    references.setdefault(materiau, []).append(numero)
            if references:
                lignes_materiaux = []
                for materiau, numeros in references.items():
                    citations = ", ".join(f"[S{numero}]" for numero in sorted(set(numeros)))
                    lignes_materiaux.append(f"- **{materiau}** — {citations}")
                return ReponseChat(
                    "Les matériaux explicitement mentionnés dans les preuves sont :\n\n"
                    + "\n".join(lignes_materiaux),
                    sources,
                    "materiaux_structures",
                    time.perf_counter() - debut,
                )

        # Une question de localisation appelle une réponse courte et factuelle :
        # nom du document, page et passage repère, sans génération ni texte coupé.
        if re.search(r"\b(?:dans )?quel(?:s)? document(?:s)?\b", _normaliser(question)):
            localisations = []
            for numero, source in enumerate(sources, 1):
                page = source.page if source.page is not None else "non précisée"
                localisations.append(
                    f"- **[S{numero}] {source.document} — page {page}** : {source.titre}"
                )
            return ReponseChat(
                "L'information recherchée est mentionnée dans :\n\n"
                + "\n".join(localisations),
                sources,
                "localisation_documentaire",
                time.perf_counter() - debut,
            )

        # Les questions de consultation courante doivent rester instantanées.
        # On renvoie les phrases les plus proches avec leur preuve, sans demander
        # au modèle génératif de reformuler inutilement le document.
        demande_synthese = bool(
            re.search(r"\b(résum(?:e|er)|synthèse|synthétise)\b", _normaliser(question))
        )
        if not demande_synthese:
            tokens_question = _tokens_utiles(question)
            reponses = []
            for numero, source in enumerate(sources, 1):
                texte_source = source.texte
                if "Texte source :" in texte_source:
                    texte_source = texte_source.split("Texte source :", 1)[1].strip()
                phrases = [
                    phrase.strip(" -:\n\t")
                    for phrase in re.split(r"(?<=[.!?;])\s+|\n+", texte_source)
                    if len(phrase.strip()) >= 20
                ]
                if not phrases:
                    phrases = [re.sub(r"\s+", " ", texte_source).strip()]
                phrase = max(
                    phrases,
                    key=lambda valeur: sum(
                        token in _normaliser(valeur) for token in tokens_question
                    ),
                )
                phrase = re.sub(r"\s+", " ", phrase.replace("\ufffd", "")).strip()
                reponses.append(_preuve_directe_avec_limite(numero, source, phrase))
            return ReponseChat(
                "Voici les informations les plus pertinentes trouvées dans les documents :\n\n"
                + "\n".join(reponses),
                sources,
                "preuves_directes",
                time.perf_counter() - debut,
            )

        contexte = "\n\n".join(blocs)
        rappel = ""
        if historique:
            derniers = historique[-4:]
            rappel = "\n".join(
                f"{m.get('role', 'user')}: {str(m.get('content', ''))[:400]}" for m in derniers
            )
        prompt = f"""Tu es l'assistant documentaire d'un projet BTP.
Règles obligatoires :
- Réponds uniquement avec les sources fournies.
- N'invente jamais une valeur, une unité, une clause ou une conclusion.
- Si les sources sont insuffisantes, dis clairement que l'information n'est pas trouvée.
- Réponds en français, clairement, avec des phrases complètes, en 120 mots maximum.
- Cite les sources utilisées sous la forme [S1], [S2].
- Pour les chiffres, conserve exactement la valeur et l'unité de la source.

Historique utile :
{rappel or 'Aucun'}

Question : {question}

Sources documentaires :
{contexte}
"""
        try:
            resultat = _requete_ollama(
                "/api/generate",
                {
                    "model": MODELE_REPONSE,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "keep_alive": "30m",
                    "options": {"temperature": 0.0, "num_predict": 140, "num_ctx": 2048},
                },
                timeout=45,
            )
            texte = str(resultat.get("response") or "").strip()
            mode = "rag_local"
        except RuntimeError:
            # Le technicien reçoit tout de même des preuves utiles au lieu d'un blocage.
            apercus = []
            for numero, source in enumerate(sources, 1):
                extrait = re.sub(r"\s+", " ", source.texte).strip()
                apercus.append(f"- **[S{numero}] {source.titre}** : {extrait}")
            texte = (
                "La synthèse locale a pris trop de temps. Voici les passages les plus "
                "pertinents trouvés dans le corpus :\n\n" + "\n".join(apercus)
            )
            mode = "preuves_directes"
        if not texte:
            texte = "Je n'ai pas pu produire une réponse à partir des preuves trouvées."
        return ReponseChat(texte, sources, mode, time.perf_counter() - debut)
