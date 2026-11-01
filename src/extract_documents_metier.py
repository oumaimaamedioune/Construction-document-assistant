"""Extraction structurée des documents métier complémentaires.

Les contrats, guides et reportages techniques n'ont pas la même finalité qu'un
CCTP ou un DQE. Ce module applique donc un scénario dédié à chaque famille et
conserve systématiquement la page et le texte source. Aucune valeur absente
n'est inventée.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pdfplumber


RACINE_PROJET = Path(__file__).resolve().parents[1]
FICHIER_SORTIE = RACINE_PROJET / "resultats_documents_metier.json"

SOURCES = {
    "CONTRAT": RACINE_PROJET / "data" / "Contrats",
    "GUIDE_METIER": RACINE_PROJET / "data" / "Guide_Metier",
    "REPORTAGE_TECHNIQUE": RACINE_PROJET / "data" / "Rapports",
}

CONTRAT_CATEGORIES = {
    "parties": ("PARTIES", "REPRÉSENTANT", "REPRESENTANT", "COMMUNICATION"),
    "objet_travaux": ("OBJET", "DESCRIPTION DES TRAVAUX", "MATÉRIAUX", "MATERIAUX", "MAIN-D’ŒUVRE"),
    "prix": ("PRIX", "COÛT", "COUT"),
    "modifications": ("MODIFICATION",),
    "suspension": ("SUSPENSION",),
    "sous_traitance_securite": ("SOUS-TRAIT", "SÉCURITÉ", "SECURITE"),
    "delais_penalites": ("FIN DES TRAVAUX", "DÉLAI", "DELAI", "PÉNALIT", "PENALIT"),
    "paiement": ("PAIEMENT",),
    "garantie": ("GARANTIE",),
    "resiliation": ("RÉSILIATION", "RESILIATION", "TERMINAISON"),
    "loi_differends": ("LOI", "DIFFÉREND", "DIFFEREND", "LITIGE"),
}

GUIDE_CATEGORIES = {
    "document_suivi": ("rapport journalier", "registre de chantier", "compte-rendu", "journal de chantier", "rapport de chantier", "attachement"),
    "obligation": ("doit ", "doivent ", "est tenu", "obligatoire"),
    "recommandation": ("recommand", "conseill", "précaution", "precaution", "il convient"),
    "risque_preuve": ("preuve", "litige", "différend", "differend", "réclamation", "reclamation"),
}

EQUIPEMENTS = (
    "WIRTGEN", "VÖGELE", "VOGELE", "HAMM", "KLEEMANN", "BENNINGHOVEN",
    "finisseur", "fraiseuse", "compacteur", "concasseur", "crible", "centrale d’enrobage",
)
PROCEDES = (
    "compactage", "fraisage", "pose", "recyclage", "concassage", "criblage",
    "enrobé", "enrobe", "asphalte", "béton", "beton", "automatisation",
)


def nettoyer_texte(texte: str) -> str:
    """Nettoie uniquement les artefacts sûrs, sans réécrire le document."""
    texte = texte.replace("\x00", " ").replace("\u00ad", "")
    return re.sub(r"[ \t]+", " ", texte).strip()


def qualite_texte(texte: str) -> tuple[str, float]:
    """Mesure la part d'artefacts PDF ``(cid:...)``."""
    artefacts = len(re.findall(r"\(cid:\d+\)", texte))
    mots = len(re.findall(r"\b\w+\b", texte))
    ratio = round(artefacts / max(1, mots + artefacts), 3)
    return ("degradee" if ratio >= 0.08 else "bonne", ratio)


def paragraphes(texte: str) -> list[str]:
    blocs = re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-ZÀ-ÖØ-Ý])", nettoyer_texte(texte))
    return [re.sub(r"\s+", " ", bloc).strip() for bloc in blocs if len(bloc.strip()) >= 35]


def categorie_contrat(titre: str) -> str:
    titre_haut = titre.upper()
    for categorie, indices in CONTRAT_CATEGORIES.items():
        if any(indice in titre_haut for indice in indices):
            return categorie
    return "clause_generale"


def nettoyer_titre_contrat(titre: str) -> str:
    """Répare les caractères artificiellement triplés par certaines polices PDF."""
    return re.sub(r"(.)\1{2,}", r"\1", titre, flags=re.IGNORECASE).strip()


def extraire_contrat(chemin: Path) -> list[dict]:
    resultats: list[dict] = []
    motif_titre = re.compile(r"^(\d+(?:\.\d+)*)\.\s+([A-ZÀ-ÖØ-Ý][A-ZÀ-ÖØ-Ý ’'\-/]{3,})$")
    with pdfplumber.open(chemin) as pdf:
        for numero, page in enumerate(pdf.pages, 1):
            brut = page.extract_text() or ""
            qualite, ratio = qualite_texte(brut)
            lignes = [nettoyer_texte(l) for l in brut.splitlines() if nettoyer_texte(l)]
            titres = []
            for ligne in lignes:
                match = motif_titre.match(ligne)
                if match:
                    titres.append((match.group(1), nettoyer_titre_contrat(match.group(2))))
            # Une page dégradée reste exploitable pour ses titres lisibles et
            # doit être signalée à l'utilisateur pour validation humaine.
            for section, titre in titres:
                resultats.append({
                    "type_document": "CONTRAT",
                    "fichier_source": chemin.name,
                    "page": numero,
                    "categorie": categorie_contrat(titre),
                    "libelle": titre.title(),
                    "donnees": {
                        "section": section,
                        "texte_source": titre,
                        "qualite_texte": qualite,
                        "ratio_artefacts": ratio,
                        "statut_validation": "a_verifier" if qualite == "degradee" else "extrait",
                    },
                })
            if numero == 1:
                for libelle, motif in {
                    "numero_reference": r"Numéro de référence\s*:\s*(.*?)(?=\s+Adresse du bâtiment\s*:|$)",
                    "adresse_batiment": r"Adresse du bâtiment\s*:\s*([^\n]+)",
                }.items():
                    match = re.search(motif, brut, re.IGNORECASE)
                    valeur = match.group(1).strip(" _") if match else ""
                    # Les traits de formulaire ne sont pas une valeur métier.
                    valeur = valeur if valeur and len(valeur.replace("_", "").strip()) >= 2 else None
                    resultats.append({
                        "type_document": "CONTRAT", "fichier_source": chemin.name,
                        "page": 1, "categorie": "identification", "libelle": libelle.replace("_", " ").title(),
                        "donnees": {"valeur": valeur, "renseigne": valeur is not None,
                                    "texte_source": match.group(0) if match else "",
                                    "qualite_texte": qualite},
                    })
    return resultats


def extraire_guide(chemin: Path) -> list[dict]:
    resultats: list[dict] = []
    with pdfplumber.open(chemin) as pdf:
        for numero, page in enumerate(pdf.pages, 1):
            texte = page.extract_text() or ""
            for bloc in paragraphes(texte):
                bloc_min = bloc.casefold()
                categories = [cat for cat, indices in GUIDE_CATEGORIES.items() if any(i in bloc_min for i in indices)]
                if not categories:
                    continue
                # Un même passage peut constituer à la fois une recommandation
                # et une preuve : les catégories sont conservées explicitement.
                resultats.append({
                    "type_document": "GUIDE_METIER", "fichier_source": chemin.name,
                    "page": numero, "categorie": categories[0],
                    "libelle": bloc[:100] + ("…" if len(bloc) > 100 else ""),
                    "donnees": {"categories_associees": categories[1:], "texte_source": bloc,
                                "qualite_texte": qualite_texte(texte)[0]},
                })
    return resultats


def valeurs_presentes(texte: str, vocabulaire: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(mot for mot in vocabulaire if mot.casefold() in texte.casefold()))


def extraire_reportage(chemin: Path) -> list[dict]:
    resultats: list[dict] = []
    motif_lieu = re.compile(r"\b(?:à|au|aux|en)\s+([A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ\-]+(?:\s+[A-ZÀ-ÖØ-Ý][A-Za-zÀ-ÖØ-öø-ÿ\-]+){0,2})")
    with pdfplumber.open(chemin) as pdf:
        for numero, page in enumerate(pdf.pages, 1):
            texte = nettoyer_texte(page.extract_text() or "")
            equipements = valeurs_presentes(texte, EQUIPEMENTS)
            procedes = valeurs_presentes(texte, PROCEDES)
            if not equipements and not procedes:
                continue
            lignes = [l.strip() for l in texte.splitlines() if len(l.strip()) > 8]
            titre = next((l for l in lignes if "//" in l), lignes[0] if lignes else f"Page {numero}")
            lieux = list(dict.fromkeys(m.group(1) for m in motif_lieu.finditer(texte)))[:5]
            resultats.append({
                "type_document": "REPORTAGE_TECHNIQUE", "fichier_source": chemin.name,
                "page": numero, "categorie": "cas_chantier_technique", "libelle": titre[:140],
                "donnees": {"equipements": equipements, "procedes_materiaux": procedes,
                            "lieux_candidats": lieux, "texte_source": texte[:2500],
                            "qualite_texte": qualite_texte(texte)[0]},
            })
    return resultats


def analyser_corpus() -> list[dict]:
    extracteurs = {"CONTRAT": extraire_contrat, "GUIDE_METIER": extraire_guide,
                   "REPORTAGE_TECHNIQUE": extraire_reportage}
    resultats: list[dict] = []
    for type_document, dossier in SOURCES.items():
        for chemin in sorted(dossier.glob("*.pdf")):
            resultats.extend(extracteurs[type_document](chemin))
    return resultats


def main() -> None:
    resultats = analyser_corpus()
    FICHIER_SORTIE.write_text(json.dumps(resultats, ensure_ascii=False, indent=2), encoding="utf-8")
    compte = Counter(r["type_document"] for r in resultats)
    print("=" * 68)
    print("EXTRACTION DES DOCUMENTS METIER COMPLEMENTAIRES")
    print("=" * 68)
    for type_document in SOURCES:
        print(f"{type_document} : {compte[type_document]} élément(s)")
    print(f"Total : {len(resultats)} élément(s) traçables")
    print(f"Résultat : {FICHIER_SORTIE}")


if __name__ == "__main__":
    main()
