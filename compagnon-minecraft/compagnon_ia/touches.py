"""Touche push-to-talk (clavier ou bouton de souris) via pynput. On écoute seulement, on ne simule rien."""

from __future__ import annotations

import logging
from typing import Callable

from .config import ErreurConfig

log = logging.getLogger("compagnon")

BOUTONS_SOURIS = {"x1": "x1", "x2": "x2", "milieu": "middle", "middle": "middle"}
NOMS_LISIBLES = {"x1": "bouton latéral arrière de la souris (x1)",
                 "x2": "bouton latéral avant de la souris (x2)",
                 "middle": "clic molette"}


def analyser_touche(reglage: str) -> tuple[str, str]:
    """"souris:x1" -> ("souris", "x1") ; "clavier:f8" -> ("clavier", "f8")."""
    genre, _, nom = reglage.strip().lower().partition(":")
    if genre == "souris" and nom in BOUTONS_SOURIS:
        return "souris", BOUTONS_SOURIS[nom]
    if genre == "clavier" and nom:
        return "clavier", nom
    raise ErreurConfig(
        f"config.toml : touche « {reglage} » invalide. Exemples : \"souris:x1\", \"souris:x2\", "
        "\"clavier:v\", \"clavier:f8\", \"clavier:alt_r\"."
    )


class ToucheParler:
    """Appelle sur_appui / sur_relache (depuis le thread de pynput) quand la touche change d'état."""

    def __init__(self, reglage: str, sur_appui: Callable[[], None], sur_relache: Callable[[], None]):
        self.genre, self.nom = analyser_touche(reglage)
        self.sur_appui = sur_appui
        self.sur_relache = sur_relache
        self._ecouteur = None

    def description(self) -> str:
        if self.genre == "souris":
            return NOMS_LISIBLES[self.nom]
        return f"touche « {self.nom} » du clavier"

    def demarrer(self) -> None:
        if self.genre == "souris":
            from pynput import mouse

            bouton = getattr(mouse.Button, self.nom, None)
            if bouton is None:
                raise ErreurConfig(f"Le bouton de souris « {self.nom} » n'existe pas sur ce système : "
                                   "choisis une touche clavier dans config.toml.")

            def clic(_x, _y, b, presse):
                if b == bouton:
                    (self.sur_appui if presse else self.sur_relache)()

            self._ecouteur = mouse.Listener(on_click=clic)
        else:
            from pynput import keyboard

            if len(self.nom) == 1:
                caractere = self.nom

                def correspond(touche) -> bool:
                    car = getattr(touche, "char", None)
                    if car and car.lower() == caractere:
                        return True
                    # Avec Ctrl/Maj enfoncé, « char » change : on compare aussi le code de touche.
                    return caractere.isalnum() and getattr(touche, "vk", None) == ord(caractere.upper())
            else:
                cible = getattr(keyboard.Key, self.nom, None)
                if cible is None:
                    raise ErreurConfig(f"Touche « {self.nom} » inconnue. Exemples : f8, alt_r, ctrl_r, "
                                       "caps_lock, insert, pause.")

                def correspond(touche) -> bool:
                    return touche == cible

            def appui(touche):
                if correspond(touche):
                    self.sur_appui()

            def relache(touche):
                if correspond(touche):
                    self.sur_relache()

            self._ecouteur = keyboard.Listener(on_press=appui, on_release=relache)

        self._ecouteur.daemon = True
        self._ecouteur.start()

    def arreter(self) -> None:
        if self._ecouteur is not None:
            self._ecouteur.stop()
            self._ecouteur = None
