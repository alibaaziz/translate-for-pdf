# Traducteur de Documents PDF Hors-Ligne (PyQt6 + Meta NLLB-200)

Application de bureau en Python avec interface graphique moderne **PyQt6** pour la traduction hors-ligne de documents PDF avec **conservation absolue de la mise en page originale**.

---

## Fonctionnalités Principales

- **100% Hors-Ligne & Qualité SOTA** :
  - Propulsé exclusivement par le modèle universel **Meta NLLB-200 (INT8)** via le moteur haute performance **CTranslate2**.
  - Traduction directe Any-to-Any entre 200 langues (sans passage intermédiaire par l'anglais).
  - Détection automatique de la langue source via langdetect.
- **Accélération Matérielle NVIDIA CUDA (GPU)** :
  - Exploitation des cœurs Tensor et de la mémoire VRAM via CUDA (int8_float16) pour une vitesse maximale (~15 ms par unité visuelle).
  - Bascule transparente automatique sur le processeur (CPU INT8) si aucun GPU NVIDIA n'est détecté.
- **Conservation Absolue de la Mise en Page & Rendu Typographique** :
  - **Images & Photos** : 100% des images raster sont conservées sans altération ni compression dégradante (PDF_REDACT_IMAGE_NONE).
  - **Graphiques & Formes** : Tracés vectoriels, diagrammes complexes, courbes, tableaux et arrière-plans conservés intacts (PDF_REDACT_LINE_ART_NONE).
  - **Typographie TrueType & Unicode** : Restitution fidèle des polices Serif (Times New Roman), Sans-Serif (Arial) et Monospace (Courier), avec préservation intégrale des styles (Gras, Italique), des couleurs et des caractères accentués (é, è, à, ç, œ, ’).
  - **Auto-Fit Précis sans Sur-impression** : Mesure sur page virtuelle (ender_mode=3) pour ajuster la taille de police au demi-point près, sans déborder sur les lignes adjacentes ni sur les images.
  - **Support Complet de l'Arabe (RTL & Cursif)** :
    - Lettres arabes connectées naturellement (formes initiale, médiane, finale, isolée via rabic-reshaper).
    - Algorithme BiDi mot par mot respectant le flux de lecture de droite à gauche sans inversion verticale des lignes.
- **Interface Graphique Ergonomique** :
  - Double visionneuse synchronisée côte à côte (Document original vs Document traduit).
  - Règle de scroll verticale, navigation par page, zoom dynamique et mode ajuster à la largeur.
  - Multi-threading asynchrone (QThread) : interface toujours fluide pendant la traduction.

---

## Installation & Dépendances

Nécessite Python 3.10 ou supérieur :

`ash
pip install -r requirements.txt
`

---

## Lancement Rapide

Double-cliquez sur un.bat ou lancez en ligne de commande :

`ash
python main.py
`

---

## Création de l'Exécutable Autonome (PC sans Python)

Pour compiler l'application en un exécutable autonome .exe (incluant le modèle NLLB-200 et les bibliothèques CUDA) :

`ash
python build_exe.py
`

L'exécutable et ses dépendances seront générés dans le dossier dist/TraducteurPDF/TraducteurPDF.exe.

---

## Structure du Code

- main.py : Point d'entrée de l'application avec configuration High-DPI.
- main_window.py : Fenêtre principale PyQt6, barres d'outils, raccourcis et gestion des événements.
- ui_components.py : Visionneuse PDF synchronisée, règle de défilement, widgets de page et worker asynchrone (QThread).
- pdf_processor.py : Moteur PyMuPDF pour l'extraction des unités visuelles, détection de colonnes, rédaction chirurgicale et réinsertion typographique.
- 	ranslator_engine.py : Moteur de traduction Meta NLLB-200 (CTranslate2), gestion des DLLs CUDA, batching multi-phrases et cache.
- config.py : Configuration des langues, chemins modèles et polices système.
- uild_exe.py : Script automatisé de compilation PyInstaller autonome avec packaging CUDA.
- equirements.txt : Liste des paquets Python requis.
