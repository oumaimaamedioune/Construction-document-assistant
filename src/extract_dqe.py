"""Extraction multi-fichiers des lignes de DQE, BPU et DPGF au format PDF."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

import pdfplumber


RACINE_PROJET = Path(__file__).resolve().parents[1]
DOSSIER_DQE = RACINE_PROJET / "data" / "DQE"
FICHIER_SORTIE = RACINE_PROJET / "resultats_dqe.json"

UNITES_VALIDES = {
    "m", "m2", "m²", "m3", "m³", "ml", "kg", "t", "u", "ens", "ff",
    "fft", "forfait", "h", "j", "jour", "lot", "unité", "unite",
}
POSTE_PATTERN = re.compile(r"^(?:\d+(?:[.\-]\d+)*|[IVXLCDM]+)$", re.IGNORECASE)
NOMBRE_SIMPLE = re.compile(r"^\d+(?:[.,]\d+)?$")
SEUIL_FUSION_NOMBRE = 6


def nettoyer_nombre(valeur: str | None) -> float | None:
    if valeur is None:
        return None
    texte = str(valeur).strip().replace(" ", "").replace("\xa0", "")
    texte = re.sub(r"[^\d,.]", "", texte).replace(",", ".")
    try:
        return float(texte) if texte else None
    except ValueError:
        return None


def fusionner_nombres_coupes(mots_tries: list[dict]) -> list[dict]:
    """Recolle les groupes tels que ``300`` + ``000`` lorsqu'ils sont proches."""
    if not mots_tries:
        return []
    resultat = [dict(mots_tries[0])]
    for courant_original in mots_tries[1:]:
        courant = dict(courant_original)
        precedent = resultat[-1]
        ecart = courant["x0"] - precedent["x1"]
        if (
            NOMBRE_SIMPLE.fullmatch(precedent["text"])
            and courant["text"].isdigit()
            and 0 <= ecart < SEUIL_FUSION_NOMBRE
        ):
            precedent["text"] += courant["text"]
            precedent["x1"] = courant["x1"]
        else:
            resultat.append(courant)
    return resultat


def regrouper_mots_en_lignes(mots: list[dict], tolerance: float = 3) -> list[list[dict]]:
    lignes: list[list[dict]] = []
    ligne_courante: list[dict] = []
    top_courant: float | None = None
    for mot in sorted(mots, key=lambda m: (round(m["top"]), m["x0"])):
        if top_courant is None or abs(mot["top"] - top_courant) <= tolerance:
            ligne_courante.append(mot)
            if top_courant is None:
                top_courant = mot["top"]
        else:
            lignes.append(ligne_courante)
            ligne_courante = [mot]
            top_courant = mot["top"]
    if ligne_courante:
        lignes.append(ligne_courante)
    return lignes


def analyser_ligne(mots_ligne: list[dict]) -> dict | None:
    mots = fusionner_nombres_coupes(sorted(mots_ligne, key=lambda m: m["x0"]))
    textes = [mot["text"] for mot in mots]
    if not textes:
        return None

    numero_poste = textes[0] if POSTE_PATTERN.fullmatch(textes[0]) else None
    reste = textes[1:] if numero_poste else textes[:]

    unite = None
    index_unite = None
    for index, texte in enumerate(reste):
        if texte.strip(".").casefold() in UNITES_VALIDES:
            unite = texte
            index_unite = index
            break

    nombres: list[str] = []
    index_nombres: list[int] = []
    for index in range(len(reste) - 1, -1, -1):
        if NOMBRE_SIMPLE.fullmatch(reste[index]):
            nombres.insert(0, reste[index])
            index_nombres.insert(0, index)
        elif nombres:
            break

    quantite = prix_unitaire = prix_total = None
    if len(nombres) >= 3:
        quantite, prix_unitaire, prix_total = nombres[-3:]
    elif len(nombres) == 2:
        quantite, prix_unitaire = nombres
    elif len(nombres) == 1:
        quantite = nombres[0]

    exclusions = set(index_nombres)
    if index_unite is not None:
        exclusions.add(index_unite)
    designation = " ".join(
        texte for index, texte in enumerate(reste) if index not in exclusions
    ).strip()

    return {
        "numero_poste": numero_poste,
        "designation": designation,
        "unite": unite,
        "quantite": nettoyer_nombre(quantite),
        "prix_unitaire": nettoyer_nombre(prix_unitaire),
        "prix_total": nettoyer_nombre(prix_total),
        "texte_source": " ".join(textes),
    }


def statut_controle(poste: dict) -> str:
    """Contrôle la cohérence Q × PU = total sans inventer les valeurs absentes."""
    quantite = poste["quantite"]
    prix_unitaire = poste["prix_unitaire"]
    prix_total = poste["prix_total"]
    if quantite is None or prix_unitaire is None or prix_total is None:
        return "incomplet"
    attendu = quantite * prix_unitaire
    tolerance = max(1.0, abs(prix_total) * 0.005)
    return "valide" if math.isclose(attendu, prix_total, abs_tol=tolerance) else "a_verifier"


def est_ligne_total(designation: str) -> bool:
    texte = designation.casefold()
    return any(mot in texte for mot in ("sous total", "sous-total", "total général", "total general"))


DEBUT_DESIGNATION = re.compile(
    r"^(?:installation|transport|nettoyage|fouille|remblais?|béton|fondation|mur(?:et)?|"
    r"baie|perron|enduit|chape|tableaux?|couverture|amarrage|faux plafond|planches?|"
    r"fourniture|badigeon|peinture|plans?)\b",
    re.IGNORECASE,
)


def segmenter_designations(texte: str, nombre_attendu: int) -> list[str]:
    """Sépare les désignations regroupées dans une grande cellule de tableau."""
    lignes = [" ".join(ligne.split()) for ligne in str(texte or "").splitlines() if ligne.strip()]
    segments: list[str] = []
    for ligne in lignes:
        lettres = "".join(caractere for caractere in ligne if caractere.isalpha())
        if not segments and lettres and lettres == lettres.upper():
            continue
        if DEBUT_DESIGNATION.match(ligne):
            segments.append(ligne)
        elif segments:
            segments[-1] = f"{segments[-1]} {ligne}"
        # Une ligne de titre de lot placée avant le premier poste est ignorée.
    return segments if len(segments) == nombre_attendu else []


def decouper_colonne(cellule, nombre: int) -> list:
    valeurs = [" ".join(v.split()) for v in str(cellule or "").splitlines() if v.strip()]
    return (valeurs + [None] * nombre)[:nombre]


def analyser_tableau_devis_standard(
    tableau: list[list], numero_page: int, nom_fichier: str
) -> list[dict] | None:
    """Analyse un devis classique dont l'en-tête peut être précédé d'informations client.

    Exemple : Désignation | Quantité | Prix unitaire | Total. L'unité est
    facultative, contrairement aux DQE techniques numérotés.
    """
    index_entete = None
    colonnes: dict[str, int] = {}
    for index, ligne in enumerate(tableau):
        cellules = [" ".join(str(cellule or "").split()).casefold() for cellule in ligne]
        for position, cellule in enumerate(cellules):
            if "désignation" in cellule or "designation" in cellule:
                colonnes["designation"] = position
            elif "quantité" in cellule or "quantite" in cellule or "qté" in cellule:
                colonnes["quantite"] = position
            elif "prix unitaire" in cellule:
                colonnes["prix_unitaire"] = position
            elif "total" in cellule:
                colonnes["prix_total"] = position
            elif cellule in UNITES_VALIDES or "unité" in cellule or "unite" in cellule:
                colonnes["unite"] = position
        if {"designation", "quantite", "prix_unitaire", "prix_total"} <= colonnes.keys():
            index_entete = index
            break
        colonnes.clear()

    if index_entete is None:
        return None

    postes: list[dict] = []
    for numero_ligne, ligne in enumerate(tableau[index_entete + 1 :], start=1):
        cellules = list(ligne)

        def cellule(nom: str):
            position = colonnes.get(nom)
            return cellules[position] if position is not None and position < len(cellules) else None

        designation = " ".join(str(cellule("designation") or "").split())
        if not designation or est_ligne_total(designation):
            continue
        quantite = nettoyer_nombre(cellule("quantite"))
        prix_unitaire = nettoyer_nombre(cellule("prix_unitaire"))
        prix_total = nettoyer_nombre(cellule("prix_total"))
        if quantite is None or prix_unitaire is None or prix_total is None:
            continue

        unite_brute = cellule("unite")
        poste = {
            "numero_poste": str(numero_ligne),
            "designation": designation,
            "unite": " ".join(str(unite_brute).split()) if unite_brute else None,
            "quantite": quantite,
            "prix_unitaire": prix_unitaire,
            "prix_total": prix_total,
            "texte_source": " ".join(
                str(valeur) for valeur in ligne if valeur not in (None, "")
            ).replace("\n", " "),
            "page": numero_page,
            "fichier_source": nom_fichier,
        }
        poste["controle_calcul"] = statut_controle(poste)
        postes.append(poste)
    return postes


def analyser_tableau(page, numero_page: int, nom_fichier: str) -> list[dict] | None:
    """Exploite directement les cellules lorsque le PDF possède de vraies bordures.

    ``None`` signifie qu'aucun tableau DQE reconnu n'est présent et déclenche
    alors l'ancienne reconstruction par position des mots.
    """
    tableaux = page.extract_tables() or []
    for tableau in tableaux:
        if tableau:
            postes_devis = analyser_tableau_devis_standard(tableau, numero_page, nom_fichier)
            if postes_devis is not None:
                return postes_devis

    tableau_dqe = None
    for tableau in tableaux:
        if not tableau:
            continue
        entete = " ".join(str(cell or "") for cell in tableau[0]).casefold()
        entete_reconnue = (
            "désignation" in entete
            and ("unité" in entete or "unit" in entete)
            and ("qté" in entete or "qtés" in entete)
        )
        # Les pages suivantes répètent les mêmes six colonnes sans répéter
        # nécessairement l'en-tête. La présence de plusieurs numéros dans la
        # première colonne permet de reconnaître cette continuation.
        continuation_reconnue = any(
            len(ligne) >= 6
            and sum(
                bool(POSTE_PATTERN.fullmatch(v.strip()))
                and not bool(re.fullmatch(r"[IVXLCDM]+", v.strip(), re.IGNORECASE))
                for v in str(ligne[0] or "").splitlines()
            ) >= 2
            for ligne in tableau
        )
        if entete_reconnue or continuation_reconnue:
            tableau_dqe = tableau
            break
    if tableau_dqe is None:
        return None

    postes: list[dict] = []
    for cellules in tableau_dqe[1:]:
        cellules = list(cellules) + [None] * (6 - len(cellules))
        numero, designation, unite, quantite, prix_unitaire, prix_total = cellules[:6]
        # Certains PDF n'ont pas de ligne horizontale entre chaque poste :
        # plusieurs numéros et valeurs sont alors regroupés dans une cellule.
        numeros_groupes = [
            valeur for valeur in str(numero or "").splitlines()
            if POSTE_PATTERN.fullmatch(valeur.strip())
            and not re.fullmatch(r"[IVXLCDM]+", valeur.strip(), re.IGNORECASE)
        ]
        if numeros_groupes and "\n" in str(numero or ""):
            designations = segmenter_designations(designation, len(numeros_groupes))
            if not designations:
                continue
            unites = decouper_colonne(unite, len(numeros_groupes))
            quantites = decouper_colonne(quantite, len(numeros_groupes))
            prix_unitaires = decouper_colonne(prix_unitaire, len(numeros_groupes))
            prix_totaux = decouper_colonne(prix_total, len(numeros_groupes))
            for valeurs in zip(numeros_groupes, designations, unites, quantites, prix_unitaires, prix_totaux):
                num, des, uni, qte, pu, total = valeurs
                poste = {
                    "numero_poste": num.strip(), "designation": des, "unite": uni,
                    "quantite": nettoyer_nombre(qte), "prix_unitaire": nettoyer_nombre(pu),
                    "prix_total": nettoyer_nombre(total),
                    "texte_source": " ".join(str(v) for v in valeurs if v not in (None, "")),
                    "page": numero_page, "fichier_source": nom_fichier,
                }
                poste["controle_calcul"] = statut_controle(poste)
                postes.append(poste)
            continue

        numero = " ".join(str(numero or "").split()) or None
        designation = " ".join(str(designation or "").split())
        unite = " ".join(str(unite or "").split()) or None

        if not numero or not POSTE_PATTERN.fullmatch(numero):
            continue
        # Les chiffres romains sont des titres de lots, pas des postes chiffrés.
        if re.fullmatch(r"[IVXLCDM]+", numero, re.IGNORECASE):
            continue
        if not designation or est_ligne_total(designation):
            continue

        poste = {
            "numero_poste": numero,
            "designation": designation,
            "unite": unite,
            "quantite": nettoyer_nombre(quantite),
            "prix_unitaire": nettoyer_nombre(prix_unitaire),
            "prix_total": nettoyer_nombre(prix_total),
            "texte_source": " ".join(
                str(v) for v in (numero, designation, unite, quantite, prix_unitaire, prix_total) if v not in (None, "")
            ),
            "page": numero_page,
            "fichier_source": nom_fichier,
        }
        poste["controle_calcul"] = statut_controle(poste)
        postes.append(poste)
    return postes


def analyser_pdf(chemin_pdf: Path) -> list[dict]:
    postes: list[dict] = []
    continuation: list[str] = []

    with pdfplumber.open(chemin_pdf) as pdf:
        for numero_page, page in enumerate(pdf.pages, start=1):
            postes_tableau = analyser_tableau(page, numero_page, chemin_pdf.name)
            if postes_tableau is not None:
                postes.extend(postes_tableau)
                continuation.clear()
                continue

            for mots_ligne in regrouper_mots_en_lignes(page.extract_words()):
                ligne = analyser_ligne(mots_ligne)
                if not ligne or not ligne["designation"]:
                    continue

                # Une ligne descriptive sans numéro, unité ou prix est souvent
                # la première moitié d'un poste coupé par la mise en page.
                if (
                    ligne["numero_poste"] is None
                    and ligne["unite"] is None
                    and ligne["prix_unitaire"] is None
                ):
                    continuation.append(ligne["texte_source"])
                    continue

                if continuation and ligne["numero_poste"]:
                    prefixe = " ".join(continuation)
                    ligne["designation"] = f"{prefixe} {ligne['designation']}".strip()
                    ligne["texte_source"] = f"{prefixe} {ligne['texte_source']}".strip()
                    continuation.clear()

                a_une_valeur = ligne["quantite"] is not None or ligne["prix_unitaire"] is not None
                if not a_une_valeur or est_ligne_total(ligne["designation"]):
                    continue

                ligne["page"] = numero_page
                ligne["fichier_source"] = chemin_pdf.name
                ligne["controle_calcul"] = statut_controle(ligne)
                postes.append(ligne)

    return postes


def executer_extraction() -> list[dict]:
    fichiers_pdf = sorted(DOSSIER_DQE.glob("*.pdf"), key=lambda p: p.name.casefold())
    if not fichiers_pdf:
        raise FileNotFoundError(f"Aucun PDF trouvé dans {DOSSIER_DQE}")

    print("=" * 72)
    print("EXTRACTION DQE/BPU/DPGF - TRAITEMENT MULTI-FICHIERS")
    print("=" * 72)
    print(f"Dossier : {DOSSIER_DQE}")
    print(f"Nombre de PDF : {len(fichiers_pdf)}\n")

    tous_les_postes: list[dict] = []
    erreurs: list[tuple[str, str]] = []
    for chemin_pdf in fichiers_pdf:
        try:
            postes = analyser_pdf(chemin_pdf)
            tous_les_postes.extend(postes)
            controles = Counter(poste["controle_calcul"] for poste in postes)
            print(f"[OK] {chemin_pdf.name}: {len(postes)} ligne(s) - {dict(controles)}")
        except Exception as exc:
            erreurs.append((chemin_pdf.name, str(exc)))
            print(f"[ERREUR] {chemin_pdf.name}: {exc}")

    with FICHIER_SORTIE.open("w", encoding="utf-8") as fichier:
        json.dump(tous_les_postes, fichier, ensure_ascii=False, indent=2)

    controles_globaux = Counter(p["controle_calcul"] for p in tous_les_postes)
    print(f"\nTotal : {len(tous_les_postes)} ligne(s)")
    print(f"Contrôles : {dict(controles_globaux)}")
    print(f"Fichiers en erreur : {len(erreurs)}")
    print(f"Résultat : {FICHIER_SORTIE}")
    return tous_les_postes


if __name__ == "__main__":
    executer_extraction()
