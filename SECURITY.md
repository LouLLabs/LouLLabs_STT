# Sécurité & vie privée — LouLLabs STT

LouLLabs STT est conçu pour être **local et privé par défaut**. Ce document décrit
précisément ce que le programme fait, ne fait pas, et comment signaler un problème.

## Principe : tout reste sur votre machine

- **Aucune donnée audio ne quitte l'ordinateur.** L'audio est capturé en mémoire,
  transcrit localement par Whisper (via `faster-whisper` / CTranslate2), puis écrasé
  au prochain enregistrement. **Aucun fichier audio n'est écrit sur le disque.**
- **Aucune télémétrie, aucun tracking, aucune publicité.**
- **Un seul accès réseau, une seule fois :** au tout premier lancement, le modèle
  Whisper (~1,5 Go) est téléchargé depuis le Hugging Face Hub en HTTPS, puis mis en
  cache. Ensuite, le programme fonctionne **100 % hors-ligne**.

## Clavier : pas de keylogger, pas de hook global

C'est le point de sécurité le plus important, et il a été repensé pour cette version.

- Le programme **n'installe aucun hook clavier global**. Il n'utilise plus la
  librairie `keyboard` (qui posait un hook bas-niveau captant toutes les frappes et
  était régulièrement signalée par les antivirus).
- La détection du push-to-talk se fait via l'API Win32 **`GetAsyncKeyState`**, qui
  lit **uniquement l'état de la seule touche configurée** (F8 par défaut). Le code ne
  lit, ne journalise et ne stocke **aucune autre touche**. C'est vérifiable en
  quelques lignes dans `loullabs_stt.py` (fonction `key_is_down` / classe `HotkeyWatcher`).
- **Aucun droit administrateur n'est requis.**

## Insertion du texte

- Méthode par défaut : **frappe directe** (SendInput Unicode). Le texte est tapé
  dans le champ actif **sans jamais passer par le presse-papier**.
- Méthode optionnelle « presse-papier » (Ctrl+V) : dans ce mode, le contenu
  précédent du presse-papier est **sauvegardé puis restauré** après le collage.
- Le texte est inséré là où se trouve le focus : gardez à l'esprit de ne pas
  déclencher la dictée alors qu'un champ sensible (ex. mot de passe) est actif.

## Système & stockage

- La configuration est enregistrée dans `%APPDATA%\LouLLabs_STT\config.json`.
  Elle ne contient **aucune donnée sensible** (touche, langue, modèle, micro…).
- L'option « Lancer au démarrage de Windows » écrit une valeur dans la clé de
  registre utilisateur `HKCU\...\Run` (portée utilisateur, **sans admin**). Elle est
  supprimée si vous décochez l'option.
- Le programme **n'exécute pas** de code distant, n'utilise ni `eval`/`exec`, ni
  sous-processus à partir d'entrées utilisateur.

## Analyse statique

Le code est scanné avec [`bandit`](https://bandit.readthedocs.io/) :
**0 problème de sévérité High, 0 Medium.** Les seules alertes restantes sont des
`try/except` de sécurité (nettoyage de ressources, API Win32 optionnelle) —
volontaires et sans impact sécurité.

```bash
pip install bandit
bandit -r loullabs_stt.py
```

## Exécutable non signé

Le `.exe` produit par PyInstaller n'est pas signé numériquement : Windows
SmartScreen peut afficher un avertissement au premier lancement. Ce n'est pas une
faille — vous pouvez aussi exécuter le programme directement depuis les sources
(`python loullabs_stt.py`) pour une transparence totale.

## Signaler une vulnérabilité

Merci de **ne pas** ouvrir d'issue publique pour un problème de sécurité.
Ouvrez plutôt un *security advisory* privé via l'onglet **Security** du dépôt
GitHub, ou contactez le mainteneur directement.
