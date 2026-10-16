"""Voix du compagnon : synthèse edge-tts, lecteur audio interruptible, prise de parole phrase par phrase."""

from __future__ import annotations

import asyncio
import io
import logging
import threading
from collections import deque
from typing import Callable

import numpy as np

from .audio import peripherique
from .phrases import nettoyer_pour_voix

log = logging.getLogger("compagnon")

FREQUENCE = 24_000  # edge-tts produit du MP3 mono 24 kHz


def reechantillonner(pcm: np.ndarray, source: int, cible: int) -> np.ndarray:
    if source == cible or pcm.size == 0:
        return pcm
    n = max(1, round(pcm.size * cible / source))
    return np.interp(np.linspace(0, pcm.size - 1, n), np.arange(pcm.size), pcm).astype(np.float32)


def decoder_mp3(donnees: bytes) -> np.ndarray:
    import soundfile as sf

    pcm, freq = sf.read(io.BytesIO(donnees), dtype="float32", always_2d=False)
    if pcm.ndim > 1:
        pcm = pcm.mean(axis=1)
    return reechantillonner(pcm.astype(np.float32), freq, FREQUENCE)


class Synthese:
    """Texte -> audio (numpy float32, 24 kHz) avec edge-tts (gratuit, nécessite Internet)."""

    def __init__(self, voix: str, debit: str = "+0%", volume: str = "+0%"):
        self.voix, self.debit, self.volume = voix, debit, volume

    async def synthetiser(self, texte: str) -> np.ndarray:
        import edge_tts

        communication = edge_tts.Communicate(texte, self.voix, rate=self.debit, volume=self.volume)
        morceaux = [m["data"] async for m in communication.stream() if m["type"] == "audio"]
        if not morceaux:
            return np.zeros(0, dtype=np.float32)
        return await asyncio.to_thread(decoder_mp3, b"".join(morceaux))


class Lecteur:
    """Sortie audio ouverte en continu : on y empile des morceaux, et on peut tout couper instantanément."""

    def __init__(self, reglage_peripherique: str = ""):
        self.peripherique = peripherique(reglage_peripherique)
        self.frequence = FREQUENCE
        self._morceaux: deque[np.ndarray] = deque()
        self._position = 0
        self._verrou = threading.Lock()
        self._flux = None

    def demarrer(self) -> None:
        import sounddevice as sd

        try:
            self._ouvrir(sd, FREQUENCE)
        except Exception:
            infos = sd.query_devices(self.peripherique, "output")
            self._ouvrir(sd, int(infos["default_samplerate"]))

    def _ouvrir(self, sd, frequence: int) -> None:
        flux = sd.OutputStream(samplerate=frequence, channels=1, dtype="float32",
                               device=self.peripherique, callback=self._rappel, latency="low")
        flux.start()
        self._flux, self.frequence = flux, frequence

    def _rappel(self, sortie, n, _temps, _statut) -> None:
        i = 0
        with self._verrou:
            while i < n and self._morceaux:
                morceau = self._morceaux[0]
                k = min(len(morceau) - self._position, n - i)
                sortie[i:i + k, 0] = morceau[self._position:self._position + k]
                i += k
                self._position += k
                if self._position >= len(morceau):
                    self._morceaux.popleft()
                    self._position = 0
        if i < n:
            sortie[i:, 0] = 0

    def jouer(self, pcm: np.ndarray) -> None:
        if self._flux is None:  # pas de sortie audio : on n'empile rien (sinon on attendrait pour rien)
            return
        pcm = reechantillonner(pcm, FREQUENCE, self.frequence)
        if pcm.size:
            with self._verrou:
                self._morceaux.append(pcm)

    def interrompre(self) -> None:
        with self._verrou:
            self._morceaux.clear()
            self._position = 0

    @property
    def parle(self) -> bool:
        with self._verrou:
            return bool(self._morceaux)

    async def attendre_fin(self) -> None:
        while self.parle:
            await asyncio.sleep(0.03)

    def fermer(self) -> None:
        if self._flux is not None:
            self._flux.stop()
            self._flux.close()
            self._flux = None


class Parole:
    """Une prise de parole : on donne les phrases au fur et à mesure, elles sont synthétisées
    en parallèle (en avance) et jouées dans l'ordre. annuler() coupe tout immédiatement."""

    def __init__(self, synthese: Synthese, lecteur: Lecteur, sur_premier_son: Callable[[], None] | None = None):
        self.synthese = synthese
        self.lecteur = lecteur
        self.sur_premier_son = sur_premier_son
        self._file: asyncio.Queue = asyncio.Queue()
        self._syntheses: list[asyncio.Task] = []
        self._terminee = False
        self._lecture = asyncio.create_task(self._jouer())

    def dire(self, phrase: str) -> None:
        texte = nettoyer_pour_voix(phrase)
        if texte:
            tache = asyncio.create_task(self.synthese.synthetiser(texte))
            self._syntheses.append(tache)
            self._file.put_nowait(tache)

    async def _jouer(self) -> None:
        while (tache := await self._file.get()) is not None:
            try:
                pcm = await tache
            except asyncio.CancelledError:
                raise
            except Exception as e:  # réseau coupé, voix inconnue…
                log.warning("[Voix]   synthèse impossible : %s", e)
                continue
            if self.sur_premier_son is not None:
                self.sur_premier_son()
                self.sur_premier_son = None
            self.lecteur.jouer(pcm)

    async def finir(self) -> None:
        """Attend que tout ait été synthétisé puis prononcé."""
        self._file.put_nowait(None)
        await self._lecture
        await self.lecteur.attendre_fin()
        self._terminee = True

    def annuler(self) -> None:
        for tache in self._syntheses:
            tache.cancel()
        self._lecture.cancel()
        if not self._terminee:  # ne pas couper une prise de parole suivante
            self.lecteur.interrompre()
