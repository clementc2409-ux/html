"""Boucle principale : relie micro, touche, captures, cerveau et voix, et gère les tours de parole."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from dataclasses import dataclass, field

from PIL import Image

from .audio import Micro, encoder_flac, niveau_crete
from .budget import Budget
from .capture import CaptureEcran, CaptureTest, preparer_image
from .cerveau import Cerveau, ErreurGroq, LimiteGroq, charger_systeme
from .config import RACINE, Config
from .phrases import DecoupeurPhrases, est_silence
from .touches import ToucheParler
from .voix import Lecteur, Parole, Synthese

log = logging.getLogger("compagnon")

# Plus le chiffre est petit, plus la demande est prioritaire.
PRIORITE = {"voix": 0, "chat": 0, "evenement": 1, "spontane": 2}
DUREE_MIN_VOIX = 0.4      # secondes : en dessous, appui accidentel
NIVEAU_MIN_VOIX = 0.01    # volume crête : en dessous, micro coupé / rien dit


@dataclass
class Demande:
    genre: str                       # "voix", "chat", "evenement" ou "spontane"
    texte: str = ""
    image: Image.Image | None = None
    t0: float = field(default_factory=time.perf_counter)


def formuler(demande: Demande) -> str:
    """Texte envoyé au modèle pour ce tour (l'étiquette lui dit d'où ça vient)."""
    if demande.genre == "voix":
        return f"[Voix] {demande.texte}"
    if demande.genre == "chat":
        return f"[Chat] {demande.texte}"
    if demande.genre == "evenement":
        return f"[Événement] {demande.texte}"
    return ("[Coup d'œil] Capture automatique pendant qu'il joue. Réagis seulement si ça vaut vraiment "
            "le coup ; sinon réponds exactement SILENCE.")


class Compagnon:
    def __init__(self, cfg: Config, *, mode_test: bool = False,
                 cerveau=None, synthese=None, lecteur=None, micro=None, capture=None):
        self.cfg = cfg
        self.mode_test = mode_test
        self.budget = Budget(cfg.jetons_par_jour, cfg.jetons_spontanes_par_heure,
                             RACINE / ".consommation_groq.json")
        self.cerveau = cerveau or Cerveau(cfg, charger_systeme(cfg), self.budget)
        self.synthese = synthese or Synthese(cfg.voix, cfg.debit, cfg.volume)
        self.lecteur = lecteur or Lecteur(cfg.sortie_audio)
        self.micro = micro if micro is not None else Micro(cfg.micro)
        if capture is None:
            capture = CaptureTest(RACINE / "exemples" / "images") if mode_test else CaptureEcran(cfg.ecran)
        self.capture = capture
        self.touche: ToucheParler | None = None
        self.micro_actif = False

        self._boucle: asyncio.AbstractEventLoop | None = None
        self._tour: asyncio.Task | None = None
        self._genre_tour: str | None = None
        self._tache_voix: asyncio.Task | None = None
        self._enregistre = False
        self._taches: list[asyncio.Task] = []

    # ------------------------------------------------------------------ démarrage / arrêt
    async def tourner(self) -> None:
        self._boucle = asyncio.get_running_loop()
        await self._verifier_groq()
        try:
            self.lecteur.demarrer()
        except Exception as e:
            log.error("[Voix]   sortie audio indisponible : %s (les réponses s'afficheront seulement ici)", e)
        self._demarrer_micro()
        threading.Thread(target=self._lire_console, daemon=True).start()
        self._afficher_accueil()
        try:
            await asyncio.Event().wait()  # tout se passe dans les rappels et les tâches
        finally:
            self.arreter()

    def arreter(self) -> None:
        for tache in [*self._taches, self._tour, self._tache_voix]:
            if tache is not None:
                tache.cancel()
        if self.touche:
            self.touche.arreter()
        with contextlib.suppress(Exception):
            self.micro.fermer()
        with contextlib.suppress(Exception):
            self.lecteur.fermer()

    async def _verifier_groq(self) -> None:
        """Vérifie la clé et que les modèles configurés existent encore (les noms changent souvent)."""
        try:
            modeles = await self.cerveau.lister_modeles()
        except Exception as e:
            import groq

            if isinstance(e, groq.AuthenticationError):
                raise ErreurGroq("clé API refusée par Groq : vérifie GROQ_API_KEY (ou cle_api dans config.toml).")
            log.warning("[Groq]   impossible de vérifier les modèles (%s). On continue quand même.", e)
            return
        for modele in (self.cfg.modele_transcription, self.cfg.modele_vision):
            if modele not in modeles:
                log.warning("[Groq]   le modèle « %s » n'apparaît pas dans ta liste Groq ! "
                            "Lance « python compagnon.py --modeles » et corrige config.toml.", modele)

    def _demarrer_micro(self) -> None:
        try:
            self.micro.demarrer()
            self.touche = ToucheParler(self.cfg.touche, self._depuis_thread(self._appui),
                                       self._depuis_thread(self._relache))
            self.touche.demarrer()
            self.micro_actif = True
        except Exception as e:
            log.error("[Micro]  push-to-talk indisponible : %s", e)
            log.error("         Tu peux quand même écrire tes phrases dans cette console (puis Entrée).")

    def _afficher_accueil(self) -> None:
        log.info("=" * 70)
        log.info("Compagnon prêt%s.", " (MODE TEST)" if self.mode_test else "")
        if self.micro_actif:
            log.info("  Parler       : maintiens %s", self.touche.description())
        log.info("  Clavier      : tape une phrase ici puis Entrée pour lui parler par écrit")
        log.info("  Modèles      : %s (voix -> texte), %s (vision)",
                 self.cfg.modele_transcription, self.cfg.modele_vision)
        log.info("  Captures     : %s", self.capture.description())
        log.info("  Voix         : %s", self.cfg.voix)
        log.info("  Groq         : %s", self.budget.resume())
        log.info("  Ctrl+C pour quitter.")
        log.info("=" * 70)

    def _depuis_thread(self, fonction):
        """Les rappels de pynput arrivent dans un autre thread : on les renvoie dans la boucle asyncio."""
        def rappel():
            with contextlib.suppress(RuntimeError):  # boucle déjà fermée (arrêt du programme)
                self._boucle.call_soon_threadsafe(fonction)
        return rappel

    def _lire_console(self) -> None:
        while True:
            try:
                ligne = input().strip()
            except (EOFError, KeyboardInterrupt, OSError):
                return
            if ligne:
                with contextlib.suppress(RuntimeError):
                    self._boucle.call_soon_threadsafe(self._phrase_tapee, ligne)

    # ------------------------------------------------------------------ push-to-talk
    def _interrompre(self) -> None:
        """Coupe immédiatement la parole et la réponse en cours."""
        self.lecteur.interrompre()
        for tache in (self._tour, self._tache_voix):
            if tache is not None and not tache.done():
                tache.cancel()

    def _appui(self) -> None:
        if self._enregistre:  # répétition automatique de la touche
            return
        if self.lecteur.parle or (self._tour and not self._tour.done()):
            log.info("[Micro]  (je me tais)")
        self._interrompre()
        self.micro.commencer()
        self._enregistre = True
        log.info("[Micro]  j'écoute…")

    def _relache(self) -> None:
        if not self._enregistre:
            return
        self._enregistre = False
        echantillons = self.micro.arreter()
        self._tache_voix = asyncio.create_task(self._traiter_voix(echantillons, time.perf_counter()))

    async def _traiter_voix(self, echantillons, t0: float) -> None:
        duree = len(echantillons) / self.micro.frequence
        if duree < DUREE_MIN_VOIX:
            log.info("[Micro]  appui trop court (%.1f s), ignoré.", duree)
            return
        if niveau_crete(echantillons) < NIVEAU_MIN_VOIX:
            log.info("[Micro]  je n'ai rien entendu (micro coupé ou mauvais micro ?)")
            return
        # Capture d'écran au moment où tu relâches, pendant que Whisper transcrit.
        tache_image = asyncio.create_task(self._capturer())
        try:
            audio = await asyncio.to_thread(encoder_flac, echantillons, self.micro.frequence)
            texte = await self.cerveau.transcrire(audio)
        except (LimiteGroq, ErreurGroq) as e:
            tache_image.cancel()
            log.error("[Groq]   transcription impossible : %s", e)
            await self._dire_message("Désolé, je n'ai pas pu t'entendre, Groq ne répond pas. Réessaie dans un instant.")
            return
        duree_transcription = time.perf_counter() - t0
        if not texte:
            tache_image.cancel()
            log.info("[Micro]  rien compris (%.1f s d'audio).", duree)
            return
        log.info("[Moi]    %s   (transcription %.2f s)", texte, duree_transcription)
        await self.soumettre(Demande("voix", texte, await tache_image, t0=t0))

    def _phrase_tapee(self, ligne: str) -> None:
        self._interrompre()
        log.info("[Moi]    %s   (écrit dans la console)", ligne)
        self._tache_voix = asyncio.create_task(self.soumettre(Demande("voix", ligne)))

    # ------------------------------------------------------------------ tours de parole
    async def soumettre(self, demande: Demande) -> bool:
        """Lance une réponse. Une demande plus (ou aussi) prioritaire interrompt la réponse en cours ;
        une moins prioritaire attend la fin ; un commentaire spontané ne coupe jamais personne."""
        while self._tour is not None and not self._tour.done():
            if demande.genre == "spontane":
                return False
            if PRIORITE[demande.genre] <= PRIORITE[self._genre_tour]:
                self._tour.cancel()
                self.lecteur.interrompre()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._tour
                break
            await asyncio.wait({self._tour}, timeout=30)
        self._genre_tour = demande.genre
        self._tour = asyncio.create_task(self._jouer_tour(demande))
        return True

    async def _capturer(self) -> Image.Image | None:
        try:
            return await asyncio.to_thread(self.capture.capturer)
        except Exception as e:
            log.warning("[Regard] capture impossible : %s", e)
            return None

    async def _jouer_tour(self, demande: Demande) -> None:
        try:
            await self._repondre(demande)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[Erreur] problème inattendu pendant la réponse")

    async def _repondre(self, demande: Demande) -> None:
        image = demande.image if demande.image is not None else await self._capturer()
        image_url = None
        if image is not None:
            image_url = await asyncio.to_thread(preparer_image, image, self.cfg.largeur_image, self.cfg.qualite_jpeg)
        entree = formuler(demande)
        t0 = demande.t0

        def premier_son():
            log.info("         -> voix lancée %.2f s après ta phrase", time.perf_counter() - t0)

        parole = Parole(self.synthese, self.lecteur, premier_son if demande.genre == "voix" else None)
        decoupeur = DecoupeurPhrases()
        morceaux: list[str] = []
        t_premier_mot = None
        memorise = False
        try:
            async with contextlib.aclosing(self.cerveau.repondre(entree, image_url)) as flux:
                async for morceau in flux:
                    if t_premier_mot is None:
                        t_premier_mot = time.perf_counter() - t0
                    morceaux.append(morceau)
                    for phrase in decoupeur.ajouter(morceau):
                        parole.dire(phrase)
            texte = "".join(morceaux).strip()
            if not texte or est_silence(texte):
                log.info("[Lui]    (ne dit rien)")
                return
            for phrase in decoupeur.terminer():
                parole.dire(phrase)
            self.cerveau.memoriser(entree, texte)
            memorise = True
            details = f"premier mot {t_premier_mot:.2f} s" if t_premier_mot is not None else ""
            if self.cerveau.derniers_jetons:
                details += f", {self.cerveau.derniers_jetons} jetons"
            log.info("[Lui]    %s   (%s)", texte, details)
            await parole.finir()
        except LimiteGroq as e:
            log.error("[Groq]   limite atteinte : %s", e)
            await self._dire_message(self._message_limite(e.attente), parole)
        except ErreurGroq as e:
            log.error("[Groq]   %s", e)
            await self._dire_message("Désolé, je n'arrive pas à joindre Groq.", parole)
        except asyncio.CancelledError:
            partiel = "".join(morceaux).strip()
            if partiel and not memorise:
                self.cerveau.memoriser(entree, partiel + " […interrompu]")
            raise
        finally:
            parole.annuler()

    @staticmethod
    def _message_limite(attente: float | None) -> str:
        if attente and attente > 600:
            return "On a épuisé le quota gratuit de Groq pour le moment. Je reviens dès que possible."
        if attente:
            return f"Groq me demande de souffler un peu. Redemande-moi dans {max(1, round(attente))} secondes."
        return "Groq me demande de souffler un peu. Redemande-moi dans un instant."

    async def _dire_message(self, texte: str, parole: Parole | None = None) -> None:
        """Prononce un court message fixe (sans passer par le modèle)."""
        parole = parole or Parole(self.synthese, self.lecteur)
        try:
            parole.dire(texte)
            await parole.finir()
        finally:
            parole.annuler()
