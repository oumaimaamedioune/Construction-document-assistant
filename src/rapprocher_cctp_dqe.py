"""Rapprochement local, explicable et non destructif entre CCTP et DQE."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path


RACINE_PROJET = Path(__file__).resolve().parents[1]
ENTREE = RACINE_PROJET / "resultats_nlp.json"
SORTIE = RACINE_PROJET / "resultats_rapprochement.json"

MOTS_VIDES = {
    "a", "au", "aux", "avec", "ce", "ces", "dans", "de", "des", "du", "elle",
    "en", "et", "est", "il", "la", "le", "les", "ou", "par", "pour", "sur", "un",
    "une", "y", "compris", "comprenant", "sous", "fourniture", "pose", "travaux", "mise", "place", "tout",
}

# Les variantes sont ramenées à un concept commun avant comparaison.
SYNONYMES = {
    "canalisation": "reseau", "canalisations": "reseau", "tuyau": "reseau", "tuyauterie": "reseau",
    "maconnerie": "mur", "cloison": "mur", "paroi": "mur",
    "excavation": "fouille", "terrassement": "fouille", "decapage": "fouille",
    "dallage": "dalle", "plancher": "dalle", "predalle": "dalle",
    "armatures": "acier", "ferraillage": "acier", "metallique": "acier",
    "menuiserie": "porte", "portail": "porte",
    "sanitaire": "plomberie", "evacuation": "plomberie",
    "courant": "electricite", "electrique": "electricite", "cablage": "electricite",
    "demolitions": "demolition", "demolir": "demolition",
    "peintures": "peinture", "revetement": "finition", "enduit": "finition",
}


def sans_accents(texte: str) -> str:
    return "".join(
        caractere for caractere in unicodedata.normalize("NFKD", texte)
        if not unicodedata.combining(caractere)
    )


def tokens_metier(texte: str) -> list[str]:
    mots = re.findall(r"[a-z0-9]+", sans_accents(texte.casefold()))
    resultat = []
    for mot in mots:
        if mot in MOTS_VIDES or len(mot) < 3 or mot.isdigit():
            continue
        if len(mot) > 5 and mot.endswith("s"):
            mot = mot[:-1]
        resultat.append(SYNONYMES.get(mot, mot))
    return resultat


def texte_element(element: dict) -> str:
    analyse = element.get("analyse_nlp") or {}
    return analyse.get("texte_normalise") or " ".join(
        [element.get("libelle", ""), element.get("donnees", {}).get("texte_source", "")]
    )


def aplatir_entites(element: dict) -> set[str]:
    entites = (element.get("analyse_nlp") or {}).get("entites", {})
    valeurs: set[str] = set()
    for categorie, liste in entites.items():
        if categorie == "mesures":
            continue
        for valeur in liste:
            brut = valeur.get("texte_source", "") if isinstance(valeur, dict) else str(valeur)
            valeurs.update(tokens_metier(brut))
    return valeurs


def calculer_idf(documents_tokens: list[list[str]]) -> dict[str, float]:
    total = len(documents_tokens)
    presence = Counter(mot for tokens in documents_tokens for mot in set(tokens))
    return {mot: math.log((1 + total) / (1 + nombre)) + 1 for mot, nombre in presence.items()}


def vecteur_tfidf(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    compte = Counter(tokens)
    maximum = max(compte.values(), default=1)
    return {mot: (nombre / maximum) * idf.get(mot, 1.0) for mot, nombre in compte.items()}


def cosinus(a: dict[str, float], b: dict[str, float]) -> float:
    communs = set(a) & set(b)
    produit = sum(a[mot] * b[mot] for mot in communs)
    norme_a = math.sqrt(sum(v * v for v in a.values()))
    norme_b = math.sqrt(sum(v * v for v in b.values()))
    return produit / (norme_a * norme_b) if norme_a and norme_b else 0.0


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def niveau_score(score: float) -> str:
    if score >= 0.55:
        return "forte"
    if score >= 0.35:
        return "moyenne"
    if score >= 0.18:
        return "faible"
    return "insuffisante"


def calculer_candidat(dqe: dict, cctp: dict, idf: dict[str, float]) -> dict:
    td, tc = tokens_metier(texte_element(dqe)), tokens_metier(texte_element(cctp))
    ed, ec = aplatir_entites(dqe), aplatir_entites(cctp)
    lexicale = cosinus(vecteur_tfidf(td, idf), vecteur_tfidf(tc, idf))
    entites = jaccard(ed, ec)
    mots_communs = sorted(set(td) & set(tc), key=lambda m: idf.get(m, 0), reverse=True)
    couverture = len(set(td) & set(tc)) / max(1, len(set(td)))
    score = min(1.0, 0.65 * lexicale + 0.25 * entites + 0.10 * couverture)
    return {
        "score": round(score, 4), "niveau": niveau_score(score),
        "similarite_lexicale": round(lexicale, 4),
        "similarite_entites": round(entites, 4),
        "mots_techniques_communs": mots_communs[:10],
        "entites_communes": sorted(ed & ec),
        "cctp": {
            "fichier_source": cctp["fichier_source"], "page": cctp.get("page"),
            "section": cctp.get("donnees", {}).get("section"),
            "libelle": cctp.get("libelle", ""),
            "texte_source": cctp.get("donnees", {}).get("texte_source", ""),
        },
    }


def rapprocher(elements: list[dict], nombre_candidats: int = 3, seuil: float = 0.18) -> dict:
    cctp = [e for e in elements if e.get("type_document") == "CCTP"]
    dqe = [e for e in elements if e.get("type_document") == "DQE"]
    tous_tokens = [tokens_metier(texte_element(e)) for e in cctp + dqe]
    idf = calculer_idf(tous_tokens)
    rapprochements = []
    cctp_retrouves: set[tuple] = set()
    for poste in dqe:
        candidats = [calculer_candidat(poste, prescription, idf) for prescription in cctp]
        candidats.sort(key=lambda c: c["score"], reverse=True)
        retenus = [c for c in candidats[:nombre_candidats] if c["score"] >= seuil]
        for candidat in retenus:
            cctp_retrouves.add((candidat["cctp"]["fichier_source"], candidat["cctp"]["page"], candidat["cctp"]["libelle"]))
        meilleur = retenus[0] if retenus else None
        rapprochements.append({
            "dqe": {
                "fichier_source": poste["fichier_source"], "page": poste.get("page"),
                "numero_poste": poste.get("donnees", {}).get("numero_poste"),
                "libelle": poste.get("libelle", ""), "unite": poste.get("donnees", {}).get("unite"),
                "texte_source": poste.get("donnees", {}).get("texte_source", ""),
            },
            "statut": "candidat_trouve" if meilleur else "sans_correspondance",
            "validation_humaine": "a_valider" if meilleur else "non_requise",
            "candidats": retenus,
        })
    prescriptions_sans_poste = [
        {"fichier_source": e["fichier_source"], "page": e.get("page"),
         "section": e.get("donnees", {}).get("section"), "libelle": e.get("libelle", ""),
         "texte_source": e.get("donnees", {}).get("texte_source", "")}
        for e in cctp
        if (e["fichier_source"], e.get("page"), e.get("libelle", "")) not in cctp_retrouves
    ]
    return {
        "version": "1.0", "methode": "tfidf_entites_lexique_btp_explicable",
        "avertissement": "Les PDF du corpus peuvent appartenir à des projets différents. Toute correspondance doit être validée par un technicien.",
        "statistiques": {
            "postes_dqe": len(dqe), "prescriptions_cctp": len(cctp),
            "postes_avec_candidat": sum(r["statut"] == "candidat_trouve" for r in rapprochements),
            "postes_sans_correspondance": sum(r["statut"] == "sans_correspondance" for r in rapprochements),
            "prescriptions_sans_poste": len(prescriptions_sans_poste),
        },
        "rapprochements": rapprochements,
        "prescriptions_sans_poste": prescriptions_sans_poste,
    }


def main() -> None:
    elements = json.loads(ENTREE.read_text(encoding="utf-8"))
    resultat = rapprocher(elements)
    SORTIE.write_text(json.dumps(resultat, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 68)
    print("RAPPROCHEMENT EXPLICABLE CCTP - DQE")
    print("=" * 68)
    for cle, valeur in resultat["statistiques"].items():
        print(f"{cle} : {valeur}")
    print(f"Résultat : {SORTIE}")


if __name__ == "__main__":
    main()
