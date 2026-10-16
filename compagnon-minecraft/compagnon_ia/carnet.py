"""Carnet du royaume : projets, quêtes, lieux et rappels, que le compagnon tient lui-même (outils Gemini).

Tout est gardé dans carnet.json, d'une partie à l'autre. Au lancement, le contenu du carnet (et le résumé de
l'histoire du royaume) est ajouté aux consignes : il sait où est la base, ce qui reste à bâtir, quelle quête
est en cours…
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from .etat_jeu import _identifiant

log = logging.getLogger("compagnon")

VIDE = {"resume": "", "resume_jusqu_a": "", "projets": [], "quetes": [], "lieux": [], "rappels": []}
LIEUX_MAX = 60
TERMINES_GARDES = 15  # projets et quêtes terminés gardés (les plus récents)


def _cle(texte: str) -> str:
    """« Le Port du Sud ! » -> « le port du sud » (comparaison sans accents ni ponctuation)."""
    sans_accents = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", sans_accents.lower()).split())


MOTS_VIDES = {"le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "au", "aux", "et", "a", "en"}


def _mots(cle: str) -> set[str]:
    return {m for m in cle.split() if m not in MOTS_VIDES}


def _texte(valeur, longueur: int = 200) -> str:
    valeur = " ".join(str(valeur or "").split())
    return valeur[:longueur]


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="minutes")


class Carnet:
    def __init__(self, fichier: Path | None):
        self.fichier = fichier
        self.donnees = json.loads(json.dumps(VIDE))
        if fichier is not None and fichier.exists():
            try:
                lu = json.loads(fichier.read_text(encoding="utf-8"))
                for cle, defaut in VIDE.items():
                    if isinstance(lu.get(cle), type(defaut)):
                        self.donnees[cle] = lu[cle]
            except (OSError, ValueError, AttributeError) as e:
                log.warning("carnet.json illisible (%s) : on repart d'un carnet vide.", e)

    # ------------------------------------------------------------------ enregistrement
    def sauver(self) -> None:
        if self.fichier is None:
            return
        temporaire = self.fichier.with_suffix(".tmp")
        try:
            temporaire.write_text(json.dumps(self.donnees, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(temporaire, self.fichier)
            # Version lisible pour le joueur (à ouvrir avec le Bloc-notes), réécrite à chaque changement.
            self.fichier.with_suffix(".md").write_text(
                "# Carnet du royaume\n\n" + (self.texte() or "(vide pour l'instant)") + "\n", encoding="utf-8")
        except OSError as e:
            log.debug("carnet non enregistré : %s", e)

    # ------------------------------------------------------------------ recherche par nom
    @staticmethod
    def _trouver(elements: list[dict], champ: str, nom: str, en_cours: bool = True) -> dict | None:
        """Élément dont le nom ressemble le plus à « nom » (« port » trouve « Port du Sud »)."""
        cible = _cle(nom)
        if not cible:
            return None
        candidats = [e for e in elements if not en_cours or not e.get("termine")]
        for e in candidats:
            if _cle(e.get(champ, "")) == cible:
                return e
        for e in candidats:
            c = _cle(e.get(champ, ""))
            if c and (cible in c or c in cible):
                return e
        mots = _mots(cible)
        for e in candidats:  # « le port » trouve « Port du Sud »
            if mots and mots <= _mots(_cle(e.get(champ, ""))):
                return e
        meilleur, score = None, 0.0
        for e in candidats:
            s = difflib.SequenceMatcher(None, cible, _cle(e.get(champ, ""))).ratio()
            if s > score:
                meilleur, score = e, s
        return meilleur if score >= 0.6 else None

    @staticmethod
    def _elaguer(elements: list[dict]) -> None:
        termines = [e for e in elements if e.get("termine")]
        for e in termines[:-TERMINES_GARDES]:
            elements.remove(e)

    # ------------------------------------------------------------------ projets
    def noter_projet(self, nom: str, details: str = "") -> dict:
        nom, details = _texte(nom, 80), _texte(details)
        if not nom:
            return {"erreur": "il faut un nom de projet"}
        projets = self.donnees["projets"]
        existant = self._trouver(projets, "nom", nom)
        if existant is not None and _cle(existant["nom"]) == _cle(nom):
            if details:
                existant["details"] = details
            self.sauver()
            return {"resultat": f"projet « {existant['nom']} » mis à jour"}
        projets.append({"nom": nom, "details": details, "cree": _maintenant()})
        self.sauver()
        return {"resultat": f"projet « {nom} » noté dans le carnet",
                "projets_en_cours": [p["nom"] for p in projets if not p.get("termine")]}

    def terminer_projet(self, nom: str) -> dict:
        projet = self._trouver(self.donnees["projets"], "nom", nom)
        if projet is None:
            return {"erreur": f"aucun projet en cours ne ressemble à « {nom} »",
                    "projets_en_cours": [p["nom"] for p in self.donnees["projets"] if not p.get("termine")]}
        projet["termine"] = _maintenant()
        self._elaguer(self.donnees["projets"])
        self.sauver()
        return {"resultat": f"projet « {projet['nom']} » terminé, bravo à lui"}

    # ------------------------------------------------------------------ quêtes
    def ajouter_quete(self, titre: str, objectif: str, recompense: str = "") -> dict:
        titre, objectif, recompense = _texte(titre, 80), _texte(objectif), _texte(recompense, 120)
        if not titre or not objectif:
            return {"erreur": "il faut un titre et un objectif"}
        quetes = self.donnees["quetes"]
        if self._trouver(quetes, "titre", titre) is not None:
            return {"erreur": f"une quête ressemblant à « {titre} » est déjà en cours"}
        quetes.append({"titre": titre, "objectif": objectif, "recompense": recompense, "cree": _maintenant()})
        self.sauver()
        return {"resultat": f"quête « {titre} » ajoutée au carnet",
                "quetes_en_cours": [q["titre"] for q in quetes if not q.get("termine")]}

    def terminer_quete(self, titre: str, reussie: bool = True) -> dict:
        quete = self._trouver(self.donnees["quetes"], "titre", titre)
        if quete is None:
            return {"erreur": f"aucune quête en cours ne ressemble à « {titre} »",
                    "quetes_en_cours": [q["titre"] for q in self.donnees["quetes"] if not q.get("termine")]}
        quete["termine"] = _maintenant()
        quete["reussie"] = bool(reussie)
        self._elaguer(self.donnees["quetes"])
        self.sauver()
        if reussie:
            recompense = f" Récompense promise : {quete['recompense']}." if quete.get("recompense") else ""
            return {"resultat": f"quête « {quete['titre']} » accomplie !{recompense} Félicite-le."}
        return {"resultat": f"quête « {quete['titre']} » abandonnée"}

    def quetes_en_cours(self) -> list[dict]:
        return [q for q in self.donnees["quetes"] if not q.get("termine")]

    # ------------------------------------------------------------------ lieux
    def noter_lieu(self, nom: str, note: str = "", position: dict | None = None) -> dict:
        """position : {"x", "y", "z", "dimension"} (prise dans le capteur du mod quand il est là)."""
        nom, note = _texte(nom, 80), _texte(note, 160)
        if not nom:
            return {"erreur": "il faut un nom de lieu"}
        lieu = {"nom": nom, "note": note, "cree": _maintenant()}
        if position:
            for cle in ("x", "y", "z"):
                if isinstance(position.get(cle), (int, float)):
                    lieu[cle] = round(position[cle])
            if position.get("dimension"):
                lieu["dimension"] = _identifiant(position["dimension"])
        lieux = self.donnees["lieux"]
        existant = next((l for l in lieux if _cle(l["nom"]) == _cle(nom)), None)
        if existant is not None:
            lieux.remove(existant)
            if not note:
                lieu["note"] = existant.get("note", "")
        lieux.append(lieu)
        del lieux[:-LIEUX_MAX]
        self.sauver()
        if "x" in lieu:
            return {"resultat": f"lieu « {nom} » noté en {self.coordonnees(lieu)}"}
        return {"resultat": f"lieu « {nom} » noté, mais sans coordonnées (pas de capteur) : demande-les-lui "
                            "s'il veut les garder (touche F3)"}

    @staticmethod
    def coordonnees(lieu: dict) -> str:
        if "x" not in lieu:
            return "position inconnue"
        dimension = {"the_nether": " (Nether)", "the_end": " (End)"}.get(_identifiant(lieu.get("dimension")), "")
        return f"X {lieu['x']} Y {lieu.get('y', '?')} Z {lieu['z']}{dimension}"

    # ------------------------------------------------------------------ rappels
    def creer_rappel(self, texte: str, minutes: float) -> dict:
        texte = _texte(texte, 160)
        try:
            minutes = float(minutes)
        except (TypeError, ValueError):
            return {"erreur": "« minutes » doit être un nombre"}
        if not texte:
            return {"erreur": "il faut le texte du rappel"}
        minutes = min(24 * 60.0, max(0.5, minutes))
        self.donnees["rappels"].append({"texte": texte, "echeance": time.time() + minutes * 60})
        self.sauver()
        quand = f"{round(minutes)} minute{'s' if round(minutes) > 1 else ''}" if minutes >= 1 else "30 secondes"
        return {"resultat": f"rappel programmé dans {quand}"}

    def rappels_echus(self, maintenant: float | None = None) -> list[str]:
        """Rappels arrivés à échéance (retirés du carnet). Ceux d'une partie précédente partent au lancement."""
        maintenant = time.time() if maintenant is None else maintenant
        echus = [r for r in self.donnees["rappels"] if r.get("echeance", 0) <= maintenant]
        if echus:
            self.donnees["rappels"] = [r for r in self.donnees["rappels"] if r not in echus]
            self.sauver()
        return [r["texte"] for r in echus]

    # ------------------------------------------------------------------ résumé de l'histoire
    def mettre_resume(self, texte: str, jusqu_a: str) -> None:
        self.donnees["resume"] = texte.strip()[:3000]
        self.donnees["resume_jusqu_a"] = jusqu_a
        self.sauver()

    # ------------------------------------------------------------------ lecture
    def consulter(self) -> dict:
        d = self.donnees
        return {
            "projets_en_cours": [f"{p['nom']}" + (f" : {p['details']}" if p.get("details") else "")
                                 for p in d["projets"] if not p.get("termine")],
            "projets_termines": [p["nom"] for p in d["projets"] if p.get("termine")][-8:],
            "quetes_en_cours": [f"{q['titre']} : {q['objectif']}"
                                + (f" (récompense : {q['recompense']})" if q.get("recompense") else "")
                                for q in d["quetes"] if not q.get("termine")],
            "quetes_terminees": [q["titre"] for q in d["quetes"] if q.get("termine")][-8:],
            "lieux": [f"{l['nom']} : {self.coordonnees(l)}" + (f" — {l['note']}" if l.get("note") else "")
                      for l in d["lieux"]],
            "rappels_a_venir": [f"{r['texte']} (dans {max(0, round((r['echeance'] - time.time()) / 60))} min)"
                                for r in d["rappels"]],
        }

    def texte(self) -> str:
        """Contenu du carnet pour les consignes du compagnon ("" s'il est vide)."""
        c = self.consulter()
        parties = []
        if self.donnees["resume"]:
            parties.append("Histoire du royaume jusqu'ici :\n" + self.donnees["resume"])
        titres = {"projets_en_cours": "Projets en cours", "quetes_en_cours": "Quêtes en cours",
                  "lieux": "Lieux notés", "projets_termines": "Projets terminés",
                  "quetes_terminees": "Quêtes terminées", "rappels_a_venir": "Rappels à venir"}
        for cle, titre in titres.items():
            if c[cle]:
                parties.append(f"{titre} :\n" + "\n".join(f"- {x}" for x in c[cle]))
        return "\n\n".join(parties)

    def resume_court(self) -> str:
        """Une ligne pour les journaux de démarrage."""
        c = self.consulter()
        return (f"{len(c['projets_en_cours'])} projet(s), {len(c['quetes_en_cours'])} quête(s) en cours, "
                f"{len(c['lieux'])} lieu(x)" + (", histoire résumée" if self.donnees["resume"] else ""))


PROMPT_RESUME = """\
Tu tiens la chronique d'une partie de Minecraft (Survie) : le royaume du joueur {pseudo}, qu'il bâtit avec son \
compagnon de route (une IA qui joue à côté de lui).

Résumé actuel de l'histoire du royaume :
{resume}

Contenu du carnet (projets, quêtes, lieux) :
{carnet}

Nouveaux événements depuis ce résumé (morts, progrès, échanges avec le compagnon) :
{nouveaux}

Réécris le résumé de l'histoire du royaume en y intégrant les nouveautés importantes. 6 à 15 lignes, en français, \
au passé, faits concrets : bases et constructions, lieux découverts, aventures, morts marquantes, objectifs, \
blagues ou promesses récurrentes entre eux. Oublie les détails sans intérêt. Pas d'introduction ni de titre."""


def prompt_resume(pseudo: str, carnet: Carnet, nouveaux: str) -> str:
    return PROMPT_RESUME.format(pseudo=pseudo or "inconnu", resume=carnet.donnees["resume"] or "(pas encore de résumé)",
                                carnet=carnet.texte() or "(vide)", nouveaux=nouveaux)
