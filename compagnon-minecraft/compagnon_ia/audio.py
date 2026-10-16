"""Micro : enregistrement push-to-talk (sounddevice) et encodage pour Whisper."""

from __future__ import annotations

import io
import logging
import threading
from collections import deque

import numpy as np

log = logging.getLogger("compagnon")


def peripherique(reglage: str):
    """Réglage de config -> argument « device » de sounddevice (None = défaut de Windows)."""
    reglage = (reglage or "").strip()
    if not reglage:
        return None
    return int(reglage) if reglage.isdigit() else reglage


class Micro:
    """Flux micro ouvert en permanence ; on ne garde le son que pendant l'appui sur la touche.

    Le flux reste ouvert pour démarrer instantanément, et on conserve un court « pré-enregistrement »
    (0,3 s) pour ne pas couper le premier mot si on parle en même temps qu'on appuie.
    """

    BLOC = 0.05  # secondes par bloc audio

    def __init__(self, reglage_peripherique: str = "", frequence: int = 16_000, preroll: float = 0.3):
        self.peripherique = peripherique(reglage_peripherique)
        self.frequence = frequence
        self._preroll = deque(maxlen=max(1, round(preroll / self.BLOC)))
        self._blocs: list[np.ndarray] = []
        self._enregistre = False
        self._verrou = threading.Lock()
        self._flux = None

    def demarrer(self) -> None:
        import sounddevice as sd

        try:
            self._ouvrir(sd, self.frequence)
        except Exception:
            # Certains micros refusent 16 kHz : on prend leur fréquence native (Groq rééchantillonne).
            infos = sd.query_devices(self.peripherique, "input")
            self._ouvrir(sd, int(infos["default_samplerate"]))
        log.debug("Micro ouvert à %d Hz", self.frequence)

    def _ouvrir(self, sd, frequence: int) -> None:
        flux = sd.InputStream(
            samplerate=frequence, channels=1, dtype="int16", device=self.peripherique,
            blocksize=int(frequence * self.BLOC), callback=self._rappel,
        )
        flux.start()
        self._flux, self.frequence = flux, frequence

    def _rappel(self, donnees, _frames, _temps, _statut) -> None:
        bloc = donnees[:, 0].copy()
        with self._verrou:
            if self._enregistre:
                self._blocs.append(bloc)
            else:
                self._preroll.append(bloc)

    def commencer(self) -> None:
        with self._verrou:
            self._blocs = list(self._preroll)
            self._enregistre = True

    def arreter(self) -> np.ndarray:
        """Arrête l'enregistrement et renvoie les échantillons (int16 mono)."""
        with self._verrou:
            self._enregistre = False
            blocs, self._blocs = self._blocs, []
        if not blocs:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(blocs)

    def fermer(self) -> None:
        if self._flux is not None:
            self._flux.stop()
            self._flux.close()
            self._flux = None


def niveau_crete(echantillons: np.ndarray) -> float:
    """Volume maximal entre 0 et 1 (pour repérer un micro muet)."""
    if echantillons.size == 0:
        return 0.0
    return float(np.abs(echantillons.astype(np.int32)).max()) / 32768.0


def encoder_flac(echantillons: np.ndarray, frequence: int) -> bytes:
    """Encode en FLAC (sans perte, deux fois plus léger que du WAV : envoi plus rapide)."""
    import soundfile as sf

    tampon = io.BytesIO()
    sf.write(tampon, echantillons, frequence, format="FLAC", subtype="PCM_16")
    return tampon.getvalue()
