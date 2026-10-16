"""Outils que Gemini peut utiliser pendant la conversation (« function calling ») : tenir le carnet du royaume
(projets, quêtes, lieux, rappels) et chercher dans le wiki Minecraft.

Le modèle décide seul de les appeler ; le programme exécute l'action et lui renvoie le résultat.
Aucun outil n'agit sur le jeu : ils ne touchent qu'au carnet (carnet.json) et lisent le wiki.
"""

from __future__ import annotations

import asyncio
import logging

from . import wiki
from .carnet import Carnet
from .etat_jeu import CapteurEtat

log = logging.getLogger("compagnon")

# nom -> (description, {paramètre: (type, description)}, paramètres obligatoires)
OUTILS: dict[str, tuple[str, dict[str, tuple[str, str]], list[str]]] = {
    "noter_projet": (
        "Note dans le carnet du royaume un projet de construction ou d'aventure dont vous avez parlé "
        "(ex. « Port du Sud », « Barrage de la rivière »). Aussi pour mettre à jour ses détails.",
        {"nom": ("STRING", "nom court du projet"),
         "details": ("STRING", "où, comment, matériaux, idées (facultatif)")},
        ["nom"]),
    "terminer_projet": (
        "Marque un projet du carnet comme terminé (quand tu vois ou qu'il te dit qu'il est fini).",
        {"nom": ("STRING", "nom du projet (même approximatif)")},
        ["nom"]),
    "ajouter_quete": (
        "Ajoute une quête au carnet quand il accepte une quête que tu lui proposes, ou quand il t'en demande une. "
        "Une quête = un objectif concret et vérifiable, adapté à ce qu'il a déjà.",
        {"titre": ("STRING", "titre court et évocateur"),
         "objectif": ("STRING", "ce qu'il doit faire exactement"),
         "recompense": ("STRING", "récompense symbolique ou de jeu, facultatif (ex. un titre, un nom de lieu)")},
        ["titre", "objectif"]),
    "terminer_quete": (
        "Marque une quête comme accomplie (ou abandonnée) quand tu constates qu'elle est faite.",
        {"titre": ("STRING", "titre de la quête (même approximatif)"),
         "reussie": ("BOOLEAN", "true si accomplie, false si abandonnée")},
        ["titre"]),
    "noter_lieu": (
        "Note un lieu important à sa position actuelle (base, village, portail, temple, mine, ferme…). "
        "Les coordonnées sont prises automatiquement dans le jeu.",
        {"nom": ("STRING", "nom du lieu"),
         "note": ("STRING", "ce qu'il y a là, facultatif")},
        ["nom"]),
    "creer_rappel": (
        "Programme un rappel : dans tant de minutes, tu recevras « [Rappel] … » et tu le lui diras.",
        {"texte": ("STRING", "ce qu'il faudra lui rappeler"),
         "minutes": ("NUMBER", "dans combien de minutes (0.5 à 1440)")},
        ["texte", "minutes"]),
    "consulter_carnet": (
        "Relit tout le carnet du royaume : projets, quêtes, lieux avec leurs coordonnées, rappels à venir.",
        {}, []),
    "chercher_wiki": (
        "Cherche dans le wiki Minecraft (version la plus récente du jeu) : recette, mécanique, chiffre exact, "
        "nouveauté. À utiliser dès que tu n'es pas certain de la réponse.",
        {"sujet": ("STRING", "ce qu'il faut chercher, en français (ex. « balise », « enchantement Fortune »)")},
        ["sujet"]),
}


def declarations(types, avec_wiki: bool = True) -> list:
    """Déclarations des outils au format du SDK google-genai."""
    resultat = []
    for nom, (description, parametres, obligatoires) in OUTILS.items():
        if nom == "chercher_wiki" and not avec_wiki:
            continue
        schema = None
        if parametres:
            schema = types.Schema(type="OBJECT", required=obligatoires, properties={
                p: types.Schema(type=t, description=d) for p, (t, d) in parametres.items()})
        resultat.append(types.FunctionDeclaration(name=nom, description=description, parameters=schema))
    return resultat


class Outils:
    def __init__(self, carnet: Carnet, capteur: CapteurEtat | None = None, wiki_actif: bool = True,
                 domaine_wiki: str = "fr.minecraft.wiki"):
        self.carnet = carnet
        self.capteur = capteur
        self.wiki_actif = wiki_actif
        self.domaine_wiki = domaine_wiki

    def _position(self) -> dict | None:
        if self.capteur is None or not self.capteur.frais:
            return None
        joueur = self.capteur.etat.get("joueur", {})
        return {cle: joueur.get(cle) for cle in ("x", "y", "z", "dimension")}

    async def executer(self, nom: str, args: dict) -> dict:
        """Exécute un outil et renvoie la réponse à transmettre au modèle (jamais d'exception)."""
        args = args or {}
        try:
            if nom == "noter_projet":
                resultat = self.carnet.noter_projet(args.get("nom", ""), args.get("details", ""))
            elif nom == "terminer_projet":
                resultat = self.carnet.terminer_projet(args.get("nom", ""))
            elif nom == "ajouter_quete":
                resultat = self.carnet.ajouter_quete(args.get("titre", ""), args.get("objectif", ""),
                                                     args.get("recompense", ""))
            elif nom == "terminer_quete":
                resultat = self.carnet.terminer_quete(args.get("titre", ""), args.get("reussie", True) is not False)
            elif nom == "noter_lieu":
                resultat = self.carnet.noter_lieu(args.get("nom", ""), args.get("note", ""), self._position())
            elif nom == "creer_rappel":
                resultat = self.carnet.creer_rappel(args.get("texte", ""), args.get("minutes", 5))
            elif nom == "consulter_carnet":
                resultat = self.carnet.consulter()
            elif nom == "chercher_wiki" and self.wiki_actif:
                log.info("[Wiki]   je cherche « %s »…", args.get("sujet", ""))
                resultat = await asyncio.to_thread(wiki.chercher, args.get("sujet", ""), self.domaine_wiki)
            else:
                resultat = {"erreur": f"outil « {nom} » inconnu"}
        except Exception as e:  # un outil ne doit jamais faire tomber la conversation
            log.debug("outil %s en erreur : %s", nom, e, exc_info=True)
            resultat = {"erreur": f"échec de l'outil : {e}"}
        etiquette = "[Wiki]  " if nom == "chercher_wiki" else "[Carnet]"
        log.info("%s %s -> %s", etiquette, nom, resultat.get("resultat") or resultat.get("erreur")
                 or (f"page « {resultat['page']} »" if resultat.get("page") else "carnet relu"))
        return resultat
