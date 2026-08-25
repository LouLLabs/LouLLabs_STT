"""
LouLLabs STT — Speech to Text
Maintenez la touche (F8 par defaut) -> Parlez -> Relachez -> Texte colle
100% local . Whisper . Francais (configurable)

Version 1.0 (publique)
  - Input 100% Win32 natif : aucun hook clavier global (pas de keylogger,
    pas d'alerte antivirus, aucun droit administrateur requis).
    Push-to-talk via GetAsyncKeyState (lecture de l'etat d'UNE seule touche).
    Collage via SendInput.
  - Memoire efficiente : le modele n'est charge qu'a la demande et se
    decharge automatiquement apres inactivite -> ~0 Mo de RAM au repos.
    Prechargement pendant que vous parlez pour masquer la latence.
  - Reglages via clic droit sur l'icone de la barre des taches (config.json).
  - Interface "liquid glass" dans la direction artistique LouLLabs.
"""

import sys
import os
import io
import json
import time
import math
import platform
import threading
import multiprocessing

# ── CRITIQUE pour PyInstaller : empeche le fork-bomb sur Windows ──
# (CTranslate2 / ONNXRuntime relancent des sous-processus ; sans cet appel
#  place avant tout, le .exe --noconsole se re-spawn a l'infini.)
multiprocessing.freeze_support()

# ── Windows uniquement ──────────────────────────────────────────
if platform.system() != "Windows":
    print("Ce programme est concu pour Windows uniquement.")
    sys.exit(1)

import ctypes
from ctypes import wintypes

# ── Imports applicatifs ─────────────────────────────────────────
try:
    import numpy as np
    import sounddevice as sd
    import pyperclip
    from faster_whisper import WhisperModel
    from PySide6.QtWidgets import (
        QApplication, QWidget, QSystemTrayIcon, QMenu, QDialog, QLabel,
        QComboBox, QCheckBox, QSpinBox, QPushButton, QVBoxLayout, QHBoxLayout,
        QGridLayout, QFrame,
    )
    from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRectF, QPointF
    from PySide6.QtGui import (
        QPainter, QColor, QLinearGradient, QRadialGradient, QPen, QBrush,
        QFont, QPainterPath, QPixmap, QIcon, QImage,
    )
except ImportError as e:
    print(f"Dependance manquante : {e}")
    print("Lancez : pip install -r requirements.txt")
    try:
        input("Appuyez sur Entree pour quitter...")
    except EOFError:
        pass
    sys.exit(1)


APP_NAME = "LouLLabs_STT"
APP_VERSION = "1.4"

# ═══════════════════════════════════════════════════════════════
#  CHEMINS / RESSOURCES
# ═══════════════════════════════════════════════════════════════

def resource_path(rel: str) -> str:
    """Chemin d'une ressource embarquee (compatible PyInstaller --onedir)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d

CONFIG_PATH = os.path.join(config_dir(), "config.json")


# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION (persistante)
# ═══════════════════════════════════════════════════════════════

DEFAULT_CONFIG = {
    "hotkey": "f8",              # touche push-to-talk (voir KEY_VK)
    "language": "fr",           # code langue Whisper ("" = auto-detection)
    "model": "large-v3-turbo",  # taille du modele
    "compute_type": "int8",     # quantification (int8 = leger et rapide)
    "beam_size": 3,             # 1 = rapide, 5 = qualite max
    "min_duration": 0.3,        # ignore les appuis < 300 ms
    "mic_device": None,         # index du micro (None = peripherique par defaut)
    "mode": "auto",             # "auto" | "performance" | "eco" (gestion des ressources)
    "idle_unload_minutes": 3,   # (mode auto, avance) delai de dechargement si defini
    "start_with_windows": False,
    "insert_method": "frappe",  # "frappe" = saisie directe (fiable, sans presse-papier)
                                # "collage" = presse-papier + Ctrl+V
    "restore_clipboard": True,  # (mode collage) restaure le presse-papier apres coup
    "first_run_done": False,    # ecran de bienvenue affiche une seule fois
    "silence_rms": 0.006,       # seuil de silence, calibre automatiquement sur le micro
}

# Touches proposees pour le push-to-talk -> code virtuel Win32.
# (uniquement des touches "seules", faciles a maintenir enfoncees)
KEY_VK = {
    "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f12": 0x7B,
    "pause": 0x13, "scroll_lock": 0x91, "inser": 0x2D,
    "ctrl_droit": 0xA3, "menu": 0x5D,
}

MODEL_CHOICES = ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]
# Seuls 3 modeles sont exposes, avec des libelles PRODUIT (pas techniques).
# Le jour ou le moteur change, l'UX ne bouge pas. (id, libelle, note)
RECOMMENDED_MODELS = [
    ("large-v3-turbo", "Precis",    "recommande"),
    ("small",          "Equilibre", "plus leger"),
    ("base",           "Rapide",    "tres leger"),
]
COMPUTE_CHOICES = ["int8", "int8_float16", "float16", "float32"]
LANG_CHOICES = [
    ("Francais", "fr"), ("Anglais", "en"), ("Espagnol", "es"),
    ("Allemand", "de"), ("Italien", "it"), ("Detection auto", ""),
]

# Modes de gestion des ressources (l'utilisateur ne voit jamais la technique)
MODE_CHOICES = [
    ("Automatique", "auto"),
    ("Performance", "performance"),
    ("Economie", "eco"),
]

# ── Garde-fou anti-hallucination ────────────────────────────────
# Whisper "invente" parfois du texte sur un silence (appui accidentel).
# Ces phrases, tres frequentes, ne sont jamais dictees volontairement.
import re as _re
import unicodedata as _ud

def _normalize(s: str) -> str:
    s = _ud.normalize("NFD", s.lower())
    s = "".join(c for c in s if _ud.category(c) != "Mn")   # retire les accents
    return _re.sub(r"\s+", " ", _re.sub(r"[^0-9a-z]+", " ", s)).strip()

# Principe : faux positif > faux negatif. On prefere laisser passer une
# hallucination rare plutot que de "manger" une vraie phrase. Donc la blacklist
# ne contient QUE des phrases multi-mots jamais dictees volontairement ; les mots
# courts frequents ("merci", "oui", "ok"...) NE sont PAS ici (un utilisateur peut
# les dicter) — ils sont geres par la confiance du modele (no_speech / logprob).
HALLUCINATION_BLOCKLIST = {_normalize(x) for x in [
    "Sous-titres realises par la communaute d'Amara.org",
    "Sous-titres realises para la communaute d'Amara.org",
    "Sous-titrage ST' 501",
    "Sous-titres fait par la communaute d'Amara.org",
    "Merci d'avoir regarde cette video",
    "Merci d'avoir regarde cette video a bientot",
    "Merci a tous et a la prochaine",
    "Thank you for watching",
    "Thanks for watching this video",
    "Please subscribe to my channel",
]}
SILENCE_RMS = 0.006     # sous ce seuil : quasi-silence (valide sur enregistrements reels :
                        # parole >= 0.015, silence ~ 0.0001)

# Palette LouLLabs
VIOLET = QColor(139, 92, 246)
VIOLET2 = QColor(168, 85, 247)
ROSE = QColor(236, 72, 153)
INK = QColor(17, 17, 17)
ROUGE = QColor(255, 45, 55)     # rouge vif (etat enregistrement)
OVERLAY_RADIUS = 30             # arrondi des coins de l'overlay


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULT_CONFIG})
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  Config illisible ({e}), valeurs par defaut utilisees.")
    # garde-fous
    if cfg["hotkey"] not in KEY_VK:
        cfg["hotkey"] = "f8"
    if cfg["model"] not in MODEL_CHOICES:
        cfg["model"] = "large-v3-turbo"
    if cfg["compute_type"] not in COMPUTE_CHOICES:
        cfg["compute_type"] = "int8"
    return cfg


def save_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"  Impossible d'enregistrer la config : {e}")


# ═══════════════════════════════════════════════════════════════
#  DEMARRAGE AVEC WINDOWS (cle de registre Run, sans droits admin)
# ═══════════════════════════════════════════════════════════════

def _run_command() -> str:
    """Commande a lancer au demarrage de session."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # mode script : pythonw.exe pour ne pas ouvrir de console
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    return f'"{exe}" "{os.path.abspath(__file__)}"'

def set_start_with_windows(enabled: bool) -> bool:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _run_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"  Demarrage Windows : {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  DETECTION MATERIEL (natif, zero dependance) — pour le diagnostic
# ═══════════════════════════════════════════════════════════════

def detect_ram_gb():
    """(total_Go, dispo_Go) via GlobalMemoryStatusEx, sinon (None, None)."""
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MEMORYSTATUSEX(); m.dwLength = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullTotalPhys / (1024 ** 3), m.ullAvailPhys / (1024 ** 3)
    except Exception:
        return None, None


def detect_gpu():
    """Nom du GPU via EnumDisplayDevices (aucun subprocess), sinon None."""
    try:
        class DISPLAY_DEVICE(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                        ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                        ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]
        names, i = [], 0
        while i < 16:
            dd = DISPLAY_DEVICE(); dd.cb = ctypes.sizeof(dd)
            if not ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
                break
            s = dd.DeviceString
            if s and s not in names:
                names.append(s)
            i += 1
        for n in names:   # privilegie un GPU nomme
            if any(k in n for k in ("Radeon", "NVIDIA", "GeForce", "RTX", "Arc", "Intel")):
                return n
        return names[0] if names else None
    except Exception:
        return None


def detect_mic():
    """Nom du micro par defaut, sinon None."""
    try:
        return sd.query_devices(kind="input").get("name")
    except Exception:
        return None


def calibrate_mic(device=None, seconds=1.0):
    """Mesure le bruit de fond et propose un seuil de silence adapte au micro.
    Retourne (seuil, bruit_rms) ou None. Le seuil ne descend jamais sous 0.006
    (valide sur enregistrements reels) et est plafonne : combine a la confiance
    du modele, il ne peut jamais supprimer une vraie phrase."""
    try:
        rec = sd.rec(int(seconds * 16000), samplerate=16000, channels=1,
                     dtype="float32", device=device)
        sd.wait()
        noise = float(np.sqrt(np.mean(np.square(rec))))
        threshold = min(0.02, max(0.006, noise * 8.0))
        return round(threshold, 4), round(noise, 5)
    except Exception as e:
        print(f"  Calibration micro impossible : {e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  INPUT WIN32 NATIF (aucun hook global, aucun droit admin)
# ═══════════════════════════════════════════════════════════════

_user32 = ctypes.windll.user32

def key_is_down(vk: int) -> bool:
    """True si la touche est physiquement enfoncee (bit de poids fort)."""
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)

# --- SendInput : structures ---
ULONG_PTR = wintypes.WPARAM  # taille pointeur (UINT_PTR)

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]

INPUT_KEYBOARD  = 1
KEYEVENTF_KEYUP     = 0x0002
KEYEVENTF_UNICODE   = 0x0004
KEYEVENTF_SCANCODE  = 0x0008
VK_CONTROL = 0x11
VK_V = 0x56
MAPVK_VK_TO_VSC = 0

# Signatures explicites (evite toute troncature de pointeur en 64 bits)
try:
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT
    _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    _user32.MapVirtualKeyW.restype = wintypes.UINT
except Exception:
    pass


def _send(events):
    arr = (INPUT * len(events))(*events)
    return _user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))


def _kb_vk(vk: int, up: bool) -> INPUT:
    """Evenement touche par code virtuel + scancode (compatibilite maximale)."""
    scan = _user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    return INPUT(INPUT_KEYBOARD, _INPUTunion(KEYBDINPUT(vk, scan, flags, 0, 0)))


def _kb_unicode(code_unit: int, up: bool) -> INPUT:
    """Evenement de saisie d'un caractere Unicode (UTF-16)."""
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    return INPUT(INPUT_KEYBOARD, _INPUTunion(KEYBDINPUT(0, code_unit, flags, 0, 0)))


def type_unicode(text: str) -> bool:
    """Tape le texte directement dans la fenetre active (aucun presse-papier).
    Methode la plus fiable : fonctionne dans les champs texte, navigateurs,
    messageries, editeurs, boites de dialogue, quelle que soit la disposition."""
    try:
        data = text.encode("utf-16-le")
        import struct
        units = struct.unpack("<%dH" % (len(data) // 2), data)
        events = []
        for cu in units:
            events.append(_kb_unicode(cu, False))
            events.append(_kb_unicode(cu, True))
        if not events:
            return True
        # Envoi par lots pour rester sous les limites de la file d'entree
        BATCH = 400
        sent = 0
        for i in range(0, len(events), BATCH):
            sent += _send(events[i:i + BATCH])
        return sent > 0
    except Exception as e:
        print(f"  Saisie Unicode impossible : {e}")
        return False


def send_ctrl_v() -> bool:
    """Envoie Ctrl+V (methode presse-papier). Verifie le succes, fallback keybd_event."""
    try:
        n = _send([_kb_vk(VK_CONTROL, False), _kb_vk(VK_V, False),
                   _kb_vk(VK_V, True), _kb_vk(VK_CONTROL, True)])
        if n and n >= 4:
            return True
    except Exception:
        pass
    try:  # fallback API historique
        _user32.keybd_event(VK_CONTROL, 0, 0, 0)
        _user32.keybd_event(VK_V, 0, 0, 0)
        _user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
        _user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception as e:
        print(f"  Collage impossible : {e}")
        return False


# ═══════════════════════════════════════════════════════════════
#  ICONE (chargee depuis assets, fallback dessine)
# ═══════════════════════════════════════════════════════════════

def app_icon() -> QIcon:
    for name in ("assets/icon.ico", "icon.ico", "assets/mascot_square.png"):
        p = resource_path(name)
        if os.path.exists(p):
            ic = QIcon(p)
            if not ic.isNull():
                return ic
    return QIcon(_fallback_pixmap())

def _fallback_pixmap() -> QPixmap:
    """Icone micro violet->rose dessinee (si l'asset est absent)."""
    size = 64
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    cx, cy = size // 2, size // 2
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, VIOLET); grad.setColorAt(1.0, ROSE)
    p.setPen(Qt.NoPen); p.setBrush(QBrush(grad))
    p.drawRoundedRect(QRectF(4, 4, size - 8, size - 8), 16, 16)
    p.setBrush(QColor(255, 255, 255))
    mic = QPainterPath()
    mic.addRoundedRect(QRectF(cx - 7, cy - 15, 14, 22), 7, 7)
    p.drawPath(mic)
    p.setPen(QPen(QColor(255, 255, 255), 3, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(cx - 13, cy - 4, 26, 26), 0, -180 * 16)
    p.drawLine(QPointF(cx, cy + 9), QPointF(cx, cy + 15))
    p.drawLine(QPointF(cx - 7, cy + 15), QPointF(cx + 7, cy + 15))
    p.end()
    return QPixmap.fromImage(img)


# ═══════════════════════════════════════════════════════════════
#  SIGNAUX THREAD-SAFE
# ═══════════════════════════════════════════════════════════════

class Signals(QObject):
    show_recording    = Signal()
    show_transcribing = Signal()
    show_loading      = Signal(str)
    show_success      = Signal(str)
    show_ready        = Signal()
    show_error        = Signal(str)
    hide_overlay      = Signal()
    update_level      = Signal(float)


# ═══════════════════════════════════════════════════════════════
#  OVERLAY LIQUID GLASS
# ═══════════════════════════════════════════════════════════════

class GlassOverlay(QWidget):
    WIDTH  = 340
    HEIGHT = 88

    def __init__(self, hotkey_label="F8"):
        super().__init__()
        self.hotkey_label = hotkey_label
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - self.WIDTH) // 2,
                  screen.height() - self.HEIGHT - 100)

        self._mode = "idle"
        self._level = 0.0
        self._smooth_level = 0.0
        self._frame = 0
        self._success_text = ""
        self._loading_text = ""
        self._error_text = ""
        self._opacity = 0.0
        self._target_opacity = 0.0
        self._bar_heights = [0.0] * 24

        # Mascotte LouLLabs (affichee dans l'etat "pret")
        self._mascot = QPixmap()
        mp = resource_path("assets/mascot_head.png")
        if os.path.exists(mp):
            pm = QPixmap(mp)
            if not pm.isNull():
                self._mascot = pm.scaledToHeight(46, Qt.SmoothTransformation)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(33)

        self.signals = Signals()
        self.signals.show_recording.connect(self._on_show_recording)
        self.signals.show_transcribing.connect(self._on_show_transcribing)
        self.signals.show_loading.connect(self._on_show_loading)
        self.signals.show_success.connect(self._on_show_success)
        self.signals.show_ready.connect(self._on_show_ready)
        self.signals.show_error.connect(self._on_show_error)
        self.signals.hide_overlay.connect(self._on_hide)
        self.signals.update_level.connect(self._on_update_level)

    def set_hotkey_label(self, label):
        self.hotkey_label = label

    def showEvent(self, event):
        super().showEvent(event)
        # Pas de flou acrylique Windows : il peint un rectangle OPAQUE carre
        # derriere la fenetre (le "carre" visible aux angles). On s'en passe :
        # le rendu translucide (WA_TranslucentBackground) donne des coins
        # arrondis parfaitement nets et un fond reellement transparent.
        self.clearMask()

    # ─── Slots ──────────────────────────────────────────────────
    def _start(self, mode):
        self._mode = mode
        self._frame = 0
        self._target_opacity = 1.0
        self.show()
        if not self._timer.isActive():
            self._timer.start()

    def _on_show_recording(self):    self._start("recording")
    def _on_show_transcribing(self): self._start("transcribing")

    def _on_show_loading(self, text):
        self._loading_text = text
        self._start("loading")

    def _on_show_success(self, text):
        self._success_text = text[:50] + ("..." if len(text) > 50 else "")
        self._start("success")
        QTimer.singleShot(2000, self._on_hide)

    def _on_show_ready(self):
        self._start("ready")
        QTimer.singleShot(3000, self._on_hide)

    def _on_show_error(self, text):
        self._error_text = text
        self._start("error")
        QTimer.singleShot(3500, self._on_hide)

    def _on_hide(self):        self._target_opacity = 0.0
    def _on_update_level(self, level): self._level = min(max(level, 0.0), 1.0)

    # ─── Animation ──────────────────────────────────────────────
    def _tick(self):
        self._frame += 1
        self._opacity += (self._target_opacity - self._opacity) * 0.18
        if self._opacity < 0.01 and self._target_opacity == 0.0:
            self._opacity = 0.0
            self._timer.stop()
            self.hide()
            return
        self._smooth_level += (self._level - self._smooth_level) * 0.3
        if self._mode == "recording":
            for i in range(24):
                wave = 0.3 + 0.7 * abs(math.sin(self._frame * 0.08 + i * 0.45))
                self._bar_heights[i] += (self._smooth_level * wave - self._bar_heights[i]) * 0.25
        self.update()

    # ─── Rendu ──────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._opacity)
        w, h = self.WIDTH, self.HEIGHT
        self._draw_glass_bg(p, w, h)
        {
            "recording": self._draw_recording,
            "transcribing": self._draw_transcribing,
            "loading": self._draw_loading,
            "success": self._draw_success,
            "ready": self._draw_ready,
            "error": self._draw_error,
        }.get(self._mode, lambda *_: None)(p, w, h)
        p.end()

    def _draw_glass_bg(self, p, w, h):
        path = QPainterPath()
        radius = OVERLAY_RADIUS
        path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        bg = QLinearGradient(0, 0, w, h)
        bg.setColorAt(0.0, QColor(139, 92, 246, 40))   # plus transparent
        bg.setColorAt(0.5, QColor(168, 85, 247, 30))
        bg.setColorAt(1.0, QColor(236, 72, 153, 36))
        p.fillPath(path, QBrush(bg))
        inner = QPainterPath()
        inner.addRoundedRect(QRectF(1, 1, w - 2, h - 2), radius - 1, radius - 1)
        ig = QLinearGradient(0, 0, w, 0)
        ig.setColorAt(0.0, QColor(255, 255, 255, 18))
        ig.setColorAt(0.5, QColor(255, 255, 255, 8))
        ig.setColorAt(1.0, QColor(255, 255, 255, 15))
        p.fillPath(inner, QBrush(ig))
        bd = QLinearGradient(0, 0, w, h)
        bd.setColorAt(0.0, QColor(255, 255, 255, 50))
        bd.setColorAt(0.3, QColor(168, 85, 247, 40))
        bd.setColorAt(0.7, QColor(236, 72, 153, 35))
        bd.setColorAt(1.0, QColor(255, 255, 255, 45))
        p.setPen(QPen(QBrush(bd), 1.0))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)
        hl = QPainterPath()
        hl.addRoundedRect(QRectF(2, 2, w - 4, h * 0.38), radius - 1, radius - 1)
        hg = QLinearGradient(0, 0, 0, h * 0.38)
        hg.setColorAt(0.0, QColor(255, 255, 255, 25))
        hg.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen)
        p.fillPath(hl, QBrush(hg))

    def _title_font(self):
        f = QFont("Space Grotesk", 11); f.setWeight(QFont.DemiBold)
        return f

    def _small_font(self):
        return QFont("Space Grotesk", 8)

    def _draw_recording(self, p, w, h):
        blink = abs(math.sin(self._frame * 0.16))   # clignotement du point rouge
        text_x = 50

        # ── Mascotte + point rouge clignotant sur la tete ──
        if not self._mascot.isNull():
            mw, mh = self._mascot.width(), self._mascot.height()
            mx, my = 14, (h - mh) / 2
            p.drawPixmap(int(mx), int(my), self._mascot)
            dcx, dcy = mx + mw * 0.72, my + mh * 0.13
            gg = QRadialGradient(dcx, dcy, 12)
            gg.setColorAt(0.0, QColor(255, 40, 50, int(190 * blink)))
            gg.setColorAt(1.0, QColor(255, 40, 50, 0))
            p.setPen(Qt.NoPen); p.setBrush(QBrush(gg))
            p.drawEllipse(QPointF(dcx, dcy), 12, 12)
            p.setBrush(QColor(255, 52, 62, int(80 + 175 * blink)))
            p.drawEllipse(QPointF(dcx, dcy), 4.8, 4.8)
            p.setPen(QPen(QColor(255, 255, 255, int(130 * blink)), 1))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(dcx, dcy), 4.8, 4.8)
            text_x = int(mx + mw + 12)
        else:
            cx, cy = 30, h // 2 - 8
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 52, 62, int(80 + 175 * blink)))
            p.drawEllipse(QPointF(cx, cy), 6, 6)
            text_x = 50

        # ── Texte rouge vif ──
        f = QFont("Space Grotesk", 12); f.setWeight(QFont.Bold)
        p.setPen(QColor(255, 66, 76)); p.setFont(f)
        p.drawText(text_x, h // 2 - 5, "Enregistrement")

        # ── Badge touche (haut droite) ──
        bx, by = w - 48, 12
        bp = QPainterPath(); bp.addRoundedRect(QRectF(bx, by, 34, 20), 6, 6)
        p.setPen(Qt.NoPen); p.fillPath(bp, QColor(255, 255, 255, 22))
        p.setPen(QColor(255, 255, 255, 150)); p.setFont(self._small_font())
        p.drawText(QRectF(bx, by, 34, 20), Qt.AlignCenter, self.hotkey_label)

        # ── Ondes rouges (sous le texte, a droite de la mascotte) ──
        bar_y, bar_w, gap = h - 22, 3.5, 3
        start_x, max_x = text_x, w - 16
        n = min(24, int((max_x - start_x) / (bar_w + gap)))
        for i in range(n):
            x = start_x + i * (bar_w + gap)
            bh = max(1.5, self._bar_heights[i] * 15)
            t = i / 23
            col = QColor(255, int(55 + t * 85), int(60 + t * 65),
                         240 if t < self._smooth_level + 0.2 else 120)
            bpth = QPainterPath()
            bpth.addRoundedRect(QRectF(x, bar_y - bh, bar_w, bh * 2), 1.5, 1.5)
            p.setPen(Qt.NoPen); p.fillPath(bpth, col)

    def _spinner(self, p, cx, cy, r=9):
        angle = self._frame * 8
        p.setPen(QPen(QColor(168, 85, 247, 60), 2.5, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), 0, 360 * 16)
        p.setPen(QPen(QColor(168, 85, 247), 2.5, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), int(angle * 16), int(90 * 16))

    def _draw_transcribing(self, p, w, h):
        mid_y = h // 2
        self._spinner(p, 30, mid_y - 2)
        p.setPen(QColor(255, 255, 255, 210)); p.setFont(QFont("Space Grotesk", 11))
        p.drawText(52, mid_y + 2, "Transcription en cours...")
        dots = (self._frame // 10) % 4
        for i in range(3):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(168, 85, 247, 200 if i < dots else 40))
            p.drawEllipse(QPointF(52 + i * 12, mid_y + 20), 2.5, 2.5)

    def _draw_loading(self, p, w, h):
        self._spinner(p, 30, h // 2 - 8)
        p.setPen(QColor(255, 255, 255, 225)); p.setFont(self._title_font())
        p.drawText(52, h // 2 - 6, "Preparation du modele")
        p.setPen(QColor(255, 255, 255, 140)); p.setFont(self._small_font())
        p.drawText(52, h // 2 + 14, self._loading_text or "Un instant...")

    def _draw_ready(self, p, w, h):
        mid_y = h // 2
        text_x = 52
        if not self._mascot.isNull():
            mw, mh = self._mascot.width(), self._mascot.height()
            mx, my = 16, (h - mh) / 2
            # halo doux derriere la mascotte
            gg = QRadialGradient(mx + mw / 2, mid_y, mw * 0.8)
            gg.setColorAt(0.0, QColor(168, 85, 247, 70)); gg.setColorAt(1.0, QColor(168, 85, 247, 0))
            p.setPen(Qt.NoPen); p.setBrush(QBrush(gg))
            p.drawEllipse(QPointF(mx + mw / 2, mid_y), mw * 0.8, mw * 0.8)
            p.drawPixmap(int(mx), int(my), self._mascot)
            text_x = int(mx + mw + 12)
        else:
            cx, cy = 30, mid_y - 3
            mg = QLinearGradient(cx - 9, cy - 9, cx + 9, cy + 9)
            mg.setColorAt(0.0, VIOLET); mg.setColorAt(1.0, VIOLET2)
            p.setPen(Qt.NoPen); p.setBrush(QBrush(mg)); p.drawEllipse(QPointF(cx, cy), 9, 9)
            p.setPen(QPen(QColor(255, 255, 255), 1.8, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx, cy - 4), QPointF(cx, cy + 2))
            p.drawLine(QPointF(cx - 3, cy + 3.5), QPointF(cx + 3, cy + 3.5))
        p.setPen(QColor(255, 255, 255, 235)); p.setFont(self._title_font())
        p.drawText(text_x, mid_y - 1, "LouLLabs STT — pret")
        p.setPen(QColor(255, 255, 255, 140)); p.setFont(self._small_font())
        p.drawText(text_x, mid_y + 16, "Maintenez " + self.hotkey_label + " pour parler")

    def _draw_success(self, p, w, h):
        mid_y = h // 2
        cx, cy = 30, mid_y - 3
        gg = QRadialGradient(cx, cy, 16)
        gg.setColorAt(0.0, QColor(34, 197, 94, 60)); gg.setColorAt(1.0, QColor(34, 197, 94, 0))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(gg)); p.drawEllipse(QPointF(cx, cy), 16, 16)
        p.setBrush(QColor(34, 197, 94)); p.drawEllipse(QPointF(cx, cy), 10, 10)
        p.setPen(QPen(QColor(255, 255, 255), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(cx - 4, cy), QPointF(cx - 1, cy + 3.5))
        p.drawLine(QPointF(cx - 1, cy + 3.5), QPointF(cx + 4.5, cy - 3))
        p.setPen(QColor(34, 197, 94)); p.setFont(self._title_font())
        p.drawText(52, mid_y + 1, "Texte colle !")
        p.setPen(QColor(255, 255, 255, 120)); p.setFont(self._small_font())
        p.drawText(52, mid_y + 18, self._success_text)

    def _draw_error(self, p, w, h):
        mid_y = h // 2
        cx, cy = 30, mid_y - 3
        gg = QRadialGradient(cx, cy, 16)
        gg.setColorAt(0.0, QColor(239, 68, 68, 70)); gg.setColorAt(1.0, QColor(239, 68, 68, 0))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(gg)); p.drawEllipse(QPointF(cx, cy), 16, 16)
        p.setBrush(QColor(239, 68, 68)); p.drawEllipse(QPointF(cx, cy), 10, 10)
        p.setPen(QPen(QColor(255, 255, 255), 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx - 3.5, cy - 3.5), QPointF(cx + 3.5, cy + 3.5))
        p.drawLine(QPointF(cx + 3.5, cy - 3.5), QPointF(cx - 3.5, cy + 3.5))
        p.setPen(QColor(255, 120, 120)); p.setFont(self._title_font())
        p.drawText(52, mid_y - 2, "Probleme")
        p.setPen(QColor(255, 255, 255, 150)); p.setFont(self._small_font())
        p.drawText(QRectF(52, mid_y + 4, w - 64, 30), Qt.TextWordWrap, self._error_text)


# ═══════════════════════════════════════════════════════════════
#  DETECTION CACHE MODELE (pour l'ecran de telechargement)
# ═══════════════════════════════════════════════════════════════

def model_is_cached(model_name: str) -> bool:
    """Heuristique : le modele existe-t-il deja dans le cache HuggingFace ?"""
    token = model_name.replace("large-v3-turbo", "turbo").split("-")[0]
    roots = [
        os.environ.get("HF_HOME"),
        os.path.join(os.environ.get("HF_HOME", ""), "hub") if os.environ.get("HF_HOME") else None,
        os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub"),
    ]
    for root in roots:
        if root and os.path.isdir(root):
            for entry in os.listdir(root):
                low = entry.lower()
                if "whisper" in low and (model_name.lower() in low or token in low):
                    return True
    return False


# ═══════════════════════════════════════════════════════════════
#  MOTEUR DE DICTEE (chargement paresseux + dechargement auto)
# ═══════════════════════════════════════════════════════════════

class STTEngine:
    def __init__(self, overlay: GlassOverlay, cfg: dict):
        self.overlay = overlay
        self.cfg = cfg
        self.model = None
        self.recording = False
        self.audio_chunks = []
        self.stream = None
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._loading = False
        self._model_ready = threading.Event()
        self._loaded_signature = None      # (model, compute_type) charge
        self._record_start = 0.0
        self._last_activity = time.time()

    # ─── Gestion du modele ──────────────────────────────────────
    def _signature(self):
        return (self.cfg["model"], self.cfg["compute_type"])

    def request_model(self):
        """Declenche le chargement du modele en tache de fond si necessaire."""
        with self._load_lock:
            if self.model is not None and self._loaded_signature == self._signature():
                self._model_ready.set()
                return
            if self.model is not None and self._loaded_signature != self._signature():
                # config changee -> on decharge l'ancien
                self.model = None
                self._model_ready.clear()
            if self._loading:
                return
            self._loading = True
            self._model_ready.clear()
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _load_worker(self):
        sig = self._signature()
        try:
            if not model_is_cached(sig[0]):
                self.overlay.signals.show_loading.emit(
                    "Telechargement (~1.5 Go), 1re fois seulement")
            model = WhisperModel(
                sig[0], device="cpu", compute_type=sig[1],
                cpu_threads=max(1, (os.cpu_count() or 2) // 2),
                num_workers=1,
            )
            with self._load_lock:
                self.model = model
                self._loaded_signature = sig
                self._loading = False
            self._model_ready.set()
            print(f"  Modele '{sig[0]}' ({sig[1]}) charge.")
        except Exception as e:
            with self._load_lock:
                self._loading = False
            self._model_ready.set()  # debloque les threads en attente
            print(f"  Erreur de chargement du modele : {e}")
            self.overlay.signals.show_error.emit("Chargement du modele impossible")

    def _idle_minutes(self) -> int:
        """Delai de dechargement selon le mode (0 = jamais)."""
        m = self.cfg.get("mode", "auto")
        if m == "performance":
            return 0            # modele garde en memoire
        if m == "eco":
            return 2            # libere vite les ressources
        adv = self.cfg.get("idle_unload_minutes")   # override avance (mode auto)
        return adv if isinstance(adv, int) and adv > 0 else 4

    def unload_model_if_idle(self):
        """Appele periodiquement : libere la RAM apres inactivite."""
        minutes = self._idle_minutes()
        if not minutes or self.recording or self.model is None:
            return
        if time.time() - self._last_activity > minutes * 60:
            with self._load_lock:
                if self._loading:
                    return
                self.model = None
                self._loaded_signature = None
                self._model_ready.clear()
            import gc; gc.collect()
            print("  Modele decharge (inactivite) -> RAM liberee.")

    def touch(self):
        self._last_activity = time.time()

    # ─── Push-to-talk ───────────────────────────────────────────
    def on_press(self):
        with self._lock:
            if self.recording:
                return
            self.recording = True
        self.touch()
        self.audio_chunks = []
        self._record_start = time.time()
        # Precharge le modele PENDANT que l'utilisateur parle (latence masquee)
        self.request_model()
        try:
            self.stream = sd.InputStream(
                samplerate=16000, channels=1, dtype="float32",
                callback=self._audio_callback, blocksize=1024,
                device=self.cfg.get("mic_device"),
            )
            self.stream.start()
        except Exception as e:
            with self._lock:
                self.recording = False
            print(f"  Erreur micro : {e}")
            self.overlay.signals.show_error.emit(
                "Micro indisponible - verifiez votre peripherique")
            return
        self.overlay.signals.show_recording.emit()

    def on_release(self):
        with self._lock:
            if not self.recording:
                return
            self.recording = False
        self.touch()
        if self.stream:
            try:
                self.stream.stop(); self.stream.close()
            except Exception:
                pass
            self.stream = None
        duration = time.time() - self._record_start
        if duration < self.cfg.get("min_duration", 0.3):
            self.overlay.signals.hide_overlay.emit()
            return
        threading.Thread(target=self._transcrire, daemon=True).start()

    def _audio_callback(self, indata, frames, time_info, status):
        self.audio_chunks.append(indata.copy())
        level = float(np.abs(indata).mean()) * 8.0
        self.overlay.signals.update_level.emit(min(level, 1.0))

    def _transcrire(self):
        try:
            if not self.audio_chunks:
                self.overlay.signals.hide_overlay.emit()
                return
            audio = np.concatenate(self.audio_chunks, axis=0).flatten()

            # Attendre le modele (charge en fond depuis l'appui sur la touche)
            if self.model is None or not self._model_ready.is_set():
                self.overlay.signals.show_loading.emit("Chargement du modele...")
                self.request_model()
                self._model_ready.wait(timeout=120)
            model = self.model
            if model is None:
                self.overlay.signals.show_error.emit("Modele indisponible")
                return

            self.overlay.signals.show_transcribing.emit()
            t0 = time.time()
            segments, info = model.transcribe(
                audio,
                language=self.cfg.get("language") or None,
                beam_size=self.cfg.get("beam_size", 3),
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                without_timestamps=True,
                no_speech_threshold=0.6,
            )
            # Un seul passage : on recolte le texte ET les signaux de confiance
            parts, nsp, alp, cr = [], [], [], []
            for s in segments:
                t = s.text.strip()
                if t:
                    parts.append(t)
                nsp.append(float(getattr(s, "no_speech_prob", 0.0)))
                alp.append(float(getattr(s, "avg_logprob", 0.0)))
                cr.append(float(getattr(s, "compression_ratio", 1.0)))
            text = " ".join(parts).strip()
            metrics = {
                "no_speech": (sum(nsp) / len(nsp)) if nsp else 1.0,
                "avg_logprob": (sum(alp) / len(alp)) if alp else -10.0,
                "compression": (max(cr) if cr else 1.0),
            }
            elapsed = time.time() - t0
            self.touch()

            if text and not self._should_suppress(text, audio, metrics):
                self._paste(text)
                print(f"  [{elapsed:.1f}s] -> {text}")
                self.overlay.signals.show_success.emit(text)
            else:
                print(f"  Aucune parole exploitable ({elapsed:.1f}s)")
                self.overlay.signals.hide_overlay.emit()
        except Exception as e:
            print(f"  Erreur de transcription : {e}")
            self.overlay.signals.show_error.emit("Erreur de transcription")

    def _should_suppress(self, text: str, audio, m: dict) -> bool:
        """Filtre multi-signal des hallucinations de Whisper.

        Combine plusieurs indices plutot qu'une seule blacklist ou le seul
        volume (RMS) : texte vide, phrase connue, repetition, et surtout la
        CONFIANCE du modele (no_speech_prob / avg_logprob). Objectif : ne
        jamais 'manger' une vraie phrase, meme dite doucement.
        """
        norm = _normalize(text)
        if not norm:
            return True

        # 1) Filet : hallucinations textuelles connues (exactes)
        if norm in HALLUCINATION_BLOCKLIST:
            print(f"  Hallucination connue ignoree : {text!r}")
            return True

        # 2) Boucle de repetition / charabia (ratio de compression eleve)
        if m.get("compression", 1.0) > 2.5:
            print(f"  Repetition suspecte (cr={m['compression']:.2f}) ignoree : {text!r}")
            return True

        no_speech = m.get("no_speech", 0.0)
        logprob = m.get("avg_logprob", 0.0)

        # 3) Le modele est tres confiant qu'il n'y a PAS de parole, et peu sur de lui
        if no_speech > 0.85 and logprob < -1.0:
            print(f"  Absence de parole (no_speech={no_speech:.2f}, lp={logprob:.2f}) : {text!r}")
            return True

        # 4) Quasi-silence UNIQUEMENT combine a une faible confiance du modele
        #    (un 'oui' clair mais doux garde un bon logprob -> non filtre)
        try:
            rms = float(np.sqrt(np.mean(np.square(audio))))
        except Exception:
            rms = 1.0
        silence_rms = self.cfg.get("silence_rms", SILENCE_RMS)
        if rms < silence_rms and logprob < -0.8 and len(norm) < 40:
            print(f"  Quasi-silence peu fiable (rms={rms:.4f}, lp={logprob:.2f}) : {text!r}")
            return True

        return False

    def _paste(self, text: str):
        """Insere le texte dans la fenetre active."""
        method = self.cfg.get("insert_method", "frappe")

        # ── Methode par defaut : saisie directe (aucun presse-papier) ──
        if method != "collage":
            if type_unicode(text):
                return
            print("  Saisie directe indisponible, bascule sur le presse-papier.")

        # ── Methode presse-papier + Ctrl+V (sauvegarde/restauration garantie) ──
        restore = self.cfg.get("restore_clipboard", True)
        previous = None
        if restore:
            try:
                previous = pyperclip.paste()   # contenu a preserver
            except Exception:
                previous = None
        try:
            pyperclip.copy(text)
        except Exception as e:
            print(f"  Presse-papier inaccessible ({e}), saisie directe.")
            type_unicode(text)
            return
        try:
            time.sleep(0.12)                   # Windows s'approprie le presse-papier
            send_ctrl_v()
        finally:
            # restauration TOUJOURS executee, meme si le collage a echoue
            if restore and previous is not None:
                time.sleep(0.4)                # laisse l'app consommer le collage
                try:
                    pyperclip.copy(previous)
                except Exception:
                    pass

    def stop(self):
        if self.stream:
            try:
                self.stream.stop(); self.stream.close()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
#  SURVEILLANCE DE LA TOUCHE (poll Win32, thread UI, ~15 ms)
# ═══════════════════════════════════════════════════════════════

class HotkeyWatcher(QObject):
    def __init__(self, engine: "STTEngine"):
        super().__init__()
        self.engine = engine
        self.vk = KEY_VK.get(engine.cfg["hotkey"], 0x77)
        self._down = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.setInterval(15)
        self._timer.start()

    def set_hotkey(self, name: str):
        self.vk = KEY_VK.get(name, 0x77)
        self._down = False

    def _poll(self):
        down = key_is_down(self.vk)
        if down and not self._down:
            self._down = True
            self.engine.on_press()
        elif not down and self._down:
            self._down = False
            self.engine.on_release()


# ═══════════════════════════════════════════════════════════════
#  FENETRE DE REGLAGES
# ═══════════════════════════════════════════════════════════════

SETTINGS_QSS = """
QDialog { background: #17151F; }
QLabel  { color: #E7E3F1; font-family: 'Space Grotesk','Segoe UI'; font-size: 10pt; }
QLabel#title { font-size: 16pt; font-weight: 600; color: #FFFFFF; }
QLabel#hint  { color: #9A93AE; font-size: 8pt; }
QComboBox, QSpinBox {
    background: #211E2C; color: #F2EEFB; border: 1px solid #3A3450;
    border-radius: 8px; padding: 6px 10px; min-height: 20px;
    font-family: 'Space Grotesk','Segoe UI'; font-size: 10pt;
}
QComboBox:hover, QSpinBox:hover { border: 1px solid #8B5CF6; }
QComboBox QAbstractItemView {
    background: #211E2C; color: #F2EEFB; selection-background-color: #8B5CF6;
    border: 1px solid #3A3450; outline: none;
}
QCheckBox { color: #E7E3F1; font-family: 'Space Grotesk','Segoe UI'; font-size: 10pt; spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid #3A3450; background: #211E2C; }
QCheckBox::indicator:checked { background: #8B5CF6; border: 1px solid #8B5CF6; }
QFrame#sep { background: #2A2638; max-height: 1px; border: none; }
QPushButton#save {
    background: #8B5CF6; color: white; border: none; border-radius: 10px;
    padding: 9px 22px; font-family: 'Space Grotesk','Segoe UI'; font-size: 10pt; font-weight: 600;
}
QPushButton#save:hover { background: #A855F7; }
QPushButton#cancel {
    background: transparent; color: #9A93AE; border: 1px solid #3A3450;
    border-radius: 10px; padding: 9px 22px; font-family: 'Space Grotesk','Segoe UI'; font-size: 10pt;
}
QPushButton#cancel:hover { color: #E7E3F1; border: 1px solid #8B5CF6; }
"""

class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, on_apply):
        super().__init__()
        self.cfg = cfg
        self.on_apply = on_apply
        self.setWindowTitle("LouLLabs STT - Parametres")
        self.setWindowIcon(app_icon())
        self.setStyleSheet(SETTINGS_QSS)
        self.setMinimumWidth(420)
        self._build()

    def _sep(self):
        f = QFrame(); f.setObjectName("sep"); f.setFixedHeight(1)
        return f

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 22)
        root.setSpacing(14)

        title = QLabel("Parametres"); title.setObjectName("title")
        root.addWidget(title)
        root.addWidget(self._sep())

        grid = QGridLayout()
        grid.setVerticalSpacing(12)
        grid.setHorizontalSpacing(16)
        r = 0

        # Touche
        grid.addWidget(QLabel("Touche push-to-talk"), r, 0)
        self.cb_key = QComboBox()
        for k in KEY_VK:
            self.cb_key.addItem(k.upper().replace("_", " "), k)
        self.cb_key.setCurrentIndex(max(0, list(KEY_VK).index(self.cfg["hotkey"])
                                        if self.cfg["hotkey"] in KEY_VK else 0))
        grid.addWidget(self.cb_key, r, 1); r += 1

        # Langue
        grid.addWidget(QLabel("Langue"), r, 0)
        self.cb_lang = QComboBox()
        for label, code in LANG_CHOICES:
            self.cb_lang.addItem(label, code)
        idx = next((i for i, (_, c) in enumerate(LANG_CHOICES) if c == self.cfg["language"]), 0)
        self.cb_lang.setCurrentIndex(idx)
        grid.addWidget(self.cb_lang, r, 1); r += 1

        # Modele (3 choix exposes ; autres modeles = config.json avance)
        grid.addWidget(QLabel("Modele"), r, 0)
        self.cb_model = QComboBox()
        for mid, friendly, note in RECOMMENDED_MODELS:
            self.cb_model.addItem(f"{friendly}   ·   {mid} ({note})", mid)
        cur = self.cfg.get("model", "large-v3-turbo")
        if cur not in [m for m, _, _ in RECOMMENDED_MODELS]:
            self.cb_model.addItem(f"{cur}  (avance)", cur)
        mdl_idx = next((i for i in range(self.cb_model.count())
                        if self.cb_model.itemData(i) == cur), 0)
        self.cb_model.setCurrentIndex(mdl_idx)
        grid.addWidget(self.cb_model, r, 1); r += 1

        # Micro
        grid.addWidget(QLabel("Microphone"), r, 0)
        self.cb_mic = QComboBox()
        self.cb_mic.addItem("Peripherique par defaut", None)
        try:
            for i, d in enumerate(sd.query_devices()):
                if d.get("max_input_channels", 0) > 0:
                    self.cb_mic.addItem(d["name"][:42], i)
        except Exception:
            pass
        want = self.cfg.get("mic_device")
        mic_idx = next((i for i in range(self.cb_mic.count())
                        if self.cb_mic.itemData(i) == want), 0)
        self.cb_mic.setCurrentIndex(mic_idx)
        grid.addWidget(self.cb_mic, r, 1); r += 1

        # Methode d'insertion du texte
        grid.addWidget(QLabel("Insertion du texte"), r, 0)
        self.cb_insert = QComboBox()
        self.cb_insert.addItem("Frappe directe (fiable)", "frappe")
        self.cb_insert.addItem("Presse-papier (Ctrl+V)", "collage")
        ins_idx = 0 if self.cfg.get("insert_method", "frappe") != "collage" else 1
        self.cb_insert.setCurrentIndex(ins_idx)
        grid.addWidget(self.cb_insert, r, 1); r += 1

        # Mode de fonctionnement (aucune technique exposee)
        grid.addWidget(QLabel("Mode"), r, 0)
        self.cb_mode = QComboBox()
        for label, val in MODE_CHOICES:
            self.cb_mode.addItem(label, val)
        cur_mode = self.cfg.get("mode", "auto")
        mode_idx = next((i for i, (_, v) in enumerate(MODE_CHOICES) if v == cur_mode), 0)
        self.cb_mode.setCurrentIndex(mode_idx)
        grid.addWidget(self.cb_mode, r, 1); r += 1

        # Acceleration (abstraite : l'utilisateur ne voit jamais CPU/GPU/CUDA)
        grid.addWidget(QLabel("Acceleration"), r, 0)
        acc = QLabel("Automatique  (processeur)")
        acc.setObjectName("hint")
        grid.addWidget(acc, r, 1); r += 1

        root.addLayout(grid)

        hint = QLabel("Automatique : equilibre. Performance : pret instantanement, "
                      "consomme plus. Economie : libere les ressources au repos.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addWidget(self._sep())

        # Cases a cocher
        self.chk_start = QCheckBox("Lancer au demarrage de Windows")
        self.chk_start.setChecked(bool(self.cfg.get("start_with_windows", False)))
        root.addWidget(self.chk_start)

        self.chk_clip = QCheckBox("Restaurer le presse-papier apres collage")
        self.chk_clip.setChecked(bool(self.cfg.get("restore_clipboard", True)))
        root.addWidget(self.chk_clip)

        # Recalibration micro (bruit de fond -> seuil de silence)
        cal_row = QHBoxLayout()
        self.btn_cal = QPushButton("Recalibrer le micro"); self.btn_cal.setObjectName("cancel")
        self.btn_cal.clicked.connect(self._recalibrate)
        self.lbl_cal = QLabel(f"seuil actuel : {self.cfg.get('silence_rms', 0.006)}")
        self.lbl_cal.setObjectName("hint")
        cal_row.addWidget(self.btn_cal); cal_row.addWidget(self.lbl_cal); cal_row.addStretch(1)
        root.addLayout(cal_row)

        root.addWidget(self._sep())

        # Boutons
        btns = QHBoxLayout(); btns.addStretch(1)
        b_cancel = QPushButton("Annuler"); b_cancel.setObjectName("cancel")
        b_cancel.clicked.connect(self.reject)
        b_save = QPushButton("Enregistrer"); b_save.setObjectName("save")
        b_save.clicked.connect(self._save)
        btns.addWidget(b_cancel); btns.addWidget(b_save)
        root.addLayout(btns)

    def _recalibrate(self):
        self.btn_cal.setText("Mesure du bruit...")
        self.btn_cal.setEnabled(False)
        QApplication.processEvents()
        cal = calibrate_mic(self.cb_mic.currentData())
        if cal:
            self.cfg["silence_rms"] = cal[0]
            self.lbl_cal.setText(f"calibre : seuil {cal[0]} (bruit {cal[1]})")
        else:
            self.lbl_cal.setText("calibration impossible")
        self.btn_cal.setText("Recalibrer le micro")
        self.btn_cal.setEnabled(True)

    def _save(self):
        self.cfg["hotkey"] = self.cb_key.currentData()
        self.cfg["language"] = self.cb_lang.currentData()
        self.cfg["model"] = self.cb_model.currentData()
        self.cfg["mic_device"] = self.cb_mic.currentData()
        self.cfg["insert_method"] = self.cb_insert.currentData()
        self.cfg["mode"] = self.cb_mode.currentData()
        self.cfg["start_with_windows"] = self.chk_start.isChecked()
        self.cfg["restore_clipboard"] = self.chk_clip.isChecked()
        save_config(self.cfg)
        self.on_apply(self.cfg)
        self.accept()


# ═══════════════════════════════════════════════════════════════
#  ECRAN DE BIENVENUE (1er lancement) — detection seule, sans benchmark impose
# ═══════════════════════════════════════════════════════════════

class WelcomeDialog(QDialog):
    def __init__(self, cfg: dict, calibration=None):
        super().__init__()
        self.cfg = cfg
        self.calibration = calibration   # (seuil, bruit) ou None
        self.setWindowTitle("Bienvenue - LouLLabs STT")
        self.setWindowIcon(app_icon())
        self.setStyleSheet(SETTINGS_QSS)
        self.setMinimumWidth(460)
        self._build()

    def _row(self, emoji, label, value):
        h = QHBoxLayout()
        a = QLabel(f"{emoji}  {label}"); a.setMinimumWidth(150)
        b = QLabel(value); b.setObjectName("hint"); b.setWordWrap(True)
        h.addWidget(a); h.addStretch(1); h.addWidget(b, 1)
        return h

    def _sep(self):
        f = QFrame(); f.setObjectName("sep"); f.setFixedHeight(1)
        return f

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 22); root.setSpacing(12)

        title = QLabel("Bienvenue dans LouLLabs STT"); title.setObjectName("title")
        root.addWidget(title)
        sub = QLabel("Dictee vocale 100% locale. Voici votre configuration :")
        sub.setObjectName("hint"); root.addWidget(sub)
        root.addWidget(self._sep())

        mic = detect_mic() or "peripherique par defaut"
        gpu = detect_gpu()
        total, avail = detect_ram_gb()
        model_id = self.cfg.get("model", "large-v3-turbo")
        friendly = next((f for m, f, _ in RECOMMENDED_MODELS if m == model_id), model_id)

        acc = f"Automatique  —  {gpu} detecte" if gpu else "Automatique  —  processeur (CPU)"
        ram = f"{avail:.1f} Go dispo / {total:.1f} Go" if total else "—"

        root.addLayout(self._row("🎙️", "Microphone", str(mic)[:46]))
        root.addLayout(self._row("⚡", "Acceleration", acc[:64]))
        root.addLayout(self._row("🧠", "Memoire", ram))
        root.addLayout(self._row("🧩", "Modele", f"{friendly}  ({model_id})"))
        if self.calibration:
            root.addLayout(self._row("🎚️", "Micro calibre",
                                     f"seuil de silence auto : {self.calibration[0]}"))

        root.addWidget(self._sep())
        note = QLabel("Le modele (~1,5 Go) se telecharge a votre premiere dictee, "
                      "puis tout fonctionne hors-ligne.\n"
                      "Maintenez F8, parlez, relachez : le texte s'ecrit.")
        note.setObjectName("hint"); note.setWordWrap(True); root.addWidget(note)

        btns = QHBoxLayout(); btns.addStretch(1)
        b = QPushButton("Commencer"); b.setObjectName("save")
        b.clicked.connect(self.accept)
        btns.addWidget(b)
        root.addLayout(btns)


# ═══════════════════════════════════════════════════════════════
#  POINT D'ENTREE
# ═══════════════════════════════════════════════════════════════

def main():
    print(f"""
  ========================================================
       LouLLabs STT — Speech to Text  v{APP_VERSION}
       Maintenez une touche  ->  Parlez  ->  Relachez  ->  Colle
       100% local  -  Whisper  -  Input Win32 natif
  ========================================================
    """)

    cfg = load_config()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)

    hotkey_label = cfg["hotkey"].upper().replace("_", " ")
    overlay = GlassOverlay(hotkey_label=hotkey_label)
    engine = STTEngine(overlay, cfg)
    watcher = HotkeyWatcher(engine)

    # Applique l'etat "demarrage Windows" au lancement
    set_start_with_windows(bool(cfg.get("start_with_windows", False)))

    # Mode Performance : precharge le modele au demarrage (pret instantanement)
    if cfg.get("mode") == "performance":
        engine.request_model()

    # ── System tray ──
    tray = QSystemTrayIcon(app)
    tray.setIcon(app_icon())
    tray.setToolTip(f"LouLLabs STT - {hotkey_label} pour parler")

    menu = QMenu()
    menu.setStyleSheet("""
        QMenu { background: rgba(23,21,31,244); border: 1px solid rgba(168,85,247,90);
                border-radius: 8px; padding: 5px; color: white;
                font-family: 'Space Grotesk','Segoe UI'; font-size: 10pt; }
        QMenu::item { padding: 7px 26px 7px 14px; border-radius: 5px; }
        QMenu::item:selected { background: rgba(139,92,246,130); }
        QMenu::item:disabled { color: rgba(255,255,255,110); }
        QMenu::separator { height: 1px; background: rgba(255,255,255,22); margin: 5px 8px; }
    """)

    act_status = menu.addAction("LouLLabs STT"); act_status.setEnabled(False)
    menu.addSeparator()
    act_hint = menu.addAction(f"{hotkey_label} : maintenir pour parler")
    act_hint.setEnabled(False)
    menu.addSeparator()
    act_settings = menu.addAction("Parametres...")
    act_quit = menu.addAction("Quitter")
    tray.setContextMenu(menu)
    tray.show()

    # ── Ouverture des reglages ──
    def apply_cfg(new_cfg):
        label = new_cfg["hotkey"].upper().replace("_", " ")
        overlay.set_hotkey_label(label)
        watcher.set_hotkey(new_cfg["hotkey"])
        tray.setToolTip(f"LouLLabs STT - {label} pour parler")
        act_hint.setText(f"{label} : maintenir pour parler")
        set_start_with_windows(bool(new_cfg.get("start_with_windows", False)))
        engine.touch()

    def open_settings():
        dlg = SettingsDialog(cfg, apply_cfg)
        dlg.exec()

    act_settings.triggered.connect(open_settings)

    def on_tray_activated(reason):
        if reason == QSystemTrayIcon.DoubleClick:
            open_settings()
    tray.activated.connect(on_tray_activated)

    # ── Timer de dechargement RAM (verifie toutes les 30 s) ──
    idle_timer = QTimer()
    idle_timer.timeout.connect(engine.unload_model_if_idle)
    idle_timer.start(30_000)

    # ── Quitter proprement ──
    def quitter():
        print("\n  Au revoir !")
        engine.stop()
        tray.hide()
        app.quit()
    act_quit.triggered.connect(quitter)

    # ── Ecran de bienvenue + calibration micro (une seule fois) ──
    if not cfg.get("first_run_done"):
        cal = calibrate_mic(cfg.get("mic_device"))   # ~1 s, mesure le bruit de fond
        if cal:
            cfg["silence_rms"] = cal[0]
            print(f"  Micro calibre : bruit={cal[1]}, seuil de silence={cal[0]}")
        try:
            WelcomeDialog(cfg, calibration=cal).exec()
        except Exception as e:
            print(f"  Bienvenue : {e}")
        cfg["first_run_done"] = True
        save_config(cfg)

    # ── Message de bienvenue ──
    QTimer.singleShot(400, overlay.signals.show_ready.emit)
    print(f"  Pret. Maintenez [{hotkey_label}] pour dicter. "
          f"Clic droit sur l'icone pour les reglages.\n")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
