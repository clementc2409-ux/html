"""Surveillance du journal de Minecraft (latest.log) : morts, progrès/succès, messages « @compagnon »."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("compagnon")

# « [12:34:56] [Server thread/INFO]: message » (vanilla), avec variantes Forge « [...] [thread/INFO] [logger/]: »
# et Fabric « [...] [thread/INFO] (Minecraft) message ».
_LIGNE = re.compile(r"^\[[^\]]*\]\s*\[[^\]]*/INFO\]\s*(?:\[[^\]]*\]|\([^)]*\))?\s*:?\s*(.*)$")
# Préfixes ajoutés par le client devant les messages du chat.
_PREFIXE_CHAT = re.compile(r"^\[(?:System|Système|CHAT|Not Secure|Non sécurisé)\]\s*", re.IGNORECASE)
_COULEURS = re.compile(r"§.")
_MESSAGE_CHAT = re.compile(r"^<([^>]+)>\s*(.*)$")
_NOM_PROGRES = re.compile(r"\[(.+)\]\s*$")

MOTS_PROGRES = ("advancement", "challenge", "goal", "progrès", "défi", "objectif")

# Messages qui commencent par le pseudo mais ne sont pas des morts.
EXCLUSIONS = (
    "joined the game", "left the game", "lost connection", "logged in", "moved too quickly", "moved wrongly",
    "kicked", "a rejoint la partie", "a quitté la partie", "a perdu la connexion", "s'est connecté",
    "expulsé", "has the following", "possède les", "a les données",
)

# Morceaux de messages de mort (anglais et français) ; la liste est large exprès.
MOTS_MORT = (
    # anglais
    "was ", "were ", "died", "drowned", "blew up", "burned", "burnt", "fell ", "hit the ground", "tried to swim",
    "went up in flames", "went off with a bang", "starved", "suffocated", "experienced kinetic", "froze to death",
    "withered away", "discovered the floor", "walked into", "didn't want to live", "left the confines",
    # français
    "a été ", "est mort", "est morte", "s'est ", "a explosé", "a heurté", "a essayé de nager", "a péri",
    "a brûlé", "est tombé", "est tombée", "a suffoqué", "a fait une chute", "a découvert", "a succombé",
    "a marché", "n'a pas voulu", "a voulu", "a quitté les limites", "a été tué", "a été abattu",
)


@dataclass
class EvenementJeu:
    genre: str    # "mort", "progres" ou "chat"
    texte: str    # message du jeu nettoyé
    detail: str = ""  # nom du progrès ou message adressé au compagnon


class AnalyseurLog:
    """Transforme une ligne du journal en événement (ou None si elle ne nous intéresse pas)."""

    def __init__(self, pseudo: str, mot_cle: str = "@compagnon"):
        self.pseudo = pseudo.strip()
        self.mot_cle = mot_cle.strip().lower()

    @staticmethod
    def message(ligne: str) -> str | None:
        m = _LIGNE.match(ligne.strip())
        if not m:
            return None
        texte = _COULEURS.sub("", m.group(1)).strip()
        while (p := _PREFIXE_CHAT.match(texte)):
            texte = texte[p.end():]
        return texte

    def analyser(self, ligne: str) -> EvenementJeu | None:
        texte = self.message(ligne)
        if not texte:
            return None

        chat = _MESSAGE_CHAT.match(texte)
        if chat:
            auteur, contenu = chat.groups()
            if self.pseudo and self.pseudo.lower() not in auteur.lower():
                return None
            if self.mot_cle and contenu.lower().startswith(self.mot_cle):
                demande = contenu[len(self.mot_cle):].lstrip(" ,:;-").strip()
                return EvenementJeu("chat", texte, demande)
            return None

        if not self.pseudo or not texte.lower().startswith(self.pseudo.lower() + " "):
            return None
        reste = texte[len(self.pseudo) + 1:].lower()

        progres = _NOM_PROGRES.search(texte)
        if progres and any(mot in reste for mot in MOTS_PROGRES):
            return EvenementJeu("progres", texte, progres.group(1))
        if any(mot in reste for mot in EXCLUSIONS):
            return None
        if any(f" {mot}" in f" {reste}" for mot in MOTS_MORT):
            return EvenementJeu("mort", texte)
        return None


class SurveillantLog:
    """Lit les nouvelles lignes de latest.log toutes les 0,5 s.

    Le fichier est ouvert puis refermé à chaque lecture : on ne bloque jamais Minecraft, qui renomme
    ce fichier à chaque lancement. Au démarrage on part de la fin (pas de vieux événements) ; si le
    fichier est recréé (nouveau lancement du jeu), on le relit depuis le début.
    """

    def __init__(self, chemin: Path, analyseur: AnalyseurLog, sur_evenement: Callable[[EvenementJeu], None],
                 intervalle: float = 0.5, anti_doublon: float = 5.0):
        self.chemin = chemin
        self.analyseur = analyseur
        self.sur_evenement = sur_evenement
        self.intervalle = intervalle
        self.anti_doublon = anti_doublon
        self._position: int | None = None
        self._reste = b""
        self._vus: dict[tuple[str, str], float] = {}
        self._absent_signale = False

    def lire_nouveautes(self) -> list[str]:
        """Renvoie les nouvelles lignes complètes depuis la dernière lecture."""
        try:
            infos = os.stat(self.chemin)
        except OSError:
            if not self._absent_signale:
                log.info("[Jeu]    journal introuvable pour l'instant : %s (Minecraft pas encore lancé ?)", self.chemin)
                self._absent_signale = True
            if self._position is None:
                self._position = 0  # quand il apparaîtra, on le lira depuis le début
            return []
        if self._absent_signale:
            log.info("[Jeu]    journal trouvé : %s", self.chemin)
            self._absent_signale = False

        if self._position is None:
            self._position = infos.st_size  # premier passage : on ignore l'ancien contenu
        elif infos.st_size < self._position:
            self._position, self._reste = 0, b""  # fichier recréé plus court (relance du jeu) ou vidé
        if infos.st_size == self._position:
            return []

        with open(self.chemin, "rb") as fichier:
            fichier.seek(self._position)
            donnees = fichier.read()
        self._position += len(donnees)
        donnees = self._reste + donnees
        *lignes, self._reste = donnees.split(b"\n")
        return [_decoder(ligne) for ligne in lignes]

    def traiter(self, lignes: list[str]) -> list[EvenementJeu]:
        evenements = []
        maintenant = time.monotonic()
        for ligne in lignes:
            evenement = self.analyseur.analyser(ligne)
            if evenement is None:
                continue
            # Le serveur intégré et le client écrivent souvent la même chose deux fois.
            cle = (evenement.genre, evenement.texte)
            if maintenant - self._vus.get(cle, -1e9) < self.anti_doublon:
                continue
            self._vus[cle] = maintenant
            evenements.append(evenement)
        return evenements

    async def tourner(self) -> None:
        while True:
            try:
                for evenement in self.traiter(self.lire_nouveautes()):
                    self.sur_evenement(evenement)
            except OSError as e:
                log.debug("[Jeu]    lecture du journal impossible : %s", e)
            await asyncio.sleep(self.intervalle)


def _decoder(ligne: bytes) -> str:
    ligne = ligne.rstrip(b"\r")
    try:
        return ligne.decode("utf-8")
    except UnicodeDecodeError:
        return ligne.decode("cp1252", errors="replace")


# --- Mode test : faux journal que l'on peut modifier à la main -------------------------------------

PSEUDO_TEST = "Steve"  # pseudo utilisé en mode test si aucun n'est configuré


def fichier_log_test() -> Path:
    from .config import RACINE

    chemin = RACINE / "exemples" / "faux_latest.log"
    if not chemin.exists():
        chemin.write_text(
            "[12:00:00] [main/INFO]: Faux journal pour « python compagnon.py --test ».\n"
            "[12:00:00] [main/INFO]: Ajoute des lignes à la fin (puis enregistre) ou utilise --simuler.\n"
            "[12:00:01] [Server thread/INFO]: Steve a rejoint la partie\n",
            encoding="utf-8")
    return chemin


EXEMPLES_MORT = (
    "{p} a été tué par Zombie",
    "{p} a explosé à cause de Creeper",
    "{p} a heurté le sol trop violemment",
    "{p} a essayé de nager dans la lave",
    "{p} s'est noyé",
    "{p} a été abattu par Squelette",
)
EXEMPLES_PROGRES = (
    "{p} a obtenu le progrès [L'âge de pierre]",
    "{p} a obtenu le progrès [Diamants !]",
    "{p} a obtenu le progrès [Nous devons aller plus profond]",
    "{p} a relevé le défi [Monstres chassés]",
)


def ligne_simulee(genre: str, pseudo: str, texte: str = "", mot_cle: str = "@compagnon") -> str:
    import random

    heure = time.strftime("%H:%M:%S")
    if genre == "mort":
        message = random.choice(EXEMPLES_MORT).format(p=pseudo)
    elif genre == "progres":
        message = random.choice(EXEMPLES_PROGRES).format(p=pseudo)
    elif genre == "chat":
        message = f"<{pseudo}> {mot_cle} {texte or 'tu en penses quoi de mon château ?'}"
    else:
        raise ValueError(genre)
    return f"[{heure}] [Server thread/INFO]: {message}"
