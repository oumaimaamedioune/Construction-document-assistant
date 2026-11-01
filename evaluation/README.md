# Évaluation des extractions

Ce dossier utilise uniquement les PDF déjà validés présents dans `data/`.

## Procédure

1. Ouvrir le PDF indiqué par `fichier_source` à la page indiquée.
2. Lire `texte_source` et vérifier les valeurs dans la page originale.
3. Renseigner `attendu` avec la bonne réponse, même si la prédiction est fausse.
4. Ajouter une explication courte dans `commentaire` en cas d'erreur.
5. Remplacer `a_annoter` par `valide` seulement après la vérification.

Une valeur absente du document doit rester `null`. Pour les entités CCTP, utiliser
une liste vide lorsqu'aucune valeur de cette catégorie n'est attendue.

Les prédictions ne doivent jamais être copiées automatiquement dans `attendu` :
cela fausserait les métriques.

## Commandes

Depuis la racine du projet :

```powershell
python src/preparer_evaluation.py
python src/evaluer_extractions.py
```

Le premier script ne remplace jamais un fichier d'annotation existant.
