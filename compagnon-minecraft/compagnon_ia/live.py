"""Moteur « Gemini Live » : il regarde l'écran en continu (vidéo), t'écoute et te répond à la voix en direct.

Une seule connexion temps réel avec Google : la vidéo de la fenêtre Minecraft (1 image/s au plus), ta voix
et les événements du jeu partent vers le modèle ; sa voix revient en flux et est jouée aussitôt.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import threading
import time
import unicodedata
from collections import deque

import numpy as np

from . import VERSION
from .audio import Micro
from .capture import CaptureEcran, CaptureTest, difference, empreinte, encoder_jpeg, jeu_au_premier_plan
from .cerveau import GUIDE_ECRAN
from .config import RACINE, Config, chemin_log, lire_texte
from .journal_jeu import PSEUDO_TEST, AnalyseurLog, EvenementJeu, SurveillantLog, fichier_log_test
from .touches import ToucheParler
from .voix import Lecteur

log = logging.getLogger("compagnon")

PAUSE_APRES_PAROLE = 8.0     # secondes de calme après une réponse avant un commentaire spontané
VIDEO_MAX_SANS_ENVOI = 10.0  # même si l'écran ne bouge pas, une image toutes les 10 s
RESOLUTIONS = {"basse": "MEDIA_RESOLUTION_LOW", "moyenne": "MEDIA_RESOLUTION_MEDIUM",
               "haute": "MEDIA_RESOLUTION_HIGH"}

COUP_D_OEIL = ("[Coup d'œil] Regarde l'image la plus récente, elle vient d'arriver. Ne parle que s'il se passe "
               "quelque chose de nouveau ou d'intéressant depuis ton dernier commentaire ; sinon ne dis absolument rien.")
# Temps laissé au modèle pour « voir » la capture fraîche avant de recevoir la question (l'ordre n'est pas garanti).
DELAI_IMAGE = 0.4

CONSIGNES_LIVE = """\
## Ce que tu reçois
- La vidéo de son écran de Minecraft, en continu (environ une image par seconde). Les images arrivent dans l'ordre :
  base-toi TOUJOURS sur la plus récente, c'est ce qu'il voit maintenant ; les précédentes montrent le passé.
  Une capture fraîche arrive juste avant chacune de ses questions.
- Sa voix quand il te parle.
- Des messages texte :
  « [Événement] … » : un événement détecté dans le journal du jeu (mort, progrès…). Réagis-y tout de suite.
  « [Chat] … » ou « [Écrit] … » : il t'écrit. Réponds-lui à voix haute.
  « [Coup d'œil] … » : une invitation à commenter ce qui se passe à l'écran.
Dans le jeu, son pseudo est {pseudo}.

## Commentaires spontanés
Pour un « [Coup d'œil] », regarde les dernières images. Ne parle que s'il se passe quelque chose de nouveau ou
d'intéressant depuis ton dernier commentaire : un danger, une découverte, une construction qui avance, une bêtise à
charrier, une idée pour le royaume. Ne répète jamais un commentaire déjà fait, varie les sujets et le ton. S'il n'y a
rien de neuf, ne dis absolument rien : pas même « rien à signaler ».

## Lire l'écran
{guide_ecran}

## Ta façon de parler
Toujours en français courant, 1 à 2 phrases (3 au maximum). Ne décris pas l'écran comme un commentateur : réagis comme
un compagnon qui joue à côté de lui. Si tu n'es pas sûr de ce que tu vois, ne l'invente pas."""


def construire_consignes(cfg: Config, personnalite: str, chronique: str) -> str:
    parties = [personnalite.strip(),
               CONSIGNES_LIVE.format(pseudo=cfg.pseudo or "inconnu", guide_ecran=GUIDE_ECRAN.strip())]
    if chronique.strip():
        parties.append("## Chronique de la partie (ce qui s'est passé jusqu'ici)\n" + chronique.strip())
    return "\n\n".join(p for p in parties if p)


def construire_config(types, cfg: Config, consignes: str, handle: str | None = None, minimale: bool = False):
    """Réglages de la session. « minimale » retire les options que certains modèles refusent."""
    reglages = {
        "response_modalities": [types.Modality.AUDIO],
        "system_instruction": consignes,
        "speech_config": types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=cfg.gemini_voix))),
        # Transcriptions : pour afficher dans la console ce que tu dis et ce qu'il répond.
        "input_audio_transcription": types.AudioTranscriptionConfig(),
        "output_audio_transcription": types.AudioTranscriptionConfig(),
        # Sans compression, une session audio + vidéo s'arrête au bout de 2 minutes.
        "context_window_compression": types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
        # La connexion est coupée toutes les ~10 minutes : on la reprend avec ce « ticket ».
        "session_resumption": types.SessionResumptionConfig(handle=handle),
    }
    # Toutes les images envoyées depuis la dernière réponse comptent, pas seulement celles reçues pendant que
    # tu parles (sinon il répondait en regardant de vieilles images).
    entree = {"turn_coverage": types.TurnCoverage.TURN_INCLUDES_ALL_INPUT}
    if not cfg.micro_continu:
        # Push-to-talk : c'est nous qui disons quand tu commences et finis de parler.
        entree["automatic_activity_detection"] = types.AutomaticActivityDetection(disabled=True)
    reglages["realtime_input_config"] = types.RealtimeInputConfig(**entree)
    if not minimale:
        if cfg.proactivite:  # lui permet de rester silencieux quand il n'a rien d'intéressant à dire
            reglages["proactivity"] = types.ProactivityConfig(proactive_audio=True)
        reglages["media_resolution"] = getattr(
            types.MediaResolution, RESOLUTIONS.get(cfg.resolution_video, "MEDIA_RESOLUTION_MEDIUM"))
    return types.LiveConnectConfig(**reglages)


def _normaliser(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z ]", " ", sans_accents.lower()).split())


class PorteSilenceLive:
    """Pour un commentaire spontané : retient sa voix tant que la transcription pourrait être
    « silence » ou « rien à signaler ». etat : None = pas décidé, True = ne rien dire, False = laisser parler."""

    SILENCES = ("silence", "rien a signaler", "rien de neuf", "rien de special", "rien de particulier",
                "je ne dis rien", "je reste silencieux", "pas de commentaire")

    def __init__(self):
        self.texte = ""
        self.etat: bool | None = None

    def ajouter(self, morceau: str) -> None:
        if self.etat is not None:
            return
        self.texte += morceau
        n = _normaliser(self.texte)
        if any(n.startswith(s) for s in self.SILENCES):
            self.etat = True
        elif n and not any(s.startswith(n) for s in self.SILENCES):
            self.etat = False

    def terminer(self) -> None:
        if self.etat is None:
            n = _normaliser(self.texte)
            # Pas de transcription du tout : on ne peut pas savoir, on laisse passer.
            self.etat = bool(n) and any(s.startswith(n) or n.startswith(s) for s in self.SILENCES)


class ErreurGemini(Exception):
    """Erreur qui empêche de continuer (clé refusée…), le message s'adresse à l'utilisateur."""


def _court(message: str, longueur: int = 160) -> str:
    message = " ".join(str(message).split())
    return message if len(message) <= longueur else message[:longueur] + "…"


def _cle_refusee(message: str) -> bool:
    m = message.lower()
    return "api key not valid" in m or "api_key_invalid" in m or "permission denied" in m or "unauthenticated" in m


def _quota(message: str) -> bool:
    m = message.lower()
    return "resource_exhausted" in m or "quota" in m or "429" in m or "rate limit" in m


def _config_refusee(message: str) -> bool:
    m = message.lower()
    return any(motif in m for motif in ("invalid", "1007", "unknown name", "not supported", "not found"))


def _modele_introuvable(message: str) -> bool:
    m = message.lower()
    return "not found" in m and "model" in m


def creer_client(cle_api: str, avancee: bool):
    """Client Gemini. La proactivité n'existe que dans la version « v1alpha » de l'API (vérifié le 16/10/2026)."""
    from google import genai

    return genai.Client(api_key=cle_api, http_options={"api_version": "v1alpha"} if avancee else None)


class CompagnonLive:
    def __init__(self, cfg: Config, *, mode_test: bool = False, micro=None, lecteur=None, capture=None, client=None):
        self.cfg = cfg
        self.mode_test = mode_test
        if mode_test and not cfg.pseudo:
            cfg.pseudo = PSEUDO_TEST
        self.chemin_log = fichier_log_test() if mode_test else chemin_log(cfg)
        self.consignes = construire_consignes(cfg, lire_texte(RACINE / "personnalite.md"),
                                              lire_texte(RACINE / "chronique.md"))
        self.micro = micro if micro is not None else Micro(cfg.micro)
        self.lecteur = lecteur or Lecteur(cfg.sortie_audio)
        if capture is None:
            capture = (CaptureTest(RACINE / "exemples" / "images", duree_par_image=20.0) if mode_test
                       else CaptureEcran(cfg.ecran, cfg.fenetre_minecraft, cfg.suivre_fenetre))
        self.capture = capture
        self.client = client  # imposé par les tests ; sinon créé selon les options utilisées
        self._clients: dict[bool, object] = {}
        self.touche: ToucheParler | None = None
        self.micro_actif = False
        self.erreur_micro = ""
        self.fichier_capture = RACINE / "derniere_capture.jpg"

        self._boucle: asyncio.AbstractEventLoop | None = None
        self._session = None
        self._handle: str | None = None
        self._config_minimale = False
        self._file_envoi: asyncio.Queue = asyncio.Queue()
        self._verrou_envoi = asyncio.Lock()
        self._activite_ouverte = False
        self._pousse = False
        self._preroll: deque[bytes] = deque(maxlen=6)  # ~0,3 s avant l'appui
        self._taches: list[asyncio.Task] = []
        # Tour de parole en cours
        self._texte_moi = ""
        self._texte_lui = ""
        self._porte: PorteSilenceLive | None = None
        self._tampon_audio: list[np.ndarray] = []
        self._modele_actif = False
        self._t_relache: float | None = None
        # Regard
        self._derniere_empreinte_video = None
        self._t_derniere_video = float("-inf")
        self._empreinte_coup_d_oeil = None
        self._dernier_spontane = float("-inf")
        self._fin_parole = float("-inf")
        self.delai_image = DELAI_IMAGE
        self._etat_video: str | None = None
        self._images_envoyees = 0

    # ------------------------------------------------------------------ démarrage / arrêt
    async def tourner(self) -> None:
        self._boucle = asyncio.get_running_loop()
        try:
            self.lecteur.demarrer()
        except Exception as e:
            log.error("[Voix]   sortie audio indisponible : %s (les réponses s'afficheront seulement ici)", e)
        self._demarrer_micro()
        threading.Thread(target=self._lire_console, daemon=True).start()
        surveillant = SurveillantLog(self.chemin_log, AnalyseurLog(self.cfg.pseudo, self.cfg.mot_cle_chat),
                                     self._sur_evenement)
        for travail in (surveillant.tourner(), self._boucle_envoi(), self._boucle_video(), self._boucle_regard()):
            self._taches.append(asyncio.create_task(travail))
        self._afficher_accueil()
        try:
            await self._boucle_connexion()
        finally:
            self.arreter()

    def arreter(self) -> None:
        for tache in self._taches:
            tache.cancel()
        if self.touche:
            self.touche.arreter()
        with contextlib.suppress(Exception):
            self.micro.fermer()
        with contextlib.suppress(Exception):
            self.lecteur.fermer()

    def _demarrer_micro(self) -> None:
        self.micro.sur_bloc = self._bloc_micro
        try:
            self.micro.demarrer()
            self.micro_actif = True
        except Exception as e:
            self.erreur_micro = str(e)
            log.error("[Micro]  IMPOSSIBLE D'OUVRIR LE MICRO : %s", e)
            log.error("         -> Paramètres Windows > Confidentialité et sécurité > Microphone : active "
                      "« Accès au microphone » ET « Autoriser les applications de bureau à accéder au microphone ».")
        if self.cfg.micro_continu:
            return
        try:
            self.touche = ToucheParler(self.cfg.touche, self._depuis_thread(self._appui),
                                       self._depuis_thread(self._relache))
            self.touche.demarrer()
        except Exception as e:
            self.touche = None
            log.error("[Touche] impossible de surveiller la touche push-to-talk : %s", e)

    def _afficher_accueil(self) -> None:
        log.info("=" * 70)
        log.info("Compagnon prêt — moteur Gemini Live%s — version %s.",
                 " (MODE TEST)" if self.mode_test else "", VERSION)
        if self.cfg.micro_continu:
            log.info("  Parler       : micro ouvert en continu, parle quand tu veux")
        elif self.touche is not None:
            log.info("  Parler       : maintiens %s%s", self.touche.description(),
                     "" if self.micro_actif else "   (MAIS LE MICRO NE MARCHE PAS, voir plus haut)")
        if self.micro_actif:
            log.info("  Micro        : %s", getattr(self.micro, "nom", lambda: "?")())
        log.info("  Clavier      : tape une phrase ici puis Entrée pour lui écrire")
        log.info("  Modèle       : %s, voix « %s »", self.cfg.gemini_modele, self.cfg.gemini_voix)
        log.info("  Vidéo        : %s, %.0f image(s)/s au plus", self.capture.description(), self.cfg.images_par_seconde)
        log.info("  Journal jeu  : %s%s", self.chemin_log, "" if self.chemin_log.exists() else " (pas encore là)")
        if self.cfg.commentaires_spontanes:
            log.info("  Spontané     : coup d'œil au plus toutes les %.0f s quand l'écran a changé",
                     self.cfg.cooldown_spontane)
        log.info("  Ctrl+C pour quitter.")
        log.info("=" * 70)

    def _depuis_thread(self, fonction):
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

    # ------------------------------------------------------------------ connexion
    def _client(self, avancee: bool):
        if self.client is not None:
            return self.client
        if avancee not in self._clients:
            self._clients[avancee] = creer_client(self.cfg.gemini_cle_api, avancee)
        return self._clients[avancee]

    async def _boucle_connexion(self) -> None:
        from google.genai import types

        attente = 2.0
        while True:
            etablie = False
            try:
                config = construire_config(types, self.cfg, self.consignes, self._handle, self._config_minimale)
                client = self._client(avancee=self.cfg.proactivite and not self._config_minimale)
                async with client.aio.live.connect(model=self.cfg.gemini_modele, config=config) as session:
                    etablie = True
                    self._session = session
                    self._activite_ouverte = False
                    log.info("[Gemini] connecté%s", " (conversation reprise)" if self._handle else "")
                    attente = 2.0
                    if self._pousse:  # tu parlais pendant la reconnexion
                        self._file_envoi.put_nowait(("debut",))
                    await self._recevoir(session)
                await asyncio.sleep(0.5)  # fin normale (go_away…) : on se reconnecte tout de suite
            except asyncio.CancelledError:
                raise
            except Exception as e:
                message = str(e)
                if _cle_refusee(message):
                    raise ErreurGemini("clé API Gemini refusée : vérifie GEMINI_API_KEY (ou cle_api dans la "
                                       f"section [gemini] de config.toml). Détail : {_court(message)}") from e
                if not etablie and self._handle:
                    self._handle = None  # ticket de reprise expiré : nouvelle conversation
                    log.warning("[Gemini] reprise impossible, je démarre une nouvelle conversation.")
                    continue
                if not etablie and not self._config_minimale and _config_refusee(message):
                    self._config_minimale = True
                    log.warning("[Gemini] le modèle refuse certaines options (%s) : je réessaie sans la "
                                "proactivité ni le réglage de résolution vidéo.", _court(message))
                    continue
                if not etablie and _modele_introuvable(message):
                    raise ErreurGemini(f"modèle « {self.cfg.gemini_modele} » introuvable ({_court(message)}). "
                                       "Lance python compagnon.py --modeles et corrige « modele » dans [gemini].")
                if _quota(message):
                    attente = max(attente, 60.0)
                    log.error("[Gemini] quota gratuit atteint pour le moment (%s). Nouvel essai dans %.0f s.",
                              _court(message), attente)
                else:
                    log.warning("[Gemini] connexion perdue (%s), reconnexion dans %.0f s…", _court(message), attente)
                await asyncio.sleep(attente)
                attente = min(60.0, attente * 2)
            finally:
                self._session = None

    async def _recevoir(self, session) -> None:
        while True:
            recu = False
            async for message in session.receive():
                recu = True
                self._traiter(message)
                if message.go_away is not None:
                    log.info("[Gemini] reconnexion demandée par Google (dans %s), on reprend la conversation.",
                             message.go_away.time_left)
                    return
            if not recu:
                return

    # ------------------------------------------------------------------ envoi
    async def _envoyer(self, **contenu) -> bool:
        session = self._session
        if session is None:
            return False
        async with self._verrou_envoi:
            await session.send_realtime_input(**contenu)
        return True

    @property
    def _mime_audio(self) -> str:
        return f"audio/pcm;rate={self.micro.frequence}"

    def _bloc_micro(self, bloc: np.ndarray) -> None:
        """Thread audio : chaque bloc de 50 ms du micro part dans la file d'envoi."""
        with contextlib.suppress(RuntimeError):
            self._boucle.call_soon_threadsafe(self._file_envoi.put_nowait, ("audio", bloc.tobytes()))

    async def _boucle_envoi(self) -> None:
        """Seule tâche qui envoie le son et le texte : l'ordre (début de parole, son, fin) est garanti."""
        from google.genai import types

        while True:
            element = await self._file_envoi.get()
            genre = element[0]
            try:
                if genre == "audio":
                    if self.cfg.micro_continu or self._activite_ouverte:
                        await self._envoyer(audio=types.Blob(data=element[1], mime_type=self._mime_audio))
                    else:
                        self._preroll.append(element[1])
                elif genre == "debut":
                    if await self._envoyer(activity_start=types.ActivityStart()):
                        self._activite_ouverte = True
                        # Capture de l'écran au moment où tu commences à parler (en parallèle du son).
                        self._lancer(self._envoyer_image_fraiche("ta question"))
                        while self._preroll:
                            await self._envoyer(audio=types.Blob(data=self._preroll.popleft(),
                                                                 mime_type=self._mime_audio))
                elif genre == "fin":
                    if self._activite_ouverte:
                        self._activite_ouverte = False
                        await self._envoyer(activity_end=types.ActivityEnd())
                elif genre == "texte":
                    _, texte, spontane = element
                    entourer = not self.cfg.micro_continu and not self._activite_ouverte
                    self._porte = PorteSilenceLive() if spontane else None
                    if entourer:
                        await self._envoyer(activity_start=types.ActivityStart())
                    raison = "coup d'œil" if spontane else "message"
                    if await self._envoyer_image_fraiche(raison):  # il voit l'écran actuel avant le texte
                        await asyncio.sleep(self.delai_image)
                    if not await self._envoyer(text=texte):
                        log.warning("[Gemini] pas connecté pour l'instant : message non transmis.")
                    if entourer:
                        await self._envoyer(activity_end=types.ActivityEnd())
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.debug("[Gemini] envoi impossible : %s", e)

    def _lancer(self, travail) -> None:
        self._taches = [t for t in self._taches if not t.done()]
        self._taches.append(asyncio.create_task(travail))

    def _signaler_video(self, etat: str, niveau: int = logging.INFO) -> None:
        """Affiche l'état de la vidéo seulement quand il change (pas une ligne par seconde)."""
        if etat != self._etat_video:
            if etat == "ok":
                if self._etat_video is not None:
                    log.info("[Vidéo]  la vidéo repart normalement")
            else:
                log.log(niveau, "[Vidéo]  %s", etat)
            self._etat_video = etat

    async def _envoyer_image(self, image, emp=None) -> bool:
        from google.genai import types

        jpeg = await asyncio.to_thread(encoder_jpeg, image, self.cfg.largeur_video, 80)
        try:
            envoye = await self._envoyer(video=types.Blob(data=jpeg, mime_type="image/jpeg"))
        except Exception as e:
            self._signaler_video(f"image non envoyée à Gemini : {e}", logging.WARNING)
            return False
        if envoye:
            self._images_envoyees += 1
            if self._images_envoyees == 1:
                log.info("[Vidéo]  première image envoyée (%d×%d, %d Ko) : il voit ton écran",
                         image.width, image.height, len(jpeg) // 1024)
            self._derniere_empreinte_video = emp if emp is not None else empreinte(image)
            self._t_derniere_video = time.monotonic()
            if self.fichier_capture is not None:
                with contextlib.suppress(OSError):
                    await asyncio.to_thread(self.fichier_capture.write_bytes, jpeg)
        return envoye

    async def _envoyer_image_fraiche(self, raison: str) -> bool:
        """Capture et envoie l'écran tout de suite (quand tu parles, avant un coup d'œil ou un événement)."""
        try:
            image = await asyncio.to_thread(self.capture.capturer)
        except Exception as e:
            log.warning("[Vidéo]  capture IMPOSSIBLE pour %s : %s", raison, e)
            return False
        envoye = await self._envoyer_image(image)
        if envoye:
            log.info("[Vidéo]  écran capturé et envoyé avec %s", raison)
        elif self._session is None:
            log.warning("[Vidéo]  capture non envoyée (%s) : pas connecté à Gemini pour l'instant", raison)
        return envoye

    async def _boucle_video(self) -> None:
        """Envoie la fenêtre de Minecraft (1 image/s au plus), seulement quand elle change."""
        while True:
            await asyncio.sleep(1.0 / self.cfg.images_par_seconde)
            if self._session is None:
                continue
            if not self.mode_test and not jeu_au_premier_plan(self.cfg.fenetre_minecraft):
                self._signaler_video("en pause : la fenêtre au premier plan n'est pas Minecraft "
                                     "(normal si tu es sur le bureau ou dans ce terminal)")
                continue
            try:
                image = await asyncio.to_thread(self.capture.capturer)
            except Exception as e:
                self._signaler_video(f"capture IMPOSSIBLE : {e}", logging.WARNING)
                continue
            self._signaler_video("ok")
            maintenant = time.monotonic()
            emp = empreinte(image)
            if (self._derniere_empreinte_video is not None
                    and difference(emp, self._derniere_empreinte_video) < 0.01
                    and maintenant - self._t_derniere_video < VIDEO_MAX_SANS_ENVOI):
                continue  # écran figé (pause) : inutile de renvoyer la même image
            await self._envoyer_image(image, emp)

    # ------------------------------------------------------------------ réception
    def _traiter(self, message) -> None:
        reprise = message.session_resumption_update
        if reprise is not None and reprise.resumable and reprise.new_handle:
            self._handle = reprise.new_handle
        contenu = message.server_content
        if contenu is None:
            return
        if contenu.interrupted:
            self.lecteur.interrompre()
            self._tampon_audio.clear()
            if self._texte_lui.strip():
                log.info("[Lui]    %s […]", self._texte_lui.strip())
            self._texte_lui = ""
            self._modele_actif = False
        if contenu.input_transcription is not None and contenu.input_transcription.text:
            self._texte_moi += contenu.input_transcription.text
            if self._porte is not None:  # tu parles : sa réponse ne sera pas un commentaire spontané
                self._vider_tampon()
                self._porte = None
        if contenu.output_transcription is not None and contenu.output_transcription.text:
            self._texte_lui += contenu.output_transcription.text
            if self._porte is not None:
                avant = self._porte.etat
                self._porte.ajouter(contenu.output_transcription.text)
                if avant is None and self._porte.etat is False:
                    self._vider_tampon()
                elif self._porte.etat is True:
                    self._tampon_audio.clear()
        if contenu.model_turn is not None and contenu.model_turn.parts:
            for partie in contenu.model_turn.parts:
                donnees = getattr(partie.inline_data, "data", None) if partie.inline_data else None
                if isinstance(donnees, bytes) and donnees:
                    self._audio(donnees)
        if contenu.turn_complete:
            self._fin_de_tour()

    def _audio(self, octets: bytes) -> None:
        if self._pousse:
            return  # tu parles : les restes de sa réponse précédente encore en route sont jetés
        pcm = np.frombuffer(octets, dtype=np.int16).astype(np.float32) / 32768.0
        if not self._modele_actif:
            self._modele_actif = True
            if self._t_relache is not None:
                log.info("         -> voix lancée %.2f s après ta phrase", time.perf_counter() - self._t_relache)
                self._t_relache = None
        if self._porte is not None and self._porte.etat is not False:
            if self._porte.etat is None:
                self._tampon_audio.append(pcm)  # on attend de savoir si c'est « silence »
            return
        self.lecteur.jouer(pcm)

    def _vider_tampon(self) -> None:
        for pcm in self._tampon_audio:
            self.lecteur.jouer(pcm)
        self._tampon_audio.clear()

    def _fin_de_tour(self) -> None:
        spontane = self._porte is not None
        silence = False
        if spontane:
            self._porte.terminer()
            silence = bool(self._porte.etat)
            if silence:
                self._tampon_audio.clear()
            else:
                self._vider_tampon()
        moi, lui = self._texte_moi.strip(), self._texte_lui.strip()
        if moi:
            log.info("[Moi]    %s", moi)
        if lui and not silence:
            log.info("[Lui]    %s%s", "(spontané) " if spontane else "", lui)
            self._fin_parole = time.monotonic()
        elif spontane:
            log.info("[Regard] rien d'intéressant, il se tait")
        self._reinitialiser_tour()

    def _reinitialiser_tour(self) -> None:
        self._texte_moi = self._texte_lui = ""
        self._porte = None
        self._tampon_audio.clear()
        self._modele_actif = False

    # ------------------------------------------------------------------ toi
    def _appui(self) -> None:
        if self._pousse:  # répétition automatique de la touche
            return
        if not self.micro_actif:
            log.warning("[Micro]  touche détectée, mais le micro ne s'est pas ouvert (%s).", self.erreur_micro)
            return
        self._pousse = True
        self.lecteur.interrompre()  # il se tait tout de suite
        self._reinitialiser_tour()
        self._file_envoi.put_nowait(("debut",))
        log.info("[Micro]  j'écoute…")

    def _relache(self) -> None:
        if not self._pousse:
            return
        self._pousse = False
        self._t_relache = time.perf_counter()
        self._fin_parole = time.monotonic()
        self._file_envoi.put_nowait(("fin",))

    def _phrase_tapee(self, ligne: str) -> None:
        self.lecteur.interrompre()
        self._reinitialiser_tour()
        log.info("[Moi]    %s   (écrit dans la console)", ligne)
        self._t_relache = time.perf_counter()
        self._file_envoi.put_nowait(("texte", f"[Écrit] {ligne}", False))

    def _sur_evenement(self, evenement: EvenementJeu) -> None:
        if evenement.genre == "chat":
            log.info("[Chat]   %s", evenement.detail or "(t'interpelle)")
            texte = f"[Chat] {evenement.detail or '(il t interpelle sans rien ajouter)'}"
        elif evenement.genre == "mort":
            log.info("[Jeu]    mort : %s", evenement.texte)
            texte = f"[Événement] Le seigneur vient de mourir. Message du jeu : « {evenement.texte} »"
        else:
            log.info("[Jeu]    progrès : %s", evenement.texte)
            texte = (f"[Événement] Il vient d'obtenir le progrès « {evenement.detail} ». "
                     f"Message du jeu : « {evenement.texte} »")
        self._reinitialiser_tour()
        self._file_envoi.put_nowait(("texte", texte, False))

    # ------------------------------------------------------------------ commentaires spontanés
    def _occupe(self) -> str | None:
        if self._pousse:
            return "tu es en train de parler"
        if self._modele_actif or self.lecteur.parle:
            self._fin_parole = time.monotonic()
            return "il parle"
        maintenant = time.monotonic()
        if maintenant - self._dernier_spontane < self.cfg.cooldown_spontane:
            return "cooldown"
        if maintenant - self._fin_parole < PAUSE_APRES_PAROLE:
            return "on vient de parler"
        return None

    async def _boucle_regard(self) -> None:
        while True:
            await asyncio.sleep(3)
            if not self.cfg.commentaires_spontanes or self._session is None or self._occupe():
                continue
            if not self.mode_test and not jeu_au_premier_plan(self.cfg.fenetre_minecraft):
                continue
            emp = self._derniere_empreinte_video
            if emp is None:
                continue
            if (self._empreinte_coup_d_oeil is not None
                    and difference(emp, self._empreinte_coup_d_oeil) < self.cfg.seuil_changement):
                continue  # rien n'a bougé depuis le dernier coup d'œil (pause, immobile)
            self._empreinte_coup_d_oeil = emp
            self._dernier_spontane = time.monotonic()
            log.info("[Regard] coup d'œil")
            self._file_envoi.put_nowait(("texte", COUP_D_OEIL, True))
