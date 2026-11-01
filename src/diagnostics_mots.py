import pdfplumber
import os

# ============================================
# CONFIGURATION - identique à extract_dqe.py
# ============================================
dossier_dqe = r"C:\Users\oumay\Desktop\Prjt_stage_menara\data\DQE"
NOM_FICHIER_CIBLE = "document_Devis.pdf"

chemin_pdf = os.path.join(dossier_dqe, NOM_FICHIER_CIBLE)

# Numéro de la page à inspecter (1 = première page)
PAGE_A_INSPECTER = 1

with pdfplumber.open(chemin_pdf) as pdf:
    page = pdf.pages[PAGE_A_INSPECTER - 1]
    mots = page.extract_words()

    # Regrouper les mots par ligne (même logique que le script principal)
    mots_tries = sorted(mots, key=lambda m: (round(m['top']), m['x0']))

    print("=" * 90)
    print(f"MOTS DÉTECTÉS SUR LA PAGE {PAGE_A_INSPECTER}")
    print("=" * 90)
    print(f"{'TEXTE':<25} {'x0':>8} {'x1':>8} {'top':>8}")
    print("-" * 90)

    for m in mots_tries:
        print(f"{m['text']:<25} {m['x0']:>8.1f} {m['x1']:>8.1f} {m['top']:>8.1f}")

print("\nCopie-colle TOUT ce résultat (ou au moins les 30-40 premières lignes)")
print("pour qu'on puisse voir exactement comment les mots '1.1', 'Ens.', '1', '300', '000' etc.")
print("sont positionnés.")