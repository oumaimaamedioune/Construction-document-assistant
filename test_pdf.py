import pdfplumber
import os

# ============================================
# ADAPTE CE CHEMIN selon ton PC
# ============================================

chemin_pdf = r"C:\Users\oumay\Desktop\Prjt_stage_menara\data\CCTP\CCTP LOT 01B GROS OEUVRE MACONNERIE STRUCTURE METALLIQUE.pdf"


print("=" * 60)
print("TEST D'EXTRACTION DE TEXTE AVEC PDFPLUMBER")
print("=" * 60)

try:
    with pdfplumber.open(chemin_pdf) as pdf:
        total_pages = len(pdf.pages)
        print(f"\nNombre total de pages : {total_pages}")
        
        # On lit les 3 premières pages pour tester
        for i in range(20, 23):  # Pages 21 à 23 (index 20, 21, 22)
            page = pdf.pages[i]
            texte = page.extract_text()
            
            print(f"\n{'='*60}")
            print(f"PAGE {i+1}")
            print(f"{'='*60}")
            
            if texte:
                # On affiche les 1500 premiers caractères
                print(texte[:1500])
                print(f"\n... (suite de la page non affichée, {len(texte)} caractères au total)")
            else:
                print("[ATTENTION] Aucun texte trouvé sur cette page !")
                print("-> Cette page est peut-être une image/scan.")
                
except FileNotFoundError:
    print("ERREUR : Le fichier n'a pas été trouvé.")
    print("Vérifie que le chemin est correct.")
    print("Astuce : fais un clic droit sur le PDF -> Propriétés -> copie le chemin complet")
except Exception as e:
    print(f"ERREUR inattendue : {e}")