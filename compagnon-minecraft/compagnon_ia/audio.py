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

    FREQUENCE_VOULUE = 16_000
    # Entrées qui ne sont pas de vrais micros (elles enregistrent le son de l'ordinateur).
    EXCLUS = ("mixage", "stereo mix", "stéréo", "what u hear", "loopback", "wave out")

    def demarrer(self) -> None:
        """Ouvre le micro choisi (ou celui par défaut). Si le micro par défaut refuse de s'ouvrir,
        essaie les autres micros de l'ordinateur et prévient lequel est utilisé."""
        import sounddevice as sd

        candidats = [self.peripherique]
        if self.peripherique is None:
            candidats += self._autres_micros(sd)
        premiere_erreur = None
        for peripherique in candidats:
            for frequence in (self.FREQUENCE_VOULUE, None):
                try:
                    if frequence is None:
                        # Certains micros refusent 16 kHz : on prend leur fréquence native (Groq rééchantillonne).
                        frequence = int(sd.query_devices(peripherique, "input")["default_samplerate"])
                    self._ouvrir(sd, peripherique, frequence)
                except Exception as e:
                    premiere_erreur = premiere_erreur or e
                    continue
                if peripherique != candidats[0]:
                    log.warning("[Micro]  le micro par défaut ne s'ouvre pas (%s) : j'utilise « %s ».",
                                premiere_erreur, self.nom())
                log.debug("Micro ouvert à %d Hz", self.frequence)
                return
        raise premiere_erreur or RuntimeError("aucun micro trouvé sur cet ordinateur")

    @classmethod
    def _autres_micros(cls, sd) -> list[int]:
        try:
            peripheriques, apis = sd.query_devices(), sd.query_hostapis()
        except Exception:
            return []
        return [i for i, p in enumerate(peripheriques)
                if p["max_input_channels"] > 0
                and "WDM-KS" not in apis[p["hostapi"]]["name"]
                and not any(motif in p["name"].lower() for motif in cls.EXCLUS)]

    def _ouvrir(self, sd, peripherique, frequence: int) -> None:
        flux = sd.InputStream(
            samplerate=frequence, channels=1, dtype="int16", device=peripherique,
            blocksize=int(frequence * self.BLOC), callback=self._rappel,
        )
        flux.start()
        self._flux, self.peripherique, self.frequence = flux, peripherique, frequence

    def nom(self) -> str:
        try:
            import sounddevice as sd

            return sd.query_devices(self.peripherique, "input")["name"]
        except Exception:
            return "?"

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
