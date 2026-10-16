"""État exact du jeu, fourni par le mod « compagnon » (fichier etat.json mis à jour 2 fois par seconde).

Sert à trois choses :
- une bande d'infos exactes collée sous chaque image envoyée au modèle (vie, faim, biome, monstres proches,
  y compris derrière le joueur, ce qu'aucune capture ne peut montrer) ;
- des alertes instantanées (creeper dans le dos, plus que 3 cœurs, noyade…) ;
- savoir exactement si un menu est ouvert ou si le jeu est en pause.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("compagnon")

FRAICHEUR_MAX = 5.0  # secondes : au-delà, le jeu est fermé ou le mod absent

DIMENSIONS = {"overworld": "la Surface", "the_nether": "le Nether", "the_end": "l'End"}


def _identifiant(texte) -> str:
    """« ResourceKey[minecraft:dimension / minecraft:the_nether] » ou « minecraft:the_nether » -> « the_nether »."""
    texte = str(texte or "")
    trouve = re.findall(r"[a-z0-9_.-]+:([a-z0-9_./-]+)", texte)
    return trouve[-1] if trouve else texte


def dimension(etat: dict) -> str:
    ident = _identifiant(etat.get("joueur", {}).get("dimension"))
    return DIMENSIONS.get(ident, ident or "?")


def heure_du_jour(etat: dict) -> str:
    """Temps du jeu (0 = 6 h du matin) -> « 10 h, jour »."""
    t = etat.get("monde", {}).get("heure")
    if t is None:
        return ""
    t = int(t) % 24000
    heure = (t // 1000 + 6) % 24
    if t < 12000:
        moment = "jour"
    elif t < 13800:
        moment = "coucher du soleil"
    elif t < 22200:
        moment = "nuit"
    else:
        moment = "lever du soleil"
    return f"{heure} h, {moment}"


def _nombre(valeur, decimales: int = 0) -> str:
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return "?"
    return f"{v:.{decimales}f}".rstrip("0").rstrip(".") if decimales else str(round(v))


def resume(etat: dict) -> str:
    """Résumé compact et exact de l'état du jeu, en une ou deux lignes."""
    j = etat.get("joueur", {})
    m = etat.get("monde", {})
    morceaux = [f"Vie {_nombre(j.get('vie'), 1)}/{_nombre(j.get('vie_max', 20))}",
                f"Faim {_nombre(j.get('faim'))}/20"]
    if j.get("armure"):
        morceaux.append(f"Armure {_nombre(j.get('armure'))}")
    if j.get("niveau") is not None:
        morceaux.append(f"Niveau {_nombre(j.get('niveau'))}")
    air, air_max = j.get("air"), j.get("air_max") or 300
    if air is not None and air < air_max:
        morceaux.append(f"Air {round(100 * max(0, air) / air_max)} %")
    if j.get("en_feu"):
        morceaux.append("EN FEU")
    lieu = " · ".join(x for x in (j.get("biome") or "", dimension(etat), heure_du_jour(etat)) if x)
    if m.get("orage"):
        lieu += " · orage"
    elif m.get("pluie"):
        lieu += " · pluie"
    morceaux.append(lieu)
    main = (j.get("main") or {}).get("nom")
    morceaux.append(f"En main : {main or 'rien'}")
    vise = etat.get("vise") or {}
    if vise.get("nom"):
        morceaux.append(f"Vise : {vise['nom']}")
    monstres = sorted(etat.get("monstres") or [], key=lambda x: x.get("distance", 99))[:4]
    if monstres:
        morceaux.append("Monstres : " + ", ".join(
            f"{x.get('nom', '?')} à {_nombre(x.get('distance'))} blocs {x.get('direction', '')}".strip()
            for x in monstres))
    else:
        morceaux.append("Aucun monstre proche")
    if etat.get("menu"):
        morceaux.append(f"MENU OUVERT ({etat['menu']})")
    return " · ".join(morceaux)


class CapteurEtat:
    """Lit etat.json (écrit par le mod) et dit s'il est frais."""

    def __init__(self, chemin: Path | None):
        self.chemin = chemin
        self.etat: dict | None = None
        self._lu_le = 0.0

    def lire(self) -> dict | None:
        if self.chemin is None:
            return None
        try:
            donnees = json.loads(self.chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.etat if self.frais else None  # fichier en cours d'écriture : on garde le précédent
        horodatage = donnees.get("horodatage", 0) / 1000.0
        if time.time() - horodatage > FRAICHEUR_MAX:
            self.etat = None
            return None
        self.etat, self._lu_le = donnees, time.monotonic()
        return donnees

    @property
    def frais(self) -> bool:
        return self.etat is not None and time.monotonic() - self._lu_le < FRAICHEUR_MAX

    @property
    def menu_ou_pause(self) -> bool:
        return bool(self.frais and (self.etat.get("menu") or self.etat.get("pause")))


# --- Bande d'infos sous l'image -------------------------------------------------------------------

def _police(taille: int):
    for nom in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(nom, taille)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=taille)
    except TypeError:
        return ImageFont.load_default()


def _couper_lignes(texte: str, police, largeur_max: int, dessin) -> list[str]:
    lignes, ligne = [], ""
    for mot in texte.split(" "):
        essai = f"{ligne} {mot}".strip()
        if dessin.textlength(essai, font=police) <= largeur_max:
            ligne = essai
        else:
            lignes.append(ligne)
            ligne = mot
    if ligne:
        lignes.append(ligne)
    return lignes


def ajouter_bande(image: Image.Image, etat: dict) -> Image.Image:
    """Colle sous l'image une bande noire « CAPTEUR » avec les infos exactes du jeu."""
    taille = max(14, image.width // 64)
    police = _police(taille)
    brouillon = ImageDraw.Draw(image)
    texte = "CAPTEUR (infos exactes) : " + resume(etat)
    lignes = _couper_lignes(texte, police, image.width - 20, brouillon)
    hauteur = 12 + len(lignes) * (taille + 6)
    resultat = Image.new("RGB", (image.width, image.height + hauteur), (0, 0, 0))
    resultat.paste(image, (0, 0))
    dessin = ImageDraw.Draw(resultat)
    for i, ligne in enumerate(lignes):
        dessin.text((10, image.height + 6 + i * (taille + 6)), ligne, fill=(255, 255, 255), font=police)
    return resultat


# --- Alertes ----------------------------------------------------------------------------------------

DISTANCE_ALERTE = 6.0
DISTANCE_ALERTE_CREEPER = 8.0


@dataclass
class Alertes:
    """Compare deux états successifs et renvoie les alertes à prononcer tout de suite (avec anti-répétition)."""

    derniers: dict = field(default_factory=dict)
    dernier_evenement: int = -1

    def _peut(self, cle: str, delai: float) -> bool:
        maintenant = time.monotonic()
        if maintenant - self.derniers.get(cle, -1e9) < delai:
            return False
        self.derniers[cle] = maintenant
        return True

    def detecter(self, avant: dict | None, apres: dict) -> list[str]:
        alertes: list[str] = []
        ja, jb = (avant or {}).get("joueur", {}), apres.get("joueur", {})
        if apres.get("menu") or apres.get("pause"):
            return alertes

        for monstre in sorted(apres.get("monstres") or [], key=lambda x: x.get("distance", 99)):
            ident = _identifiant(monstre.get("id")) or monstre.get("nom", "?")
            limite = DISTANCE_ALERTE_CREEPER if "creeper" in ident else DISTANCE_ALERTE
            distance = monstre.get("distance", 99)
            direction = monstre.get("direction", "")
            if distance <= limite and (direction != "devant" or "creeper" in ident) and self._peut(f"monstre:{ident}", 25):
                ou = {"devant": "devant lui", "derrière": "derrière lui", "à gauche": "à sa gauche",
                      "à droite": "à sa droite"}.get(direction, direction)
                alertes.append(f"{monstre.get('nom', ident)} à {_nombre(distance)} blocs {ou} !")
                break  # une alerte monstre à la fois

        vie_a, vie_b = ja.get("vie"), jb.get("vie")
        if vie_a is not None and vie_b is not None:
            if vie_b < vie_a - 4.5 and self._peut("gros_degats", 10):
                cause = next((e.get("cause") for e in reversed(apres.get("evenements") or [])
                              if e.get("type") == "degats" and e.get("cause")), None)
                alertes.append(f"il vient de perdre {_nombre((vie_a - vie_b) / 2, 1)} cœurs d'un coup"
                               + (f" ({cause})" if cause else "") + " !")
            if 0 < vie_b <= 6 < vie_a and self._peut("vie_basse", 60):
                alertes.append(f"il n'a plus que {_nombre(vie_b / 2, 1)} cœurs !")

        faim_a, faim_b = ja.get("faim"), jb.get("faim")
        if faim_a is not None and faim_b is not None and faim_b <= 6 < faim_a and self._peut("faim", 300):
            alertes.append("il commence à avoir faim (faim à " + _nombre(faim_b) + "/20).")

        air, air_max = jb.get("air"), jb.get("air_max") or 300
        if air is not None and air < 0.3 * air_max and self._peut("air", 30):
            alertes.append("il manque d'air, il est en train de se noyer !")

        if jb.get("en_feu") and not ja.get("en_feu") and self._peut("feu", 30):
            alertes.append("il est en feu !")

        if avant and dimension(avant) != dimension(apres) and self._peut("dimension", 5):
            alertes.append(f"il vient d'arriver dans {dimension(apres)}.")

        heure_a = (avant or {}).get("monde", {}).get("heure")
        heure_b = apres.get("monde", {}).get("heure")
        if (heure_a is not None and heure_b is not None and dimension(apres) == "la Surface"
                and int(heure_a) % 24000 < 12000 <= int(heure_b) % 24000 and self._peut("coucher", 600)):
            alertes.append("le soleil se couche, la nuit va tomber.")

        niv_a, niv_b = ja.get("niveau"), jb.get("niveau")
        if niv_a is not None and niv_b is not None and niv_b > niv_a and niv_b % 5 == 0 and self._peut("niveau", 30):
            alertes.append(f"il vient d'atteindre le niveau {niv_b} d'expérience.")
        return alertes


# --- Simulation (mode test, sans Minecraft) ----------------------------------------------------------

SCENARIOS = ("capteur", "creeper", "blesse")


def etat_simule(scenario: str, t: float) -> dict:
    """Faux état du jeu à l'instant t (secondes depuis le début de la simulation)."""
    vie, monstres, evenements = 18.0, [], []
    if scenario == "creeper" and t >= 3:
        distance = max(2.5, 14 - 1.5 * (t - 3))  # un creeper s'approche dans son dos
        monstres.append({"nom": "Creeper", "id": "minecraft:creeper", "distance": round(distance, 1),
                         "direction": "derrière", "hauteur": "même niveau"})
    if scenario == "blesse" and t >= 3:
        vie = 9.0 if t < 8 else 5.0  # flèches d'un squelette
        evenements.append({"n": 1, "type": "degats", "montant": 9.0, "cause": "Squelette"})
        if t >= 8:
            evenements.append({"n": 2, "type": "degats", "montant": 4.0, "cause": "Squelette"})
        monstres.append({"nom": "Squelette", "id": "minecraft:skeleton", "distance": 11.0, "direction": "à gauche",
                         "hauteur": "même niveau"})
    return {
        "version": 1, "horodatage": int(time.time() * 1000),
        "joueur": {"nom": "Test", "vie": vie, "vie_max": 20.0, "faim": 15, "saturation": 3.0, "armure": 7,
                   "niveau": 9, "air": 300, "air_max": 300, "en_feu": False, "sous_eau": False,
                   "x": 152.5, "y": 71.0, "z": -48.3, "dimension": "minecraft:overworld",
                   "biome": "Plaines", "lumiere": 15, "main": {"nom": "Épée en fer", "nombre": 1, "usure": 0.2},
                   "main_secondaire": {"nom": None}, "effets": []},
        "monde": {"heure": 5000, "jour": 3, "pluie": False, "orage": False},
        "vise": {"type": "bloc", "nom": "Herbe"},
        "menu": None, "pause": False,
        "monstres": monstres, "evenements": evenements,
    }
