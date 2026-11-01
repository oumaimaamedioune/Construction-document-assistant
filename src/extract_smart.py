"""Extraction des caractéristiques techniques contenues dans les CCTP.

Le module traite tous les PDF présents dans ``data/CCTP`` et conserve, pour
chaque information, le fichier, la page, la section et la ligne source. Cette
traçabilité est indispensable pour permettre la vérification métier.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pdfplumber


RACINE_PROJET = Path(__file__).resolve().parents[1]
DOSSIER_CCTP = RACINE_PROJET / "data" / "CCTP"
FICHIER_SORTIE = RACINE_PROJET / "resultats_extraction.json"

MATERIAUX_CLES = (
    "béton", "beton", "acier", "coffrage", "brique", "mortier", "enduit",
    "peinture", "étanchéité", "etancheite", "isolation", "plancher", "dalle",
    "voile", "mur", "maçonnerie", "maconnerie", "ferraillage", "armature",
    "bois", "terrassement", "plomberie", "sanitaire", "électricité",
    "menuiserie", "structure", "métallique", "metallique", "fondation",
    "assainissement", "revêtement", "revetement", "tuyau", "canalisation",
    "réseau", "reseau", "terrasse bois",
)

# Les motifs sont compilés séparément : une norme « EN » doit rester en
# majuscules afin de ne plus confondre « en 5 exemplaires » avec une norme.
PATTERNS = {
    "resistance": re.compile(r"\b\d{1,3}(?:[.,]\d+)?\s*MPa\b", re.IGNORECASE),
    "classe_beton": re.compile(r"\bC\d{2,3}/\d{2,3}\b", re.IGNORECASE),
    "norme": re.compile(
        r"\b(?:NM|EN|DTU|NF|ISO|ASTM)(?:\s+(?:EN|ISO))?\s+[A-Z]?\d[\d.\-]*(?:\s+\d{2,4})?\b"
    ),
    "dimension": re.compile(
        r"\b\d{1,4}(?:[.,]\d+)?\s*[x×]\s*\d{1,4}(?:[.,]\d+)?"
        r"(?:\s*[x×]\s*\d{1,4}(?:[.,]\d+)?)?\s*(?:cm|mm|m)?\b",
        re.IGNORECASE,
    ),
    "dosage": re.compile(
        r"\b(?:\d{2,4}(?:[.,]\d+)?\s*kg\s*/\s*m[³3]|\d{2,4}(?:[.,]\d+)?\s*kg\s+de\s+ciment)\b",
        re.IGNORECASE,
    ),
    "masse_volumique": re.compile(
        r"(?<=masse volumique supérieure à )\d{2,4}(?:[.,]\d+)?\s*kg\s*/\s*m[³3]\b",
        re.IGNORECASE,
    ),
    "diametre": re.compile(
        r"(?:[Øøᴓ]\s*\d{1,3}(?:[.,]\d+)?|\bdiam(?:è|e)tres?\s+(?:(?:extérieur|inférieur(?:e)?s?\s+à)\s+)?\d{1,3}(?:[.,]\d+)?)\s*(?:mm|cm|m)?\b",
        re.IGNORECASE,
    ),
    "acier_type": re.compile(r"\bFeE\s*\d+\b", re.IGNORECASE),
    # Une unité seule ne suffit pas à prouver qu'il s'agit d'une épaisseur :
    # Ø 63 mm est un diamètre, H = 50 cm une hauteur et 14 x 14 cm une section.
    "epaisseur": re.compile(
        r"(?:"
        r"(?:épaisseur|ép\.)\s+(?:minimale?\s+)?(?:de\s+|à\s+)?\d{1,3}(?:[.,]\d+)?\s*(?:cm|mm)"
        r"|\d{1,3}(?:[.,]\d+)?\s*(?:cm|mm)\s+d['’]épaisseur"
        r")",
        re.IGNORECASE,
    ),
    "grammage": re.compile(r"\b\d{2,4}(?:[.,]\d+)?\s*g\s*/\s*m[²2]\b", re.IGNORECASE),
    "pourcentage": re.compile(r"\b\d{1,3}(?:[.,]\d+)?\s*%", re.IGNORECASE),
}

# Les CCTP du corpus emploient aussi bien ``2.5.1 Béton`` que
# ``4-11 - Béton balayé``. Le séparateur fait donc partie du numéro.
SECTION_PATTERN = re.compile(r"^(\d+(?:[.\-]\d+)*)\s*(?:[-–:]\s*)?(.+)")


def detecter_materiau(titre: str) -> str | None:
    """Retourne le titre s'il désigne une section technique connue."""
    titre_minuscule = titre.casefold()
    if any(mot in titre_minuscule for mot in MATERIAUX_CLES):
        return titre.strip()
    return None


def extraire_entites(ligne: str) -> dict[str, list[str]]:
    """Extrait les valeurs techniques d'une ligne sans doublons."""
    entites: dict[str, list[str]] = {}
    for categorie, pattern in PATTERNS.items():
        valeurs = [match.group(0).strip() for match in pattern.finditer(ligne)]
        if valeurs:
            entites[categorie] = list(dict.fromkeys(valeurs))
    # ``kg/m³`` est une unité ambiguë. Quand la ligne indique explicitement
    # une masse volumique, la valeur ne doit pas être doublée comme dosage.
    if "masse_volumique" in entites and "dosage" in entites:
        masses = {valeur.casefold().replace(" ", "") for valeur in entites["masse_volumique"]}
        entites["dosage"] = [
            valeur for valeur in entites["dosage"]
            if valeur.casefold().replace(" ", "") not in masses
        ]
        if not entites["dosage"]:
            del entites["dosage"]
    return entites


def analyser_pdf(chemin_pdf: Path) -> list[dict]:
    """Analyse un CCTP et renvoie ses blocs techniques traçables."""
    resultats: list[dict] = []
    section_actuelle: str | None = None
    materiau_actuel: str | None = None

    with pdfplumber.open(chemin_pdf) as pdf:
        for numero_page, page in enumerate(pdf.pages, start=1):
            texte = page.extract_text() or ""
            for ligne_brute in texte.splitlines():
                ligne = " ".join(ligne_brute.split())
                if not ligne:
                    continue

                section = SECTION_PATTERN.match(ligne)
                if section:
                    section_actuelle = section.group(1)
                    materiau_actuel = detecter_materiau(section.group(2))

                entites = extraire_entites(ligne)
                if entites and materiau_actuel:
                    resultats.append(
                        {
                            "fichier_source": chemin_pdf.name,
                            "page": numero_page,
                            "section": section_actuelle,
                            "materiau": materiau_actuel,
                            "texte_source": ligne[:300],
                            "entites": entites,
                        }
                    )

    return resultats


def executer_extraction() -> dict[str, list[dict]]:
    """Traite tous les CCTP, exporte le JSON et retourne les résultats."""
    fichiers_pdf = sorted(DOSSIER_CCTP.glob("*.pdf"), key=lambda p: p.name.casefold())
    if not fichiers_pdf:
        raise FileNotFoundError(f"Aucun PDF trouvé dans {DOSSIER_CCTP}")

    print("=" * 72)
    print("EXTRACTION CCTP - TRAITEMENT MULTI-FICHIERS")
    print("=" * 72)
    print(f"Dossier : {DOSSIER_CCTP}")
    print(f"Nombre de PDF : {len(fichiers_pdf)}\n")

    tous_les_resultats: list[dict] = []
    erreurs: list[tuple[str, str]] = []

    for chemin_pdf in fichiers_pdf:
        try:
            resultats_pdf = analyser_pdf(chemin_pdf)
            tous_les_resultats.extend(resultats_pdf)
            print(f"[OK] {chemin_pdf.name}: {len(resultats_pdf)} bloc(s)")
        except Exception as exc:  # un PDF défectueux ne bloque pas tout le lot
            erreurs.append((chemin_pdf.name, str(exc)))
            print(f"[ERREUR] {chemin_pdf.name}: {exc}")

    par_materiau: defaultdict[str, list[dict]] = defaultdict(list)
    for resultat in tous_les_resultats:
        par_materiau[resultat["materiau"]].append(resultat)

    sortie = dict(sorted(par_materiau.items(), key=lambda item: item[0].casefold()))
    with FICHIER_SORTIE.open("w", encoding="utf-8") as fichier:
        json.dump(sortie, fichier, ensure_ascii=False, indent=2)

    repartition = Counter(r["fichier_source"] for r in tous_les_resultats)
    print("\nRésumé par fichier :")
    for nom_fichier, nombre in repartition.items():
        print(f"  - {nom_fichier}: {nombre}")
    print(f"\nTotal : {len(tous_les_resultats)} bloc(s) extrait(s)")
    print(f"Fichiers en erreur : {len(erreurs)}")
    print(f"Résultat : {FICHIER_SORTIE}")
    return sortie


if __name__ == "__main__":
    executer_extraction()
