# Assistant Intelligent d'Analyse de Documents de Chantier

## Présentation du projet

Développement d'un assistant intelligent destiné à automatiser l'analyse et l'exploitation des documents de chantier.

Le système repose sur un pipeline de traitement automatique du langage naturel (NLP), intégrant le modèle de langage **Qwen3 1.7B** exécuté localement via **Ollama**, et associé à un chatbot documentaire interactif.

Cette solution permet d'extraire des informations pertinentes à partir de documents de chantier, de faciliter leur consultation et de répondre aux questions des utilisateurs en s'appuyant sur leur contenu, tout en privilégiant un traitement local des données.

## Fonctionnalités principales

- Extraction intelligente d'informations : identification automatique des entités et des informations clés contenues dans les documents de chantier.
- Pipeline NLP local  traitement des documents à l'aide de modèles exécutés localement, sans dépendance à des services d'IA dans le cloud.
- Chatbot documentaire : interaction en langage naturel avec les documents pour faciliter la recherche et l'accès à l'information.
- Interface interactive : application web moderne et intuitive développée avec Streamlit.

## Technologies utilisées


 Langage de programmation: Python 
 Modèle de langage (LLM): Qwen3 1.7B
 Exécution du modèle : Ollama 
 Interface utilisateur :Streamlit
 Intelligence artificielle: NLP, extraction d'entités, LLM 


## Lancer l'application

```bash
streamlit run src/app.py
```

## Objectifs du projet

- Automatiser l'analyse des documents de chantier.
- Faciliter l'extraction et la consultation des informations pertinentes.
- Exploiter les capacités des grands modèles de langage (LLM) dans un contexte métier spécifique.
- Proposer une solution d'intelligence artificielle privilégiant le traitement local et la confidentialité des données.





