"""Analyse sûre d'un PDF BTP avant son éventuelle intégration au corpus.

Le module réutilise les extracteurs déjà validés. Pour une famille inconnue, il
produit seulement une analyse générique traçable et ne prétend pas appliquer un
schéma métier spécialisé.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pdfplumber

from extract_documents_metier import extraire_contrat, extraire_guide, extraire_reportage
from extract_dqe import analyser_pdf as analyser_dqe
from extract_smart import analyser_pdf as analyser_cctp
from nlp_btp import analyser_texte


TYPES_DOCUMENT = {
    "CCTP": "CCTP — prescriptions techniques",
    "DQE": "DQE / devis — postes, quantités et prix",
    "CONTRAT": "Contrat de travaux — clauses et obligations",
    "GUIDE_METIER": "Guide métier — règles et recommandations",
    "REPORTAGE_TECHNIQUE": "Rapport / reportage technique — retour d'expérience",
    "AUTRE_BTP": "Autre document BTP — analyse générique",
}

DOSSIERS_CORPUS = {
    "CCTP": "CCTP",
    "DQE": "DQE",
    "CONTRAT": "Contrats",
    "GUIDE_METIER": "Guide_Metier",
    "REPORTAGE_TECHNIQUE": "Rapports",
    "AUTRE_BTP": "Autres_BTP",
}


# Couverture commune utilisée uniquement lorsque l'extracteur spécialisé est
# manifestement insuffisant. Chaque résultat reste un extrait exact du PDF et
# doit être validé humainement.
THEMES_METIER_SECOURS = {
    "objet_travaux": ("objet du marche", "objet des travaux", "description des travaux", "consistance des travaux"),
    "parties_intervenants": ("maitre d'ouvrage", "maitre d'oeuvre", "titulaire", "entrepreneur", "sous-traitant"),
    "delais_penalites": ("delai", "calendrier", "planning", "penalite", "retard", "date d'achevement"),
    "paiement_prix": ("paiement", "acompte", "prix", "facture", "decompte", "revision des prix"),
    "garantie_assurance": ("garantie", "assurance", "responsabilite decennale", "retenue de garantie"),
    "obligations": ("obligation", "est tenu", "doit", "devra", "a la charge"),
    "resiliation_litiges": ("resiliation", "litige", "differend", "contentieux", "tribunal"),
    "securite_prevention": ("securite", "prevention", "risque", "protection", "ppsps"),
    "qualite_controle": ("controle", "conformite", "verification", "reception", "essai"),
    "normes_references": ("norme", "dtu", "nf en", "iso", "reglementation"),
    "materiaux_ouvrages": ("beton", "acier", "ciment", "maconnerie", "canalisation", "fondation"),
    "quantites_dimensions": ("quantite", "dimension", "epaisseur", "diametre", "metre carre", "metre cube"),
    "suivi_avancement": ("avancement", "compte rendu", "rapport journalier", "incident", "observation"),
    "environnement_dechets": ("dechet", "environnement", "nuisance", "pollution", "tri"),
    "mise_en_oeuvre": ("mise en oeuvre", "execution", "mode operatoire", "realisation", "travaux comprendront"),
    "fourniture_pose": ("fourniture", "pose", "approvisionnement", "transport", "stockage"),
    "terrassement_fondations": ("terrassement", "fouille", "remblai", "compactage", "fondation"),
    "beton_armatures": ("beton arme", "betonnage", "coffrage", "ferraillage", "armature", "eprouvette"),
    "tolerances_performances": ("tolerance", "resistance", "performance", "dosage", "densite"),
}

# Ces mots sont utiles mais trop généraux pour décider seuls d'un thème.
# Exemple : « poste de contrôle » n'est pas forcément un contrôle qualité et
# « tri » ne doit jamais être retrouvé à l'intérieur du mot « maîtrise ».
MOTS_AMBIGUS_SECOURS = {"controle", "verification", "reception", "tri", "risque", "travaux comprendront"}


def _sans_accents(texte: str) -> str:
    return "".join(
        caractere for caractere in unicodedata.normalize("NFD", texte)
        if unicodedata.category(caractere) != "Mn"
    ).casefold()


def _extraire_passages_secours(
    chemin: Path, type_document: str, pages: list[dict], maximum: int = 80,
) -> list[dict]:
    """Produit des preuves thématiques exactes lorsqu'un schéma est trop strict."""
    resultats: list[dict] = []
    cles_vues: set[tuple] = set()
    for page in pages:
        texte = str(page.get("texte") or "").strip()
        if not texte:
            continue
        comparable = _sans_accents(texte)
        for categorie, mots in THEMES_METIER_SECOURS.items():
            correspondances = []
            for mot in mots:
                motif = rf"(?<!\w){re.escape(mot)}(?!\w)"
                trouve = re.search(motif, comparable)
                if trouve:
                    correspondances.append((mot, trouve.start()))
            # Un mot volontairement large ne suffit pas à lui seul : il doit
            # être accompagné d'un autre indice de la même catégorie.
            if len(correspondances) == 1 and correspondances[0][0] in MOTS_AMBIGUS_SECOURS:
                continue
            positions = [position for _, position in correspondances]
            if not positions:
                continue
            position = min(positions)
            debut = max(0, position - 220)
            fin = min(len(texte), position + 480)
            # On élargit aux limites de phrase sans dépasser une preuve courte.
            extrait = texte[debut:fin].strip(" -–—,.;:")
            cle = (page.get("page"), categorie, extrait.casefold())
            if len(extrait) < 30 or cle in cles_vues:
                continue
            cles_vues.add(cle)
            resultats.append({
                "type_document": type_document,
                "fichier_source": chemin.name,
                "page": page.get("page"),
                "categorie": categorie,
                "libelle": categorie.replace("_", " ").title(),
                "donnees": {
                    "texte_source": extrait,
                    "qualite_texte": "bonne",
                    "statut_validation": "a_verifier",
                    "origine_extraction": "secours_thematique_explicable",
                    "mots_declencheurs": [mot for mot, _ in correspondances][:4],
                },
            })
            if len(resultats) >= maximum:
                return resultats
    return resultats


def nom_securise(nom: str) -> str:
    base = Path(nom).name
    tige = re.sub(r"[^\w .()-]+", "_", Path(base).stem, flags=re.UNICODE).strip(" ._")
    return f"{tige or 'document_btp'}.pdf"


def inspecter_pdf(chemin: Path) -> dict:
    """Lit le PDF, page par page, et échoue clairement s'il est inexploitable."""
    textes: list[dict] = []
    with pdfplumber.open(chemin) as pdf:
        if not pdf.pages:
            raise ValueError("Le PDF ne contient aucune page.")
        for numero, page in enumerate(pdf.pages, 1):
            texte = " ".join((page.extract_text() or "").split())
            textes.append({"page": numero, "texte": texte})
    texte_total = " ".join(p["texte"] for p in textes).strip()
    if len(texte_total) < 20:
        raise ValueError(
            "Le PDF ne contient pas assez de texte lisible. Il est peut-être scanné et nécessite un OCR."
        )
    return {
        "nombre_pages": len(textes),
        "pages": textes,
        "nombre_caracteres": len(texte_total),
        "sha256": hashlib.sha256(chemin.read_bytes()).hexdigest(),
    }


def proposer_type(nom_fichier: str, pages: list[dict]) -> tuple[str, list[str]]:
    """Propose une famille avec des indices compréhensibles par l'utilisateur."""
    texte = f"{nom_fichier} {' '.join(p['texte'] for p in pages[:4])}".casefold()
    scores = Counter()
    indices: dict[str, list[str]] = {type_doc: [] for type_doc in TYPES_DOCUMENT}
    regles = {
        "CCTP": ("cctp", "cahier des clauses techniques", "prescriptions techniques"),
        "DQE": ("dqe", "devis quantitatif", "prix unitaire", "quantité", "montant"),
        "CONTRAT": ("contrat de travaux", "parties", "garantie", "résiliation", "paiement"),
        "GUIDE_METIER": ("guide pratique", "conducteur de travaux", "recommandation", "doit "),
        "REPORTAGE_TECHNIQUE": ("rapport de chantier", "reportage", "chantier", "compactage"),
    }
    for type_doc, mots in regles.items():
        for mot in mots:
            if mot in texte:
                scores[type_doc] += 3 if mot in nom_fichier.casefold() else 1
                indices[type_doc].append(mot)
    if not scores:
        return "AUTRE_BTP", ["Aucun marqueur documentaire spécialisé suffisamment clair"]
    proposition, _ = scores.most_common(1)[0]
    return proposition, indices[proposition][:4]


def _normaliser_cctp(blocs: list[dict]) -> list[dict]:
    return [{
        "type_document": "CCTP", "fichier_source": bloc.get("fichier_source"),
        "page": bloc.get("page"), "categorie": "materiau",
        "libelle": bloc.get("materiau") or "Élément technique",
        "donnees": {"section": bloc.get("section"), "texte_source": bloc.get("texte_source"),
                    **bloc.get("entites", {})},
    } for bloc in blocs]


def _normaliser_dqe(postes: list[dict]) -> list[dict]:
    champs = ("numero_poste", "unite", "quantite", "prix_unitaire", "prix_total",
              "controle_calcul", "texte_source")
    return [{
        "type_document": "DQE", "fichier_source": poste.get("fichier_source"),
        "page": poste.get("page"), "categorie": "poste_devis",
        "libelle": poste.get("designation") or "Poste sans désignation",
        "donnees": {champ: poste.get(champ) for champ in champs},
    } for poste in postes]


def _analyse_generique(chemin: Path, pages: list[dict]) -> list[dict]:
    elements: list[dict] = []
    for page in pages:
        for passage in re.split(r"(?<=[.!?])\s+|\n+", page["texte"]):
            passage = passage.strip()
            if len(passage) < 25:
                continue
            analyse = analyser_texte(passage)
            if not analyse.get("entites"):
                continue
            elements.append({
                "type_document": "AUTRE_BTP", "fichier_source": chemin.name,
                "page": page["page"], "categorie": "passage_technique",
                "libelle": passage[:110] + ("…" if len(passage) > 110 else ""),
                "donnees": {"texte_source": passage[:2000], "entites": analyse["entites"]},
            })
    return elements


def _resume(elements: list[dict], inspection: dict) -> dict:
    categories = Counter(e.get("categorie") or "non_classee" for e in elements)
    entites = Counter()
    statuts = Counter()
    passages = []
    for element in elements:
        donnees = element.get("donnees", {})
        analyse = analyser_texte(" ".join((str(element.get("libelle") or ""),
                                           str(donnees.get("texte_source") or ""))))
        for categorie, valeurs in analyse.get("entites", {}).items():
            entites[categorie] += len(valeurs)
        statut = donnees.get("controle_calcul") or donnees.get("statut_validation")
        if statut:
            statuts[str(statut)] += 1
        source = donnees.get("texte_source")
        if source and len(passages) < 5:
            passages.append({"page": element.get("page"), "libelle": element.get("libelle"),
                              "texte_source": source})
    return {
        "nombre_pages": inspection["nombre_pages"], "nombre_elements": len(elements),
        "categories": dict(categories), "entites": dict(entites), "controles": dict(statuts),
        "passages_representatifs": passages,
        "points_vigilance": (["Aucun élément structuré détecté : vérifier le type choisi ou utiliser un OCR."]
                              if not elements else []),
    }


def analyser_nouveau_document(chemin: Path, type_choisi: str = "AUTO") -> dict:
    inspection = inspecter_pdf(chemin)
    type_propose, indices = proposer_type(chemin.name, inspection["pages"])
    type_final = type_propose if type_choisi == "AUTO" else type_choisi
    extracteurs = {
        "CCTP": lambda p: _normaliser_cctp(analyser_cctp(p)),
        "DQE": lambda p: _normaliser_dqe(analyser_dqe(p)),
        "CONTRAT": extraire_contrat,
        "GUIDE_METIER": extraire_guide,
        "REPORTAGE_TECHNIQUE": extraire_reportage,
    }
    elements = (extracteurs[type_final](chemin) if type_final in extracteurs
                else _analyse_generique(chemin, inspection["pages"]))
    seuil_minimum = max(3, min(12, inspection["nombre_pages"] // 3))
    secours_active = False
    if type_final in {"CCTP", "CONTRAT", "GUIDE_METIER", "REPORTAGE_TECHNIQUE", "AUTRE_BTP"} and len(elements) < seuil_minimum:
        passages_secours = _extraire_passages_secours(
            chemin, type_final, inspection["pages"],
        )
        cles_existantes = {
            (e.get("page"), e.get("categorie"),
             str(e.get("donnees", {}).get("texte_source") or "").casefold())
            for e in elements
        }
        for passage in passages_secours:
            cle = (passage.get("page"), passage.get("categorie"),
                   str(passage.get("donnees", {}).get("texte_source") or "").casefold())
            if cle not in cles_existantes:
                elements.append(passage)
                cles_existantes.add(cle)
                secours_active = True
    return {
        "nom_fichier": chemin.name, "type_propose": type_propose, "indices_type": indices,
        "type_final": type_final, "inspection": inspection, "elements": elements,
        "resume": _resume(elements, inspection),
        # Toute famille BTP peut être conservée dans le corpus documentaire.
        # Seules les familles disposant d'un extracteur dédié sont analysables
        # par le pipeline métier complet.
        "integrable": type_final in DOSSIERS_CORPUS,
        "analysable": type_final != "AUTRE_BTP",
        "secours_thematique_active": secours_active,
    }
