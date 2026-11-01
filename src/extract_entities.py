import pdfplumber
import re
import os

# ============================================
# CHEMIN VERS TON DOSSIER CCTP
# ============================================
dossier_cctp = r"C:\Users\oumay\Desktop\Prjt_stage_menara\data\CCTP"
# On prend le premier PDF trouvé
fichiers_pdf = [f for f in os.listdir(dossier_cctp) if f.lower().endswith('.pdf')]
if not fichiers_pdf:
    print("ERREUR : Aucun PDF trouvé dans le dossier CCTP !")
    exit()

chemin_pdf = os.path.join(dossier_cctp, fichiers_pdf[0])
print(f"Fichier analysé : {fichiers_pdf[0]}")
print("=" * 70)

# ============================================
# PATTERNS DE RECHERCHE (Regex)
# ============================================
patterns = {
    "RESISTANCE (MPa)": r'\b\d{1,3}\s*MPa\b',
    "CLASSE BETON": r'\bC\d{2,3}/\d{2,3}\b',
    "NORME": r'\b(?:NM|EN|DTU|NF|ISO|ASTM)\s*[A-Z]?\d[\d\.\-]*(?:\s*\d{2,3})?\b',
    "DIMENSION": r'\b\d{1,4}\s*[x×]\s*\d{1,4}(?:\s*[x×]\s*\d{1,4})?\s*(?:cm|mm|m)?\b',
    "DOSAGE (kg/m3)": r'\b\d{2,4}\s*kg/m[³3]\b',
    "DIAMETRE": r'[ØøO]\s*\d{1,3}\s*(?:mm|cm)?',
    "ACIER (FeE)": r'\bFeE\s*\d+\b',
    "EPAISSEUR": r'\b\d{1,3}\s*(?:cm|mm)\b',
    "GRAMMAGE": r'\b\d{2,4}\s*g/m[²2]\b',
    "POURCENTAGE": r'\b\d{1,3}\s*%\b',
}

with pdfplumber.open(chemin_pdf) as pdf:
    total_trouves = 0
    
    for page_num in range(len(pdf.pages)):
        texte = pdf.pages[page_num].extract_text()
        if not texte:
            continue
            
        resultats_page = []
        page_a_des_resultats = False
        
        for entite, pattern in patterns.items():
            matches = re.findall(pattern, texte, re.IGNORECASE)
            if matches:
                page_a_des_resultats = True
                uniques = list(dict.fromkeys(matches))
                resultats_page.append(f"  [{entite}] : {', '.join(uniques[:10])}")
                total_trouves += len(uniques)
        
        if page_a_des_resultats:
            print(f"\n--- PAGE {page_num + 1} ---")
            for r in resultats_page:
                print(r)

print("\n" + "=" * 70)
print(f"Extraction terminée. {total_trouves} entités techniques trouvées au total.")