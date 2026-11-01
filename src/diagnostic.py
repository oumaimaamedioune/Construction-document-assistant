import pdfplumber
import re
import os

dossier_cctp = r"C:\Users\oumay\Desktop\Prjt_stage_menara\data\CCTP"
fichiers_pdf = [f for f in os.listdir(dossier_cctp) if f.lower().endswith('.pdf')]

# On analyse le premier fichier (Coupvray)
chemin_pdf = os.path.join(dossier_cctp, fichiers_pdf[0])

print(f"Document analysé : {fichiers_pdf[0]}")
print("=" * 70)

# Mots qu'on cherche dans les titres
MATERIAUX_CLES = [
    "béton", "beton", "acier", "aciers", "coffrage", "brique", "briques",
    "mortier", "enduit", "peinture", "étanchéité", "etancheite", "isolation",
    "plancher", "dalles", "voile", "murs", "maçonnerie", "maconnerie",
    "ferraillage", "armature", "armatures", "bois", "terrassement",
    "plomberie", "sanitaire", "électricité", "menuiserie", "gros oeuvre",
    "structure", "métallique", "metallique", "terrasse", "fondation",
    "assainissement", "revêtement", "clôture", "drainage", "tuyau"
]

print("\n--- 1. RECHERCHE DES SECTIONS AVEC MATÉRIAUX ---")
print("-" * 50)

sections_trouvees = 0

with pdfplumber.open(chemin_pdf) as pdf:
    for i in range(min(40, len(pdf.pages))):
        texte = pdf.pages[i].extract_text()
        if not texte:
            continue
        lignes = texte.split('\n')
        for ligne in lignes:
            ligne = ligne.strip()
            if not ligne:
                continue
            
            # Pattern : numéro + texte (ex: 2.5.1, 3.1, A.2, etc.)
            match = re.match(r'^(\d+(?:\.\d+)*|[A-Z]\.\d+)\s+(.+)', ligne)
            if match:
                numero = match.group(1)
                titre = match.group(2)
                titre_lower = titre.lower()
                
                for mat in MATERIAUX_CLES:
                    if mat in titre_lower:
                        print(f"[PAGE {i+1:2d}] {numero:8s} | {titre[:60]}")
                        sections_trouvees += 1
                        break

if sections_trouvees == 0:
    print("AUCUNE section avec mot-clé matériau trouvée.")
    print("\n--- 2. VOICI LES 20 PREMIÈRES LIGNES DU DOCUMENT ---")
    print("-" * 50)
    with pdfplumber.open(chemin_pdf) as pdf:
        texte = pdf.pages[0].extract_text()
        if texte:
            lignes = texte.split('\n')[:20]
            for j, ligne in enumerate(lignes, 1):
                print(f"{j:2d}. {ligne[:80]}")
    
    print("\n--- 3. VOICI QUELQUES TITRES DE SECTION DÉTECTÉS ---")
    print("-" * 50)
    with pdfplumber.open(chemin_pdf) as pdf:
        for i in range(min(20, len(pdf.pages))):
            texte = pdf.pages[i].extract_text()
            if not texte:
                continue
            lignes = texte.split('\n')
            for ligne in lignes:
                ligne = ligne.strip()
                if re.match(r'^(\d+(?:\.\d+)*|[A-Z]\.\d+)\s+(.+)', ligne):
                    print(f"[P{i+1}] {ligne[:80]}")
                    break  # Juste la première ligne de titre par page

print("\n" + "=" * 70)
print(f"Total sections matériaux trouvées : {sections_trouvees}")