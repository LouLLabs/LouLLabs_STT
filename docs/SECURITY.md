# Security & privacy - LouLLabs STT

LouLLabs STT is designed to be **local and private by default**. This document
describes precisely what the program does, does not do, and how to report a problem.

## Principle: everything stays on your machine

- **No audio data ever leaves the computer.** Audio is captured in memory,
  transcribed locally by Whisper (via `faster-whisper` / CTranslate2), then overwritten
  at the next recording. **No audio file is ever written to disk.**
- **No telemetry, no tracking, no advertising.**
- **A single network access, only once:** on the very first launch, the Whisper
  model (~460 MB for the default `small` model) is downloaded from the Hugging Face
  Hub over HTTPS, then cached. After that, the program runs **100% offline**.

## Keyboard: no keylogger, no global hook

This is the most important security point, and it has been redesigned for this version.

- The program **installs no global keyboard hook**. It no longer uses the
  `keyboard` library (which set a low-level hook capturing every keystroke and was
  regularly flagged by antivirus software).
- Push-to-talk detection is done through the Win32 API **`GetAsyncKeyState`**, which
  reads **only the state of the single configured key** (F8 by default). The code
  reads, logs, and stores **no other key**. This is verifiable in a few lines in
  `loullabs_stt.py` (the `key_is_down` function / `HotkeyWatcher` class).
- **No administrator rights are required.**

## Text insertion

- Default method: **direct typing** (SendInput Unicode). The text is typed into the
  active field **without ever going through the clipboard**.
- Optional "clipboard" method (Ctrl+V): in this mode, the previous clipboard
  contents are **saved and then restored** after the paste.
- The text is inserted wherever the focus is: keep in mind not to trigger dictation
  while a sensitive field (e.g. a password) is active.

## System & storage

- The configuration is saved in `%APPDATA%\LouLLabs_STT\config.json`.
  It contains **no sensitive data** (key, language, model, microphone…).
- The "Launch at Windows startup" option writes a value in the user registry key
  `HKCU\...\Run` (user scope, **no admin**). It is removed if you uncheck the option.
- The program **does not run** remote code, and uses neither `eval`/`exec` nor
  subprocesses derived from user input.

## Static analysis

The code is scanned with [`bandit`](https://bandit.readthedocs.io/):
**0 High-severity issues, 0 Medium.** The only remaining alerts are security
`try/except` blocks (resource cleanup, optional Win32 API) - intentional and with
no security impact.

```bash
pip install bandit
bandit -r loullabs_stt.py
```

## Unsigned executable

The `.exe` produced by PyInstaller is not digitally signed: Windows SmartScreen may
display a warning on first launch. This is not a flaw - you can also run the program
directly from the sources (`python loullabs_stt.py`) for full transparency.

**To consider for wider distribution:** signing the executable with a code-signing
certificate (e.g. an OV/EV certificate, or free options such as Azure Trusted
Signing) removes the SmartScreen warning and is the last "professional polish" step
before distributing the `.exe` broadly. It has a cost and is optional - running from
source needs no signature.

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.
Instead, open a private *security advisory* through the **Security** tab of the
GitHub repository, or contact the maintainer directly.
