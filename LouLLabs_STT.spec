# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets/icon.ico', 'assets'),
         ('assets/mascot_head.png', 'assets'),
         ('assets/mascot_square.png', 'assets'),
         ('assets/mascot_full.png', 'assets')]
binaries = []
# 100% native Win32 input: no 'keyboard' dependency.
hiddenimports = ['sounddevice', 'pyperclip', 'faster_whisper', 'ctranslate2',
                 'onnxruntime', 'av', 'PySide6.QtWidgets', 'PySide6.QtCore',
                 'PySide6.QtGui']

for pkg in ('faster_whisper', 'ctranslate2', 'onnxruntime', 'av', 'sounddevice'):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h


a = Analysis(
    ['loullabs_stt.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# One-file build: everything is bundled into a SINGLE LouLLabs_STT.exe,
# so it can live at the project root (or anywhere) with no sibling files.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LouLLabs_STT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)
