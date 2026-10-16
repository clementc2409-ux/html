"""Captures d'écran (mss) ou images d'exemple (mode test), et préparation pour l'envoi au modèle."""

from __future__ import annotations

import base64
import io
import logging
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

log = logging.getLogger("compagnon")

EXTENSIONS_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class CaptureEcran:
    """Capture la fenêtre de Minecraft si on la trouve (Windows), sinon l'écran choisi
    (1 = écran principal, 0 = tous les écrans réunis).

    Ne capturer que la fenêtre évite d'envoyer le bureau, la barre des tâches ou le terminal autour du jeu
    (le modèle les prenait pour des menus), et fonctionne quel que soit l'écran où se trouve le jeu."""

    def __init__(self, ecran: int = 1, motif_fenetre: str = "Minecraft", suivre_fenetre: bool = True):
        self.ecran = ecran
        self.motif_fenetre = motif_fenetre
        self.suivre_fenetre = suivre_fenetre
        self._derniere_source: str | None = None

    def capturer(self) -> Image.Image:
        import mss  # import tardif : mss n'est utile qu'en mode réel

        zone = zone_fenetre_jeu(self.motif_fenetre) if self.suivre_fenetre else None
        # Un objet mss par capture : il n'est pas partageable entre threads.
        with mss.mss() as sct:
            brut = None
            if zone:
                try:
                    brut = sct.grab(zone)
                except Exception:  # fenêtre en partie hors de l'écran, etc.
                    zone = None
            if brut is None:
                ecrans = sct.monitors
                brut = sct.grab(ecrans[self.ecran if 0 <= self.ecran < len(ecrans) else 1])
        source = f"fenêtre de Minecraft ({brut.size[0]}×{brut.size[1]})" if zone else f"écran {self.ecran}"
        if source != self._derniere_source:
            log.info("[Regard] capture de : %s", source)
            self._derniere_source = source
        return Image.frombytes("RGB", brut.size, brut.bgra, "raw", "BGRX")

    def description(self) -> str:
        if self.suivre_fenetre:
            return f"fenêtre de Minecraft (sinon écran {self.ecran})"
        return f"écran {self.ecran}"


class CaptureTest:
    """Mode test : renvoie tour à tour les images d'un dossier au lieu de vraies captures.

    Le dossier est relu à chaque capture : on peut y ajouter ou retirer des images pendant que ça tourne.
    """

    def __init__(self, dossier: Path, duree_par_image: float = 0.0):
        self.dossier = dossier
        self.duree_par_image = duree_par_image  # 0 = image suivante à chaque capture
        self._index = 0
        self._debut = time.monotonic()
        self._derniere: str | None = None

    def _fichiers(self) -> list[Path]:
        if not self.dossier.is_dir():
            return []
        return sorted(p for p in self.dossier.iterdir() if p.suffix.lower() in EXTENSIONS_IMAGES)

    def capturer(self) -> Image.Image:
        fichiers = self._fichiers()
        if not fichiers:
            raise FileNotFoundError(f"aucune image dans {self.dossier}")
        if self.duree_par_image > 0:
            self._index = int((time.monotonic() - self._debut) / self.duree_par_image)
        fichier = fichiers[self._index % len(fichiers)]
        if self.duree_par_image <= 0:
            self._index += 1
        if self.duree_par_image <= 0 or fichier.name != self._derniere:
            log.info("[Test]   image utilisée comme capture : %s", fichier.name)
        self._derniere = fichier.name
        with Image.open(fichier) as img:
            return img.convert("RGB")

    def description(self) -> str:
        return f"images de {self.dossier}"


def encoder_jpeg(image: Image.Image, largeur: int = 1280, qualite: int = 85) -> bytes:
    """Réduit l'image (largeur max) et la compresse en JPEG."""
    if image.width > largeur:
        hauteur = round(image.height * largeur / image.width)
        image = image.resize((largeur, hauteur), Image.LANCZOS)
    tampon = io.BytesIO()
    image.convert("RGB").save(tampon, format="JPEG", quality=qualite, optimize=True)
    return tampon.getvalue()


def url_data(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


def preparer_image(image: Image.Image, largeur: int = 1280, qualite: int = 85) -> str:
    """Image -> URL data: base64 prête à envoyer au modèle."""
    return url_data(encoder_jpeg(image, largeur, qualite))


# --- Comparaison d'images et détection « est-ce que je joue ? » -------------------------------------

def empreinte(image: Image.Image) -> np.ndarray:
    """Version minuscule en couleur (64×36), suffisante pour savoir si l'écran a changé."""
    return np.asarray(image.convert("RGB").resize((64, 36), Image.BILINEAR), dtype=np.float32)


def difference(a: np.ndarray, b: np.ndarray) -> float:
    """Différence moyenne entre deux empreintes, de 0 (identiques) à 1 (tout a changé)."""
    return float(np.abs(a - b).mean()) / 255.0


CLASSE_GLFW = "GLFW30"  # classe Windows des fenêtres GLFW/LWJGL, donc de Minecraft Java


def est_fenetre_jeu(titre: str, classe: str, motif: str) -> bool:
    """Reconnaît la fenêtre du jeu, mais pas le launcher ni un dossier nommé « compagnon-minecraft »."""
    titre = (titre or "").strip().lower()
    motif = (motif or "").strip().lower()
    if "launcher" in titre:
        return False
    if classe == CLASSE_GLFW and (not motif or motif in titre):
        return True
    return bool(motif) and titre.startswith(motif)


class _Win32:
    """Accès aux quelques fonctions Windows utiles (instance privée de user32, pour ne gêner personne)."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes as wt

        self.ctypes, self.wt = ctypes, wt
        activer_dpi(ctypes)
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetForegroundWindow.restype = wt.HWND
        u.GetWindowTextLengthW.argtypes = [wt.HWND]
        u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.IsWindowVisible.argtypes = [wt.HWND]
        u.IsIconic.argtypes = [wt.HWND]
        u.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
        u.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
        self.ENUMERATION = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        u.EnumWindows.argtypes = [self.ENUMERATION, wt.LPARAM]
        self.u = u

    def titre(self, fenetre) -> str:
        n = self.u.GetWindowTextLengthW(fenetre)
        tampon = self.ctypes.create_unicode_buffer(n + 1)
        self.u.GetWindowTextW(fenetre, tampon, n + 1)
        return tampon.value

    def classe(self, fenetre) -> str:
        tampon = self.ctypes.create_unicode_buffer(256)
        self.u.GetClassNameW(fenetre, tampon, 256)
        return tampon.value

    def fenetres_visibles(self) -> list:
        trouvees = []

        def rappel(fenetre, _):
            if self.u.IsWindowVisible(fenetre):
                trouvees.append(fenetre)
            return True

        self.u.EnumWindows(self.ENUMERATION(rappel), 0)
        return trouvees

    def zone_client(self, fenetre) -> dict | None:
        """Zone intérieure de la fenêtre (sans barre de titre ni bordures), en pixels écran."""
        if self.u.IsIconic(fenetre):
            return None
        rect, coin = self.wt.RECT(), self.wt.POINT(0, 0)
        if not self.u.GetClientRect(fenetre, self.ctypes.byref(rect)):
            return None
        if not self.u.ClientToScreen(fenetre, self.ctypes.byref(coin)):
            return None
        largeur, hauteur = rect.right - rect.left, rect.bottom - rect.top
        if largeur < 200 or hauteur < 150:
            return None
        return {"left": coin.x, "top": coin.y, "width": largeur, "height": hauteur}


def activer_dpi(ctypes) -> None:
    """Coordonnées en vrais pixels même avec une mise à l'échelle Windows (125 %, 150 %…)."""
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_WIN32: _Win32 | None = None
_WIN32_ESSAYE = False


def _win32() -> _Win32 | None:
    global _WIN32, _WIN32_ESSAYE
    if not _WIN32_ESSAYE:
        _WIN32_ESSAYE = True
        if sys.platform == "win32":
            try:
                _WIN32 = _Win32()
            except Exception as e:
                log.debug("API Windows indisponible : %s", e)
    return _WIN32


def fenetre_jeu(motif: str):
    """La fenêtre de Minecraft : celle au premier plan si c'est le jeu, sinon la première trouvée."""
    w = _win32()
    if w is None:
        return None
    try:
        active = w.u.GetForegroundWindow()
        if active and est_fenetre_jeu(w.titre(active), w.classe(active), motif):
            return active
        for fenetre in w.fenetres_visibles():
            if est_fenetre_jeu(w.titre(fenetre), w.classe(fenetre), motif):
                return fenetre
    except Exception as e:
        log.debug("Recherche de la fenêtre du jeu impossible : %s", e)
    return None


def zone_fenetre_jeu(motif: str) -> dict | None:
    fenetre = fenetre_jeu(motif)
    if fenetre is None:
        return None
    try:
        return _win32().zone_client(fenetre)
    except Exception:
        return None


def jeu_au_premier_plan(motif: str) -> bool:
    """Vrai si la fenêtre active est Minecraft (ou si on ne peut pas le savoir).

    Minecraft se met en pause tout seul quand il perd le focus : inutile de commenter le bureau.
    """
    if not motif.strip():
        return True
    w = _win32()
    if w is None:
        return True
    try:
        active = w.u.GetForegroundWindow()
        return bool(active) and est_fenetre_jeu(w.titre(active), w.classe(active), motif)
    except Exception:
        return True
