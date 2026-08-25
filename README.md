<p align="center">
  <img src="assets/mascot_full.png" width="150" alt="LouLLabs STT" />
</p>

<h1 align="center">LouLLabs&nbsp;STT</h1>

<p align="center">
  <b>Dictée vocale 100&nbsp;% locale pour Windows.</b><br/>
  Maintenez une touche, parlez, relâchez — le texte s'écrit là où se trouve votre curseur.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-8B5CF6" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-A855F7" />
  <img src="https://img.shields.io/badge/100%25-local-EC4899" />
  <img src="https://img.shields.io/badge/no-keylogger-22C55E" />
  <img src="https://img.shields.io/badge/licence-MIT-111111" />
</p>

```
MAINTENIR F8  →  🎙️ micro  →  🔴 enregistrement  →  Whisper (local)  →  ⌨️ texte inséré
```

**LouLLabs STT** (Speech&nbsp;to&nbsp;Text) transcrit votre voix en texte, entièrement en local,
sans connexion internet après le premier lancement. Aucune donnée audio ne quitte votre machine,
aucune télémétrie. Le modèle Whisper tourne sur le CPU (quantifié `int8`).

---

## ✨ Points forts

- **Privé par défaut** — audio jamais écrit sur le disque, zéro réseau après le téléchargement du modèle, zéro télémétrie.
- **Pas de keylogger** — aucun hook clavier global. La touche est lue via l'API Win32 `GetAsyncKeyState` (une seule touche), **sans droits administrateur**. Voir [SECURITY.md](SECURITY.md).
- **RAM ~0 au repos** — le modèle se charge à la demande et se **décharge automatiquement** après inactivité ; il est préchargé pendant que vous parlez pour masquer la latence.
- **Deux modes simples** — *Automatique* (par défaut), *Performance* (prêt instantanément) ou *Économie* (libère les ressources au repos). Aucun jargon technique exposé.
- **Transcription fidèle** — le texte est transcrit **fidèlement à votre voix, sans reformulation par une IA**. Aucun post-traitement, aucun LLM, aucune « correction intelligente ».
- **Anti-hallucination** — un appui accidentel sur un silence n'écrit rien : les hallucinations connues de Whisper (« Sous-titres réalisés par… », etc.) et les quasi-silences sont filtrés.
- **Insertion fiable** — le texte est **tapé directement** dans le champ actif (sans toucher au presse-papier), avec repli automatique sur Ctrl+V.
- **Réglable sans code** — clic droit sur l'icône de la barre des tâches → *Paramètres* (touche, langue, modèle, micro, mode, démarrage Windows).
- **Interface soignée** — overlay « liquid glass » translucide et mascotte LouLLabs.

---

## 🚀 Installation

**Prérequis :** Windows 10/11 · [Python 3.10+](https://www.python.org/) (cocher *« Add Python to PATH »*) · un micro.

```bash
git clone https://github.com/LouLLabs/LouLLabs_STT.git
cd LouLLabs_STT
pip install -r requirements.txt
python loullabs_stt.py
```

Ou, sans ligne de commande : double-cliquez sur **`installer.bat`** puis **`lancer.bat`**.

> Le **premier lancement** télécharge le modèle `large-v3-turbo` (~1,5 Go), une seule fois. Ensuite tout est hors-ligne.

---

## ⌨️ Utilisation

| Action | Résultat |
|--------|----------|
| **Maintenir F8** (par défaut) | Enregistre (overlay + mascotte + point rouge clignotant) |
| **Relâcher** | Transcrit et insère le texte dans l'application active |
| **Clic droit sur l'icône** de la barre des tâches | *Paramètres* / *Quitter* |

---

## ⚙️ Paramètres

Tout est réglable depuis la fenêtre *Paramètres* (clic droit sur l'icône) :
touche push-to-talk, langue (ou détection auto), **modèle** (3 choix), microphone,
**méthode d'insertion** (frappe directe / Ctrl+V), **mode** (Automatique / Performance / Économie),
**accélération** (Automatique) et lancement au démarrage de Windows.
Config stockée dans `%APPDATA%\LouLLabs_STT\config.json` (les modèles avancés — `tiny`, `medium`, `large-v3` — s'y ajoutent à la main).

| Modèle | Taille | Qualité FR | Vitesse |
|--------|--------|------------|---------|
| `base` | ~140 Mo | Correcte | Très rapide |
| `small` | ~460 Mo | Bonne | Rapide |
| `large-v3-turbo` ⭐ | ~1,5 Go | Excellente | Bonne |

**Modes.** *Automatique* : équilibre (déchargement après quelques minutes). *Performance* : modèle préchargé au démarrage, prêt instantanément, consomme davantage. *Économie* : RAM libérée rapidement dès l'inactivité.

---

## 📊 Performance

| Métrique | Valeur |
|----------|--------|
| RAM au repos (modèle déchargé) | **~0 Mo** ajouté |
| RAM en usage (turbo int8) | ~880 Mo |
| CPU au repos | ~0 % (lecture d'une touche toutes les 15 ms) |
| Transcription 1,7 s d'audio | ~4–5 s (CPU, `beam_size=3`, VAD actif) |

---

## 🏗️ Compiler en .exe

Double-cliquez sur **`build.bat`** (ou `py -m PyInstaller --noconfirm LouLLabs_STT.spec`).
Résultat : `dist\LouLLabs_STT\LouLLabs_STT.exe` (icône incluse). L'exécutable n'est pas signé — voir [SECURITY.md](SECURITY.md).

---

## 🧱 Architecture

```
loullabs_stt.py       Application (fichier unique)
├── Input Win32        GetAsyncKeyState (touche) + SendInput (frappe/Ctrl+V)
├── GlassOverlay       Overlay translucide (prêt / enregistrement / transcription / succès / erreur)
├── STTEngine          Moteur : lazy-load + déchargement RAM, capture, transcription, insertion
├── HotkeyWatcher      Lecture de la touche (~15 ms) sur le thread Qt
└── SettingsDialog     Fenêtre de réglages (clic droit sur l'icône)
```

Dépendances : `faster-whisper`, `sounddevice`, `numpy`, `pyperclip`, `PySide6`.

---

## 🔒 Sécurité

La posture de sécurité et de confidentialité est détaillée dans **[SECURITY.md](SECURITY.md)**
(pas de hook clavier global, pas de réseau après le modèle, scan `bandit` sans alerte High/Medium…).

## 📄 Licence

Projet sous licence [MIT](LICENSE) — © 2026 LouLLabs.

Les composants tiers conservent leurs propres licences (MIT, BSD, et **LGPL** pour
Qt/PySide6 et FFmpeg). Le détail et la conformité LGPL sont documentés dans
**[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)**. Les poids du modèle Whisper
(OpenAI, MIT) sont téléchargés à la demande et ne sont pas redistribués ici.

<p align="center"><sub>Un outil <a href="https://www.loullabs.com/">LouLLabs</a>.</sub></p>
