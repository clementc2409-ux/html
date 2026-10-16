"""Chargement de config.toml et des fichiers texte (personnalité, chronique)."""

from __future__ import annotations

import logging
import os
import re
import sys
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

log = logging.getLogger("compagnon")


class ErreurConfig(Exception):
    """Problème de configuration (le message s'adresse à l'utilisateur)."""


@dataclass
class Config:
    # [moteur]
    moteur: str = "gemini"
    # [gemini]
    gemini_cle_api: str = ""
    gemini_modele: str = "gemini-3.8-live"
    gemini_voix: str = "Algenib"
    micro_continu: bool = False
    images_par_seconde: float = 1.0
    largeur_video: int = 1280
    resolution_video: str = "auto"
    proactivite: bool = True
    bande_capteur: bool = True
    # [groq]
    cle_api: str = ""
    modele_transcription: str = "whisper-large-v3-turbo"
    modele_vision: str = "qwen/qwen3.8-27b"
    effort_raisonnement: str = "none"
    temperature: float = 0.6
    max_jetons_reponse: int = 350
    # [parole]
    touche: str = "clavier:v"
    micro: str = ""
    langue: str = "fr"
    vocabulaire: str = ""
    # [voix]
    voix: str = "fr-FR-HenriNeural"
    debit: str = "+5%"
    volume: str = "+0%"
    sortie_audio: str = ""
    # [jeu]
    pseudo: str = ""
    chemin_log: str = ""
    mot_cle_chat: str = "@compagnon"
    chemin_etat: str = ""
    # [regard]
    commentaires_spontanes: bool = True
    intervalle_capture: float = 20.0
    cooldown_spontane: float = 45.0
    seuil_changement: float = 0.04
    fenetre_minecraft: str = "Minecraft"
    suivre_fenetre: bool = True
    ecran: int = 1
    largeur_image: int = 1280
    qualite_jpeg: int = 85
    # [memoire]
    echanges: int = 10
    # [carnet]
    outils: bool = True
    quetes: bool = True
    wiki: bool = True
    resume_auto: bool = True
    modele_resume: str = "gemini-3.5-flash"
    # [budget]
    jetons_par_jour: int = 200_000
    jetons_spontanes_par_heure: int = 40_000


# Section du fichier TOML -> clés acceptées.
SECTIONS: dict[str, tuple[str, ...] | dict[str, str]] = {
    "moteur": {"choix": "moteur"},
    "gemini": {"cle_api": "gemini_cle_api", "modele": "gemini_modele", "voix": "gemini_voix",
               "micro_continu": "micro_continu", "images_par_seconde": "images_par_seconde",
               "largeur_video": "largeur_video", "resolution_video": "resolution_video",
               "proactivite": "proactivite", "bande_capteur": "bande_capteur"},
    "groq": ("cle_api", "modele_transcription", "modele_vision", "effort_raisonnement",
             "temperature", "max_jetons_reponse"),
    "parole": ("touche", "micro", "langue", "vocabulaire"),
    "voix": ("voix", "debit", "volume", "sortie_audio"),
    "jeu": ("pseudo", "chemin_log", "mot_cle_chat", "chemin_etat"),
    "regard": ("commentaires_spontanes", "intervalle_capture", "cooldown_spontane",
               "seuil_changement", "fenetre_minecraft", "suivre_fenetre", "ecran", "largeur_image", "qualite_jpeg"),
    "memoire": ("echanges",),
    "carnet": ("outils", "quetes", "wiki", "resume_auto", "modele_resume"),
    "budget": ("jetons_par_jour", "jetons_spontanes_par_heure"),
}


def _convertir(nom: str, valeur, defaut):
    """Convertit une valeur du TOML vers le type attendu, avec un message clair sinon."""
    attendu = type(defaut)
    if attendu is bool:
        if isinstance(valeur, bool):
            return valeur
    elif attendu is float:
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
            return float(valeur)
    elif attendu is int:
        if isinstance(valeur, int) and not isinstance(valeur, bool):
            return valeur
    elif attendu is str:
        if isinstance(valeur, (str, int)) and not isinstance(valeur, bool):
            return str(valeur)
    noms = {bool: "true/false", float: "un nombre", int: "un nombre entier", str: "du texte entre guillemets"}
    raise ErreurConfig(f"config.toml : « {nom} » doit être {noms[attendu]} (valeur actuelle : {valeur!r}).")


def charger_config(chemin: Path | None = None) -> Config:
    chemin = chemin or RACINE / "config.toml"
    cfg = Config()
    if chemin.exists():
        try:
            donnees = tomllib.loads(chemin.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ErreurConfig(f"{chemin.name} est mal formé : {e}") from e
    else:
        log.warning("%s introuvable : réglages par défaut.", chemin)
        donnees = {}

    defauts = {f.name: f.default for f in fields(Config)}
    for section, contenu in donnees.items():
        if section not in SECTIONS or not isinstance(contenu, dict):
            log.warning("config.toml : section [%s] inconnue, ignorée.", section)
            continue
        champs = SECTIONS[section]
        if not isinstance(champs, dict):
            champs = {cle: cle for cle in champs}
        for cle, valeur in contenu.items():
            if cle not in champs:
                log.warning("config.toml : réglage « %s » inconnu dans [%s], ignoré.", cle, section)
                continue
            setattr(cfg, champs[cle], _convertir(cle, valeur, defauts[champs[cle]]))

    if not cfg.cle_api:
        cfg.cle_api = os.environ.get("GROQ_API_KEY", "").strip()
    if not cfg.gemini_cle_api:
        cfg.gemini_cle_api = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    cfg.moteur = cfg.moteur.strip().lower()
    if cfg.moteur not in ("gemini", "groq"):
        raise ErreurConfig(f"config.toml : moteur « {cfg.moteur} » inconnu (choix possibles : \"gemini\" ou \"groq\").")
    cfg.images_par_seconde = min(1.0, max(0.1, cfg.images_par_seconde))  # Gemini Live : 1 image/s au plus
    cfg.largeur_video = max(256, cfg.largeur_video)
    cfg.intervalle_capture = max(3.0, cfg.intervalle_capture)
    cfg.echanges = max(1, cfg.echanges)
    # L'observation de l'écran (non prononcée) passe avant la réponse : il faut de la place pour les deux.
    cfg.max_jetons_reponse = max(250, cfg.max_jetons_reponse)
    cfg.largeur_image = max(256, cfg.largeur_image)
    cfg.qualite_jpeg = min(95, max(20, cfg.qualite_jpeg))
    return cfg


def developper_chemin(chemin: str) -> Path:
    """Remplace %VARIABLE% (style Windows), $VARIABLE et ~ dans un chemin."""
    chemin = re.sub(r"%([^%]+)%", lambda m: os.environ.get(m.group(1), m.group(0)), chemin)
    return Path(os.path.expanduser(os.path.expandvars(chemin)))


def chemin_log_par_defaut() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / ".minecraft"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "minecraft"
    else:
        base = Path.home() / ".minecraft"
    return base / "logs" / "latest.log"


def chemin_log(cfg: Config) -> Path:
    if not cfg.chemin_log.strip():
        return chemin_log_par_defaut()
    chemin = developper_chemin(cfg.chemin_log.strip())
    if "%" in str(chemin):
        # Variable Windows absente (ex. %APPDATA% sur Mac/Linux) : chemin standard du système.
        return chemin_log_par_defaut()
    return chemin


def chemin_etat(cfg: Config, chemin_du_log: Path) -> Path:
    """Fichier d'état écrit par le mod : par défaut <dossier du jeu>/compagnon/etat.json, à côté de logs/."""
    if cfg.chemin_etat.strip():
        return developper_chemin(cfg.chemin_etat.strip())
    return chemin_du_log.parent.parent / "compagnon" / "etat.json"


def lire_texte(chemin: Path) -> str:
    """Contenu d'un fichier texte, ou "" s'il n'existe pas."""
    try:
        return chemin.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
