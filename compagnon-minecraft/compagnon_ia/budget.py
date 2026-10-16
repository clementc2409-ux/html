"""Suivi de la consommation Groq (offre gratuite) pour ne pas gaspiller le quota en commentaires spontanés."""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path

log = logging.getLogger("compagnon")


class Budget:
    """Compte les jetons du jour (enregistrés dans un petit fichier JSON) et régule les commentaires
    spontanés avec un « seau » qui se remplit à jetons_spontanes_par_heure. Les réponses à tes
    questions et aux événements ne sont jamais bloquées par le budget : seuls les commentaires
    spontanés sont abandonnés en priorité."""

    # Part du quota journalier qu'on garde pour les questions : au-delà de 80 %, plus de spontané.
    SEUIL_JOUR = 0.8
    # Requêtes restantes (d'après Groq) en dessous desquelles on arrête le spontané.
    RESERVE_REQUETES = 30

    def __init__(self, jetons_par_jour: int, jetons_spontanes_par_heure: int, fichier: Path | None = None):
        self.jetons_par_jour = jetons_par_jour
        self.debit = max(0, jetons_spontanes_par_heure) / 3600.0
        self.capacite = max(4000.0, jetons_spontanes_par_heure / 6)
        self.reserve = self.capacite
        self._maj = time.monotonic()
        self.cout_spontane = 2500.0  # estimation, affinée avec les vrais chiffres
        self.pause_jusqua = 0.0
        self.requetes_restantes: int | None = None
        self.fichier = fichier
        self.jour = date.today().isoformat()
        self.jetons_jour = 0
        self.requetes_jour = 0
        self._charger()

    # --- fichier ---------------------------------------------------------------------------
    def _charger(self) -> None:
        if not self.fichier or not self.fichier.exists():
            return
        try:
            donnees = json.loads(self.fichier.read_text(encoding="utf-8"))
            if donnees.get("jour") == self.jour:
                self.jetons_jour = int(donnees.get("jetons", 0))
                self.requetes_jour = int(donnees.get("requetes", 0))
        except (OSError, ValueError):
            pass

    def _sauver(self) -> None:
        if not self.fichier:
            return
        try:
            self.fichier.write_text(json.dumps(
                {"jour": self.jour, "jetons": self.jetons_jour, "requetes": self.requetes_jour}), encoding="utf-8")
        except OSError:
            pass

    def _nouveau_jour(self) -> None:
        aujourdhui = date.today().isoformat()
        if aujourdhui != self.jour:
            self.jour, self.jetons_jour, self.requetes_jour = aujourdhui, 0, 0

    # --- suivi -----------------------------------------------------------------------------
    def enregistrer(self, jetons: int, spontane: bool) -> None:
        self._nouveau_jour()
        self.jetons_jour += jetons
        self.requetes_jour += 1
        if spontane:
            self._recharger()
            self.reserve -= jetons
            self.cout_spontane = 0.7 * self.cout_spontane + 0.3 * jetons
        self._sauver()

    def noter_entetes(self, entetes) -> None:
        """Lit les en-têtes de limite renvoyés par Groq (requêtes restantes aujourd'hui)."""
        valeur = entetes.get("x-ratelimit-remaining-requests") if entetes else None
        if valeur is not None:
            try:
                self.requetes_restantes = int(float(valeur))
            except ValueError:
                pass

    def pause_spontanes(self, secondes: float) -> None:
        self.pause_jusqua = max(self.pause_jusqua, time.monotonic() + secondes)

    def _recharger(self) -> None:
        maintenant = time.monotonic()
        self.reserve = min(self.capacite, self.reserve + (maintenant - self._maj) * self.debit)
        self._maj = maintenant

    def autorise_spontane(self) -> tuple[bool, str]:
        self._nouveau_jour()
        self._recharger()
        if time.monotonic() < self.pause_jusqua:
            reste = self.pause_jusqua - time.monotonic()
            return False, f"Groq a demandé une pause ({reste:.0f} s)"
        if self.jetons_par_jour and self.jetons_jour >= self.SEUIL_JOUR * self.jetons_par_jour:
            return False, "quota du jour presque atteint, je garde le reste pour tes questions"
        if self.requetes_restantes is not None and self.requetes_restantes < self.RESERVE_REQUETES:
            return False, f"plus que {self.requetes_restantes} requêtes Groq aujourd'hui, je les garde pour toi"
        if self.reserve < self.cout_spontane:
            manque = (self.cout_spontane - self.reserve) / self.debit if self.debit else float("inf")
            return False, f"budget horaire de commentaires spontanés atteint (encore ~{manque:.0f} s)"
        return True, ""

    def resume(self) -> str:
        texte = f"{_nombre(self.jetons_jour)} jetons aujourd'hui"
        if self.jetons_par_jour:
            pourcent = 100 * self.jetons_jour / self.jetons_par_jour
            texte += f" ({pourcent:.0f} % de {_nombre(self.jetons_par_jour)})"
        if self.requetes_restantes is not None:
            texte += f", {self.requetes_restantes} requêtes restantes"
        return texte


def _nombre(n: int) -> str:
    return f"{n:,}".replace(",", " ")
