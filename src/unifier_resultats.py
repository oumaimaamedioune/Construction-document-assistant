import json
from pathlib import Path

# ============================================
# CHEMINS DES FICHIERS DÉJÀ GÉNÉRÉS
# ============================================
racine_projet = Path(__file__).resolve().parents[1]
chemin_cctp = racine_projet / "resultats_extraction.json"
chemin_dqe = racine_projet / "resultats_dqe.json"
chemin_sortie = racine_projet / "resultats_unifies.json"

resultats_unifies = []

# ============================================
# 1. TRANSFORMER LES RÉSULTATS CCTP
# ============================================
# Rappel : resultats_extraction.json est organisé comme ceci :
# { "Béton": [ {page, section, materiau, texte_source, entites}, ... ], "Acier": [...] }
if chemin_cctp.exists():
    with chemin_cctp.open('r', encoding='utf-8') as f:
        donnees_cctp = json.load(f)

    for materiau, blocs in donnees_cctp.items():
        for bloc in blocs:
            resultats_unifies.append({
                "type_document": "CCTP",
                "fichier_source": bloc.get("fichier_source", "CCTP_inconnu"),
                "page": bloc.get("page"),
                "categorie": "materiau",
                "libelle": bloc.get("materiau", materiau),
                "donnees": {
                    "section": bloc.get("section"),
                    "texte_source": bloc.get("texte_source"),
                    **bloc.get("entites", {})
                }
            })
    print(f"CCTP : {sum(len(v) for v in donnees_cctp.values())} éléments intégrés")
else:
    print(f"Attention : {chemin_cctp} introuvable, on ignore le CCTP pour cette fois")

# ============================================
# 2. TRANSFORMER LES RÉSULTATS DQE
# ============================================
# Rappel : resultats_dqe.json est une simple liste de postes
if chemin_dqe.exists():
    with chemin_dqe.open('r', encoding='utf-8') as f:
        donnees_dqe = json.load(f)

    for poste in donnees_dqe:
        resultats_unifies.append({
            "type_document": "DQE",
            "fichier_source": poste.get("fichier_source", "DQE_inconnu"),
            "page": poste.get("page"),
            "categorie": "poste_devis",
            "libelle": poste.get("designation"),
            "donnees": {
                "numero_poste": poste.get("numero_poste"),
                "unite": poste.get("unite"),
                "quantite": poste.get("quantite"),
                "prix_unitaire": poste.get("prix_unitaire"),
                "prix_total": poste.get("prix_total"),
                "controle_calcul": poste.get("controle_calcul"),
                "texte_source": poste.get("texte_source"),
            }
        })
    print(f"DQE : {len(donnees_dqe)} éléments intégrés")
else:
    print(f"Attention : {chemin_dqe} introuvable, on ignore le DQE pour cette fois")

# ============================================
# 3. EXPORT DU RÉSULTAT UNIFIÉ
# ============================================
with chemin_sortie.open('w', encoding='utf-8') as f:
    json.dump(resultats_unifies, f, ensure_ascii=False, indent=2)

print(f"\nTotal : {len(resultats_unifies)} éléments unifiés")
print(f"Résultat exporté dans : {chemin_sortie}")
