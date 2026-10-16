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
from .capture import CaptureEcran, CaptureTest, difference, empreinte, jeu_au_premier_plan, preparer_image
from .cerveau import Cerveau, ErreurGroq, LimiteGroq, charger_systeme
from .config import RACINE, Config, chemin_log
from .journal_jeu import PSEUDO_TEST, AnalyseurLog, EvenementJeu, SurveillantLog, fichier_log_test
from .phrases import DecoupeurPhrases, PorteSilence, est_silence
from .touches import ToucheParler
from .voix import Lecteur, Parole, Synthese

log = logging.getLogger("compagnon")

# Plus le chiffre est petit, plus la demande est prioritaire.
PRIORITE = {"voix": 0, "chat": 0, "evenement": 1, "spontane": 2}
DUREE_MIN_VOIX = 0.4      # secondes : en dessous, appui accidentel
NIVEAU_MIN_VOIX = 0.01    # volume crête : en dessous, micro coupé / rien dit
PAUSE_APRES_PAROLE = 8.0  # secondes de calme après une réponse avant un commentaire spontané


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
            "le coup et sans te répéter ; sinon réponds exactement SILENCE. Si la capture montre un menu "
            "(pause, inventaire, options) ou un écran de chargement, réponds SILENCE.")


class Compagnon:
    def __init__(self, cfg: Config, *, mode_test: bool = False,
                 cerveau=None, synthese=None, lecteur=None, micro=None, capture=None):
        self.cfg = cfg
        self.mode_test = mode_test
        if mode_test and not cfg.pseudo:
            cfg.pseudo = PSEUDO_TEST
        self.chemin_log = fichier_log_test() if mode_test else chemin_log(cfg)
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
        self.erreur_micro = ""

        self._boucle: asyncio.AbstractEventLoop | None = None
        self._tour: asyncio.Task | None = None
        self._genre_tour: str | None = None
        self._tache_voix: asyncio.Task | None = None
        self._enregistre = False
        self._taches: list[asyncio.Task] = []
        # Regard (commentaires spontanés)
        self._derniere_empreinte = None          # dernière image envoyée au modèle
        self._dernier_spontane = float("-inf")   # dernier commentaire spontané prononcé
        self._fin_parole = float("-inf")
        self._derniere_raison: str | None = None

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
        surveillant = SurveillantLog(self.chemin_log, AnalyseurLog(self.cfg.pseudo, self.cfg.mot_cle_chat),
                                     self._sur_evenement)
        self._taches.append(asyncio.create_task(surveillant.tourner()))
        self._taches.append(asyncio.create_task(self._boucle_regard()))
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
        # Micro et touche sont indépendants : même sans micro, la touche est surveillée pour pouvoir
        # dire clairement ce qui ne va pas au moment où tu appuies.
        try:
            self.micro.demarrer()
            self.micro_actif = True
        except Exception as e:
            self.erreur_micro = str(e)
            log.error("[Micro]  IMPOSSIBLE D'OUVRIR LE MICRO : %s", e)
            log.error("         -> Paramètres Windows > Confidentialité et sécurité > Microphone : active "
                      "« Accès au microphone » ET « Autoriser les applications de bureau à accéder au microphone ».")
            log.error("         -> Ou choisis le bon micro : python compagnon.py --peripheriques, puis « micro » "
                      "dans config.toml.")
        try:
            self.touche = ToucheParler(self.cfg.touche, self._depuis_thread(self._appui),
                                       self._depuis_thread(self._relache))
            self.touche.demarrer()
        except Exception as e:
            self.touche = None
            log.error("[Touche] impossible de surveiller la touche push-to-talk : %s", e)
        if not self.micro_actif or self.touche is None:
            log.error("         En attendant, tu peux écrire tes phrases dans cette console (puis Entrée).")

    def _afficher_accueil(self) -> None:
        log.info("=" * 70)
        log.info("Compagnon prêt%s.", " (MODE TEST)" if self.mode_test else "")
        if self.touche is not None:
            log.info("  Parler       : maintiens %s%s", self.touche.description(),
                     "" if self.micro_actif else "   (MAIS LE MICRO NE MARCHE PAS, voir plus haut)")
        if self.micro_actif:
            log.info("  Micro        : %s", getattr(self.micro, "nom", lambda: "?")())
            log.info("                 (« [Micro] j'écoute… » doit s'afficher ; sinon : python compagnon.py --diagnostic)")
        log.info("  Clavier      : tape une phrase ici puis Entrée pour lui parler par écrit")
        log.info("  Modèles      : %s (voix -> texte), %s (vision)",
                 self.cfg.modele_transcription, self.cfg.modele_vision)
        log.info("  Captures     : %s", self.capture.description())
        log.info("  Journal jeu  : %s%s", self.chemin_log, "" if self.chemin_log.exists() else " (pas encore là)")
        if self.cfg.pseudo:
            log.info("  Pseudo       : %s  (écris « %s … » dans le chat pour lui parler)",
                     self.cfg.pseudo, self.cfg.mot_cle_chat)
        else:
            log.warning("  Pseudo       : NON CONFIGURÉ -> tes morts et tes succès ne seront pas détectés "
                        "(réglage « pseudo » dans config.toml)")
        if self.cfg.commentaires_spontanes:
            log.info("  Regard       : capture toutes les %.0f s, commentaire spontané au plus toutes les %.0f s",
                     self.cfg.intervalle_capture, self.cfg.cooldown_spontane)
        else:
            log.info("  Regard       : commentaires spontanés désactivés")
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
        if not self.micro_actif:
            log.warning("[Micro]  touche détectée, mais le micro ne s'est pas ouvert (%s). Vérifie les "
                        "autorisations micro de Windows, puis relance.", self.erreur_micro)
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

    # ------------------------------------------------------------------ journal du jeu
    def _sur_evenement(self, evenement: EvenementJeu) -> None:
        if evenement.genre == "chat":
            log.info("[Chat]   %s", evenement.detail or "(t'interpelle)")
            demande = Demande("chat", evenement.detail or "(il t'interpelle sans rien ajouter)")
        elif evenement.genre == "mort":
            log.info("[Jeu]    mort : %s", evenement.texte)
            demande = Demande("evenement", f"Le seigneur vient de mourir. Message du jeu : « {evenement.texte} »")
        else:
            log.info("[Jeu]    progrès : %s", evenement.texte)
            demande = Demande("evenement", f"Il vient d'obtenir le progrès « {evenement.detail} ». "
                                           f"Message du jeu : « {evenement.texte} »")
        self._taches.append(asyncio.create_task(self.soumettre(demande)))
        self._taches = [t for t in self._taches if not t.done()]

    # ------------------------------------------------------------------ regard (commentaires spontanés)
    def _occupe(self) -> str | None:
        """Raison de ne pas faire de commentaire spontané maintenant (None = la voie est libre)."""
        if self._enregistre:
            return "tu es en train de parler"
        if (self._tour and not self._tour.done()) or (self._tache_voix and not self._tache_voix.done()):
            return "réponse en cours"
        if self.lecteur.parle:
            return "je parle"
        maintenant = time.monotonic()
        reste = self.cfg.cooldown_spontane - (maintenant - self._dernier_spontane)
        if reste > 0:
            return f"cooldown après le dernier commentaire (encore {reste:.0f} s)"
        if maintenant - self._fin_parole < PAUSE_APRES_PAROLE:
            return "on vient de parler"
        return None

    def _signaler(self, raison: str | None, niveau: int = logging.INFO) -> None:
        """Affiche pourquoi on n'envoie rien, sans répéter la même raison toutes les 20 s."""
        cle = raison.split(" (")[0] if raison else None  # sans le compte à rebours éventuel
        if cle and cle != self._derniere_raison:
            log.log(niveau, "[Regard] pas de commentaire : %s", raison)
        self._derniere_raison = cle

    async def _boucle_regard(self) -> None:
        while True:
            await asyncio.sleep(self.cfg.intervalle_capture)
            if not self.cfg.commentaires_spontanes:
                continue
            try:
                await self._coup_d_oeil()
            except Exception:
                log.exception("[Regard] erreur inattendue")

    async def _coup_d_oeil(self) -> None:
        raison = self._occupe()
        if raison:
            self._signaler(raison, logging.DEBUG)
            return
        if not self.mode_test and not jeu_au_premier_plan(self.cfg.fenetre_minecraft):
            self._signaler(f"la fenêtre au premier plan n'est pas « {self.cfg.fenetre_minecraft} »")
            return
        image = await self._capturer()
        if image is None:
            return
        if self._derniere_empreinte is not None:
            ecart = difference(empreinte(image), self._derniere_empreinte)
            if ecart < self.cfg.seuil_changement:
                self._signaler("écran quasi identique (jeu en pause ou immobile ?)")
                return
        autorise, raison = self.budget.autorise_spontane()
        if not autorise:
            self._signaler(raison)
            return
        if self._occupe():  # quelqu'un a pris la parole pendant la capture
            return
        self._derniere_raison = None
        log.info("[Regard] coup d'œil envoyé")
        await self.soumettre(Demande("spontane", image=image))

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
                # asyncio.wait (et non « await tour ») : si c'est nous qu'on annule entre-temps,
                # l'annulation doit remonter normalement.
                await asyncio.wait({self._tour})
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
        spontane = demande.genre == "spontane"
        image = demande.image if demande.image is not None else await self._capturer()
        image_url = None
        if image is not None:
            self._derniere_empreinte = empreinte(image)
            image_url = await asyncio.to_thread(preparer_image, image, self.cfg.largeur_image, self.cfg.qualite_jpeg)
        entree = formuler(demande)
        t0 = demande.t0

        def premier_son():
            log.info("         -> voix lancée %.2f s après ta phrase", time.perf_counter() - t0)

        parole = Parole(self.synthese, self.lecteur, premier_son if demande.genre == "voix" else None)
        decoupeur = DecoupeurPhrases()
        porte = PorteSilence() if spontane else None  # retient le début tant que ça pourrait être SILENCE
        morceaux: list[str] = []
        t_premier_mot = None
        memorise = a_parle = False
        try:
            async with contextlib.aclosing(self.cerveau.repondre(entree, image_url, spontane)) as flux:
                async for morceau in flux:
                    if t_premier_mot is None:
                        t_premier_mot = time.perf_counter() - t0
                    morceaux.append(morceau)
                    if porte is not None:
                        morceau = porte.ajouter(morceau)
                        if porte.etat is True:
                            break  # SILENCE : inutile de lire la suite
                    for phrase in decoupeur.ajouter(morceau):
                        parole.dire(phrase)
            texte = "".join(morceaux).strip()
            observation = getattr(self.cerveau, "derniere_observation", "")
            if observation:
                log.info("[Vu]     %s", observation)
            if porte is not None:
                porte.terminer()
            if not texte or est_silence(texte) or (porte is not None and porte.etat):
                log.info("[Regard] SILENCE (rien d'intéressant à dire)" if spontane else "[Lui]    (ne dit rien)")
                return
            for phrase in decoupeur.terminer():
                parole.dire(phrase)
            self.cerveau.memoriser(entree, texte)
            memorise = a_parle = True
            if spontane:
                self._dernier_spontane = time.monotonic()
            details = f"premier mot {t_premier_mot:.2f} s" if t_premier_mot is not None else ""
            if self.cerveau.derniers_jetons:
                details += f", {self.cerveau.derniers_jetons} jetons"
            log.info("[Lui]    %s%s   (%s)", "(spontané) " if spontane else "", texte, details)
            await parole.finir()
        except LimiteGroq as e:
            if spontane:
                # Les commentaires spontanés sont sacrifiés en premier.
                self.budget.pause_spontanes(e.attente or 60)
                log.warning("[Groq]   limite atteinte : commentaire spontané abandonné (pause %.0f s).",
                            e.attente or 60)
                return
            log.error("[Groq]   limite atteinte : %s", e)
            a_parle = True
            await self._dire_message(self._message_limite(e.attente), parole)
        except ErreurGroq as e:
            log.error("[Groq]   %s", e)
            if not spontane:
                a_parle = True
                await self._dire_message("Désolé, je n'arrive pas à joindre Groq.", parole)
        except asyncio.CancelledError:
            partiel = "".join(morceaux).strip()
            if partiel and not memorise and not (porte is not None and porte.etat is not False):
                self.cerveau.memoriser(entree, partiel + " […interrompu]")
            raise
        finally:
            parole.annuler()
            if a_parle:
                self._fin_parole = time.monotonic()

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
