"""Captures d'écran (mss) ou images d'exemple (mode test), et préparation pour l'envoi au modèle."""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from PIL import Image

log = logging.getLogger("compagnon")

EXTENSIONS_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class CaptureEcran:
    """Capture l'écran choisi (1 = écran principal, 0 = tous les écrans réunis)."""

    def __init__(self, ecran: int = 1):
        self.ecran = ecran

    def capturer(self) -> Image.Image:
        import mss  # import tardif : mss n'est utile qu'en mode réel

        # Un objet mss par capture : il n'est pas partageable entre threads.
        with mss.mss() as sct:
            ecrans = sct.monitors
            index = self.ecran if 0 <= self.ecran < len(ecrans) else 1
            brut = sct.grab(ecrans[index])
            return Image.frombytes("RGB", brut.size, brut.bgra, "raw", "BGRX")

    def description(self) -> str:
        return f"écran {self.ecran}"


class CaptureTest:
    """Mode test : renvoie tour à tour les images d'un dossier au lieu de vraies captures.

    Le dossier est relu à chaque capture : on peut y ajouter ou retirer des images pendant que ça tourne.
    """

    def __init__(self, dossier: Path):
        self.dossier = dossier
        self._index = 0

    def _fichiers(self) -> list[Path]:
        if not self.dossier.is_dir():
            return []
        return sorted(p for p in self.dossier.iterdir() if p.suffix.lower() in EXTENSIONS_IMAGES)

    def capturer(self) -> Image.Image:
        fichiers = self._fichiers()
        if not fichiers:
            raise FileNotFoundError(f"aucune image dans {self.dossier}")
        fichier = fichiers[self._index % len(fichiers)]
        self._index += 1
        log.info("[Test]   image utilisée comme capture : %s", fichier.name)
        with Image.open(fichier) as img:
            return img.convert("RGB")

    def description(self) -> str:
        return f"images de {self.dossier}"


def preparer_image(image: Image.Image, largeur: int = 768, qualite: int = 70) -> str:
    """Réduit l'image (largeur max), la compresse en JPEG et renvoie une URL data: base64."""
    if image.width > largeur:
        hauteur = round(image.height * largeur / image.width)
        image = image.resize((largeur, hauteur), Image.LANCZOS)
    tampon = io.BytesIO()
    image.convert("RGB").save(tampon, format="JPEG", quality=qualite, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(tampon.getvalue()).decode("ascii")
