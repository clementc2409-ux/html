"""Faux composants (micro, voix, cerveau…) pour tester la boucle sans matériel ni réseau."""

import asyncio

import numpy as np
from PIL import Image

from compagnon_ia.config import Config


class FauxCerveau:
    def __init__(self, reponses=None, delai=0.0):
        self.reponses = list(reponses or [])
        self.delai = delai
        self.entrees = []
        self.images = []
        self.historique = []
        self.derniers_jetons = 1000

    async def lister_modeles(self):
        return ["whisper-large-v3-turbo", "qwen/qwen3.8-27b"]

    async def transcrire(self, audio):
        return "Tu vois ce creeper ?"

    async def repondre(self, entree, image_url, spontane=False):
        self.entrees.append(entree)
        self.images.append(image_url)
        reponse = self.reponses.pop(0) if self.reponses else "D'accord."
        for mot in reponse.split(" "):
            await asyncio.sleep(self.delai)
            yield mot + " "

    def memoriser(self, entree, reponse):
        self.historique.append((entree, reponse))


class FausseSynthese:
    def __init__(self):
        self.textes = []

    async def synthetiser(self, texte):
        await asyncio.sleep(0.001)
        self.textes.append(texte)
        return np.ones(240, dtype=np.float32)


class FauxLecteur:
    def __init__(self, duree=0.0):
        self.duree = duree
        self.joue = []
        self.interruptions = 0
        self._fin = 0.0

    def demarrer(self):
        pass

    def jouer(self, pcm):
        self.joue.append(pcm)
        boucle = asyncio.get_running_loop()
        self._fin = max(self._fin, boucle.time()) + self.duree

    def interrompre(self):
        self.interruptions += 1
        self._fin = 0.0

    @property
    def parle(self):
        try:
            return asyncio.get_running_loop().time() < self._fin
        except RuntimeError:
            return False

    async def attendre_fin(self):
        while self.parle:
            await asyncio.sleep(0.005)

    def fermer(self):
        pass


class FauxMicro:
    frequence = 16_000

    def __init__(self):
        self.enregistre = False

    def demarrer(self):
        pass

    def commencer(self):
        self.enregistre = True

    def arreter(self):
        self.enregistre = False
        t = np.arange(16_000) / 16_000
        return (np.sin(2 * np.pi * 220 * t) * 8000).astype(np.int16)

    def fermer(self):
        pass


class FausseCapture:
    def __init__(self, couleurs=((40, 120, 40),)):
        self.couleurs = list(couleurs)
        self.n = 0

    def capturer(self):
        couleur = self.couleurs[min(self.n, len(self.couleurs) - 1)]
        self.n += 1
        return Image.new("RGB", (1280, 720), couleur)

    def description(self):
        return "fausse capture"


def config_test(**reglages) -> Config:
    return Config(cle_api="test", pseudo="Arthur", **reglages)
