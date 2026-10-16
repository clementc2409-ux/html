"""Mémoire d'une partie à l'autre : morts, progrès, échanges marquants, gardés dans souvenirs.json.

Au démarrage, les derniers souvenirs sont ajoutés aux consignes du compagnon : il peut y faire allusion
(« encore noyé, comme la dernière fois ! ») au lieu de repartir de zéro à chaque lancement.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

log = logging.getLogger("compagnon")

LIBELLES = {"mort": "mort", "progres": "progrès", "chat": "il t'a écrit", "echange": "échange",
            "remarque": "ta remarque"}


def _couper(texte: str, longueur: int) -> str:
    texte = " ".join(texte.split())
    return texte if len(texte) <= longueur else texte[:longueur].rsplit(" ", 1)[0] + "…"


class Souvenirs:
    def __init__(self, fichier: Path | None, maximum: int = 300):
        self.fichier = fichier
        self.maximum = maximum
        self.elements: list[dict] = []
        if fichier is not None and fichier.exists():
            try:
                donnees = json.loads(fichier.read_text(encoding="utf-8"))
                self.elements = [e for e in donnees if isinstance(e, dict) and e.get("texte")]
            except (OSError, ValueError) as e:
                log.warning("souvenirs.json illisible (%s) : on repart d'une mémoire vide.", e)

    def ajouter(self, genre: str, texte: str) -> None:
        texte = _couper(texte, 300)
        if not texte:
            return
        self.elements.append({"quand": datetime.now().isoformat(timespec="seconds"), "genre": genre, "texte": texte})
        del self.elements[:-self.maximum]
        self._sauver()

    def _sauver(self) -> None:
        if self.fichier is None:
            return
        temporaire = self.fichier.with_suffix(".tmp")
        try:
            temporaire.write_text(json.dumps(self.elements, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(temporaire, self.fichier)
        except OSError as e:
            log.debug("souvenirs non enregistrés : %s", e)

    def resume(self, nombre: int = 40) -> str:
        """Les derniers souvenirs, une ligne chacun, du plus ancien au plus récent."""
        return self._lignes(self.elements[-nombre:])

    def depuis(self, quand: str, nombre: int = 150) -> tuple[list[dict], str]:
        """Souvenirs plus récents que « quand » (date ISO, "" = tous) : (souvenirs, texte en lignes)."""
        nouveaux = [e for e in self.elements if str(e.get("quand", "")) > quand][-nombre:]
        return nouveaux, self._lignes(nouveaux)

    @staticmethod
    def _lignes(elements: list[dict]) -> str:
        lignes = []
        for e in elements:
            try:
                quand = datetime.fromisoformat(e["quand"]).strftime("%d/%m %H:%M")
            except (KeyError, ValueError):
                quand = "?"
            lignes.append(f"- {quand} — {LIBELLES.get(e.get('genre'), e.get('genre', '?'))} : {e['texte']}")
        return "\n".join(lignes)
