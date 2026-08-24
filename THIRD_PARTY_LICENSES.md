# Licences tierces — LouLLabs STT

LouLLabs STT est distribué sous licence **MIT** (voir [`LICENSE`](LICENSE)).
Il s'appuie sur des composants tiers, chacun sous sa propre licence, listés ci-dessous.
Ce document sert d'avis de licences (notice) pour la **distribution source** comme pour la
**distribution binaire** (l'exécutable produit par PyInstaller).

## Dépendances directes

| Composant | Rôle | Licence | Source |
|-----------|------|---------|--------|
| **faster-whisper** | Inference Whisper (CTranslate2) | MIT | https://github.com/SYSTRAN/faster-whisper |
| **CTranslate2** | Runtime d'inference | MIT | https://github.com/OpenNMT/CTranslate2 |
| **sounddevice** | Capture audio | MIT | https://github.com/spatialaudio/python-sounddevice |
| **PortAudio** (via sounddevice) | Backend audio | MIT | https://www.portaudio.com/ |
| **NumPy** | Calcul numérique | BSD-3-Clause | https://github.com/numpy/numpy |
| **pyperclip** | Presse-papier (mode optionnel) | BSD-3-Clause | https://github.com/asweigart/pyperclip |
| **ONNX Runtime** | VAD Silero (via faster-whisper) | MIT | https://github.com/microsoft/onnxruntime |
| **PyAV** (`av`) | Décodage audio (wrapper FFmpeg) | BSD-3-Clause | https://github.com/PyAV-Org/PyAV |
| **PySide6 / Qt** | Interface (overlay, tray, réglages) | **LGPL-3.0** | https://www.qt.io/ · https://code.qt.io/ |
| **FFmpeg** (embarqué via PyAV) | Bibliothèques de décodage | **LGPL-2.1-or-later** | https://ffmpeg.org/ |

## Modèle Whisper

Les poids du modèle Whisper (`large-v3-turbo` et autres tailles) sont publiés par
OpenAI sous licence **MIT** et téléchargés à la demande depuis le Hugging Face Hub.
Ils ne sont **pas** redistribués dans ce dépôt ni dans l'exécutable.
Source : https://github.com/openai/whisper · https://huggingface.co/

« Whisper » est une dénomination d'OpenAI, employée ici de manière purement
descriptive ; ce projet n'est ni affilié à, ni approuvé par OpenAI.

## Conformité LGPL (composants Qt/PySide6 et FFmpeg)

Deux composants sont sous **LGPL** (copyleft faible) : **Qt/PySide6** (LGPL-3.0)
et **FFmpeg** (LGPL-2.1-or-later, tel qu'embarqué par les *wheels* PyAV publiées sur PyPI).
La LGPL autorise leur usage dans une application sous licence différente (ici MIT),
à condition que l'utilisateur final puisse **remplacer** ces bibliothèques par sa
propre version.

Cette condition est respectée :

1. **Distribution source** — l'utilisateur installe lui-même les bibliothèques via
   `pip install -r requirements.txt` ; il les contrôle donc entièrement.
2. **Distribution binaire** — l'exécutable est compilé en mode **PyInstaller `--onedir`**
   (voir [`LouLLabs_STT.spec`](LouLLabs_STT.spec)). Les bibliothèques Qt et FFmpeg
   restent des fichiers `.dll` **séparés** dans le dossier `dist/LouLLabs_STT/` et
   peuvent être remplacées par une version compatible, conformément à la LGPL.
3. Les **textes de licence** de chaque bibliothèque sont inclus par PyInstaller
   (`collect_all`) dans le dossier de distribution, et les textes officiels sont
   disponibles ici : LGPL-3.0 → https://www.gnu.org/licenses/lgpl-3.0.txt ·
   LGPL-2.1 → https://www.gnu.org/licenses/lgpl-2.1.txt

Le code source des composants LGPL est disponible aux adresses indiquées dans le
tableau ci-dessus (Qt : https://code.qt.io/ · FFmpeg : https://ffmpeg.org/download.html).

## Note

Ce fichier est fourni à titre informatif et de conformité. Les licences exactes
de chaque paquet font foi dans les fichiers `LICENSE`/`METADATA` livrés avec le
paquet correspondant.
