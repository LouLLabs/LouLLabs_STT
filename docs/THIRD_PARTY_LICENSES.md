# Third-party licenses - LouLLabs STT

LouLLabs STT is distributed under the **MIT** license (see [`LICENSE`](LICENSE)).
It relies on third-party components, each under its own license, listed below.
This document serves as a license notice for both the **source distribution** and the
**binary distribution** (the executable produced by PyInstaller).

## Direct dependencies

| Component | Role | License | Source |
|-----------|------|---------|--------|
| **faster-whisper** | Whisper inference (CTranslate2) | MIT | https://github.com/SYSTRAN/faster-whisper |
| **CTranslate2** | Inference runtime | MIT | https://github.com/OpenNMT/CTranslate2 |
| **sounddevice** | Audio capture | MIT | https://github.com/spatialaudio/python-sounddevice |
| **PortAudio** (via sounddevice) | Audio backend | MIT | https://www.portaudio.com/ |
| **NumPy** | Numerical computing | BSD-3-Clause | https://github.com/numpy/numpy |
| **pyperclip** | Clipboard (optional mode) | BSD-3-Clause | https://github.com/asweigart/pyperclip |
| **ONNX Runtime** | Silero VAD (via faster-whisper) | MIT | https://github.com/microsoft/onnxruntime |
| **PyAV** (`av`) | Audio decoding (FFmpeg wrapper) | BSD-3-Clause | https://github.com/PyAV-Org/PyAV |
| **PySide6 / Qt** | Interface (overlay, tray, settings) | **LGPL-3.0** | https://www.qt.io/ · https://code.qt.io/ |
| **FFmpeg** (bundled via PyAV) | Decoding libraries | **LGPL-2.1-or-later** | https://ffmpeg.org/ |

## Whisper model

The Whisper model weights (`large-v3-turbo` and other sizes) are published by
OpenAI under the **MIT** license and downloaded on demand from the Hugging Face Hub.
They are **not** redistributed in this repository or in the executable.
Source: https://github.com/openai/whisper · https://huggingface.co/

"Whisper" is a name of OpenAI, used here purely descriptively; this project is
neither affiliated with nor endorsed by OpenAI.

## LGPL compliance (Qt/PySide6 and FFmpeg components)

Two components are under the **LGPL** (weak copyleft): **Qt/PySide6** (LGPL-3.0)
and **FFmpeg** (LGPL-2.1-or-later, as bundled by the PyAV *wheels* published on PyPI).
The LGPL permits their use in an application under a different license (MIT here),
provided that the end user can **replace** these libraries with their own version.

This condition is met:

1. **Source distribution** - the user installs the libraries themselves via
   `pip install -r requirements.txt`; they therefore have full control over them.
2. **Binary distribution** - the executable is compiled in **PyInstaller `--onedir`**
   mode (see [`LouLLabs_STT.spec`](LouLLabs_STT.spec)). The Qt and FFmpeg libraries
   remain **separate** `.dll` files in the `dist/LouLLabs_STT/` folder and can be
   replaced with a compatible version, in accordance with the LGPL.
3. The **license texts** of each library are included by PyInstaller
   (`collect_all`) in the distribution folder, and the official texts are
   available here: LGPL-3.0 → https://www.gnu.org/licenses/lgpl-3.0.txt ·
   LGPL-2.1 → https://www.gnu.org/licenses/lgpl-2.1.txt

The source code of the LGPL components is available at the addresses indicated in
the table above (Qt: https://code.qt.io/ · FFmpeg: https://ffmpeg.org/download.html).

## Note

This file is provided for informational and compliance purposes. The exact licenses
of each package are authoritative in the `LICENSE`/`METADATA` files shipped with the
corresponding package.
