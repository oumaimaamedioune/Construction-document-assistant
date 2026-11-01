"""Outils NLP locaux pour le vocabulaire technique du BTP.

Cette première couche ne dépend d'aucune API externe. Elle fournit des
résultats explicables : chaque entité reconnue provient d'un dictionnaire
métier ou d'un motif contrôlé (norme, unité ou propriété technique).
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict


VERSION_NLP = "1.0"

# Une forme canonique est associée aux variantes réellement rencontrées dans
# les CCTP et DQE. Le dictionnaire pourra être enrichi sans changer le moteur.
LEXIQUE_BTP = {
    "materiaux": {
        "béton": ("béton", "beton"),
        "béton armé": ("béton armé", "beton arme", "b.a.", "ba"),
        "acier": ("acier",),
        "mortier": ("mortier",),
        "ciment": ("ciment",),
        "PVC": ("pvc", "polychlorure de vinyle"),
        "PEHD": ("pehd", "polyéthylène haute densité"),
        "cuivre": ("cuivre",),
        "bois": ("bois",),
        "brique": ("brique", "briques"),
        "carrelage": ("carrelage",),
        "enduit": ("enduit",),
    },
    "ouvrages_equipements": {
        "canalisation": ("canalisation", "canalisations"),
        "réseau": ("réseau", "réseaux", "reseau", "reseaux"),
        "plancher": ("plancher", "planchers"),
        "dalle": ("dalle", "dalles"),
        "voile": ("voile", "voiles"),
        "poteau": ("poteau", "poteaux"),
        "fondation": ("fondation", "fondations"),
        "coffrage": ("coffrage", "coffrages"),
        "armature": ("armature", "armatures", "ferraillage"),
        "sanitaire": ("sanitaire", "sanitaires"),
    },
    "proprietes": {
        "hydrofugé": ("hydrofugé", "hydrofuge", "hydrofugée", "hydrofugee"),
    },
    "type_ciment": {
        "CPJ": ("cpj",),
    },
}

MOTIF_NORME = re.compile(
    r"\b(?:NF(?:\s+EN)?|NM|EN|ISO|DTU|ASTM)\s*[-:]?\s*[A-Z]?\d[\d.\-/]*(?:\s*[-:]\s*\d+)?\b",
    re.IGNORECASE,
)
MOTIF_CLASSE_BETON = re.compile(r"\bC\s*\d{2,3}\s*/\s*\d{2,3}\b", re.IGNORECASE)
MOTIF_RESISTANCE = re.compile(r"\b\d{1,3}(?:[.,]\d+)?\s*MPa\b", re.IGNORECASE)
MOTIF_DOSAGE = re.compile(r"\b\d{2,4}(?:[.,]\d+)?\s*kg\s*(?:/\s*m[³3]|de\s+ciment)\b", re.IGNORECASE)
MOTIF_DIAMETRE = re.compile(r"(?:Ø|ø|diam(?:è|e)tre\s*)\s*\d+(?:[.,]\d+)?\s*(?:mm|cm|m)\b", re.IGNORECASE)
MOTIF_EPAISSEUR = re.compile(
    r"(?:épaisseur|epaisseur|ép\.)\s*(?:minimale?\s*)?(?:de|à|:)?\s*\d+(?:[.,]\d+)?\s*(?:mm|cm|m)\b",
    re.IGNORECASE,
)
MOTIF_DIMENSION = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*[x×]\s*\d+(?:[.,]\d+)?(?:\s*[x×]\s*\d+(?:[.,]\d+)?)?\s*(?:mm|cm|m)?\b",
    re.IGNORECASE,
)

UNITES = {
    "m2": "m²", "m²": "m²", "m^2": "m²",
    "m3": "m³", "m³": "m³", "m^3": "m³",
    "ml": "ml", "m.l": "ml",
    "mm": "mm", "cm": "cm", "m": "m",
    "kg": "kg", "g": "g", "l": "L", "u": "u", "unité": "u", "unite": "u",
}
MOTIF_VALEUR_UNITE = re.compile(
    r"(?<![\w/])(?P<valeur>\d+(?:[.,]\d+)?)\s*(?P<unite>m\^?[23]|m[²³]|m\.l|ml|mm|cm|kg|g|l|u|unité|unite)\b",
    re.IGNORECASE,
)


def sans_accents(texte: str) -> str:
    """Produit une forme de comparaison, sans modifier le texte présenté."""
    return "".join(
        caractere for caractere in unicodedata.normalize("NFD", texte)
        if unicodedata.category(caractere) != "Mn"
    )


def nettoyer_texte(texte: str | None) -> str:
    """Nettoie les artefacts fréquents d'extraction PDF."""
    if not texte:
        return ""
    propre = unicodedata.normalize("NFKC", str(texte))
    propre = propre.replace("’", "'").replace("–", "-").replace("—", "-")
    propre = propre.replace("×", "x")
    propre = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", propre)
    propre = re.sub(r"[\r\n\t]+", " ", propre)
    return re.sub(r"\s+", " ", propre).strip()


def normaliser_unites(texte: str) -> tuple[str, list[dict]]:
    """Uniformise les unités et conserve valeur, unité et expression source."""
    mesures: list[dict] = []

    # NFKC transforme les exposants en chiffres simples. On rétablit d'abord
    # les unités composées afin que kg/m3 ne soit pas traité comme kg seul.
    texte = re.sub(r"\bkg\s*/\s*m(?:\^?3)\b", "kg/m³", texte, flags=re.IGNORECASE)
    texte = re.sub(r"\bg\s*/\s*m(?:\^?2)\b", "g/m²", texte, flags=re.IGNORECASE)

    def remplacer(match: re.Match) -> str:
        valeur_source = match.group("valeur")
        unite_source = match.group("unite")
        valeur = valeur_source.replace(",", ".")
        unite = UNITES[unite_source.casefold()]
        mesures.append({
            "valeur": float(valeur),
            "unite": unite,
            "texte_source": match.group(0),
        })
        return f"{valeur} {unite}"

    texte_normalise = MOTIF_VALEUR_UNITE.sub(remplacer, texte)
    mesures_uniques = []
    cles_vues = set()
    for mesure in mesures:
        cle = (mesure["valeur"], mesure["unite"], mesure["texte_source"].casefold())
        if cle not in cles_vues:
            mesures_uniques.append(mesure)
            cles_vues.add(cle)
    return texte_normalise, mesures_uniques


def _contient_variante(texte_comparable: str, variante: str) -> bool:
    comparable = sans_accents(variante).casefold()
    motif = rf"(?<!\w){re.escape(comparable)}(?!\w)"
    return re.search(motif, texte_comparable) is not None


def reconnaitre_vocabulaire(texte: str) -> dict[str, list[str]]:
    """Reconnaît le vocabulaire BTP et retourne les formes canoniques."""
    comparable = sans_accents(texte).casefold()
    trouvees: dict[str, list[str]] = {}
    for categorie, concepts in LEXIQUE_BTP.items():
        valeurs = [
            canonique
            for canonique, variantes in concepts.items()
            if any(_contient_variante(comparable, variante) for variante in variantes)
        ]
        if valeurs:
            trouvees[categorie] = valeurs
    return trouvees


def _valeurs_uniques(motif: re.Pattern, texte: str) -> list[str]:
    valeurs = [re.sub(r"\s+", " ", resultat.group(0)).strip() for resultat in motif.finditer(texte)]
    return list(dict.fromkeys(valeurs))


def analyser_texte(texte: str | None) -> dict:
    """Exécute la première analyse NLP métier sur un texte technique."""
    texte_nettoye = nettoyer_texte(texte)
    texte_normalise, mesures = normaliser_unites(texte_nettoye)
    entites: defaultdict[str, list] = defaultdict(list)

    for categorie, valeurs in reconnaitre_vocabulaire(texte_normalise).items():
        entites[categorie].extend(valeurs)

    motifs = {
        "normes": MOTIF_NORME,
        "classes_beton": MOTIF_CLASSE_BETON,
        "resistances": MOTIF_RESISTANCE,
        "dosages": MOTIF_DOSAGE,
        "diametres": MOTIF_DIAMETRE,
        "epaisseurs": MOTIF_EPAISSEUR,
        "dimensions": MOTIF_DIMENSION,
    }
    for categorie, motif in motifs.items():
        valeurs = _valeurs_uniques(motif, texte_normalise)
        if valeurs:
            entites[categorie].extend(valeurs)
    if mesures:
        entites["mesures"] = mesures

    return {
        "version": VERSION_NLP,
        "methode": "regles_et_lexique_btp",
        "texte_normalise": texte_normalise,
        "entites": dict(entites),
    }
