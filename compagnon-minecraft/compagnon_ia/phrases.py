"""Traitement du texte : découpage en phrases pour parler au plus vite, filtres de sortie du modèle."""

from __future__ import annotations

import re

# Fin de phrase : ponctuation forte (+ guillemet/parenthèse fermante éventuelle) suivie d'un espace,
# ou un retour à la ligne.
_FIN_PHRASE = re.compile(r"(?:[.!?…]+[»\"')\]]*\s+|\n+)")
# Coupure « douce » pour ne pas attendre trop longtemps une phrase très longue.
_COUPURE_DOUCE = re.compile(r"[,;:—–]\s+")


class DecoupeurPhrases:
    """Reçoit le texte au fil du streaming et rend les phrases dès qu'elles sont complètes."""

    def __init__(self, longueur_max: int = 140, longueur_min_coupe: int = 50):
        self.longueur_max = longueur_max
        self.longueur_min_coupe = longueur_min_coupe
        self._tampon = ""

    def ajouter(self, texte: str) -> list[str]:
        self._tampon += texte
        phrases: list[str] = []
        while True:
            m = _FIN_PHRASE.search(self._tampon)
            if m:
                phrase = self._tampon[: m.end()].strip()
                self._tampon = self._tampon[m.end():]
                if phrase:
                    phrases.append(phrase)
                continue
            if len(self._tampon) > self.longueur_max:
                coupes = [c for c in _COUPURE_DOUCE.finditer(self._tampon) if c.start() >= self.longueur_min_coupe]
                if coupes:
                    fin = coupes[-1].end()
                    phrases.append(self._tampon[:fin].strip())
                    self._tampon = self._tampon[fin:]
                    continue
            return phrases

    def terminer(self) -> list[str]:
        reste, self._tampon = self._tampon.strip(), ""
        return [reste] if reste else []


class FiltreReflexion:
    """Retire les blocs <think>…</think> si le modèle « réfléchit à voix haute »."""

    OUVRE, FERME = "<think>", "</think>"

    def __init__(self):
        self._tampon = ""
        self._dedans = False

    def filtrer(self, texte: str) -> str:
        self._tampon += texte
        sortie: list[str] = []
        while self._tampon:
            if self._dedans:
                i = self._tampon.find(self.FERME)
                if i < 0:
                    self._tampon = self._tampon[-len(self.FERME):]
                    break
                self._tampon = self._tampon[i + len(self.FERME):]
                self._dedans = False
            else:
                i = self._tampon.find(self.OUVRE)
                if i < 0:
                    j = self._tampon.rfind("<")
                    if j >= 0 and self.OUVRE.startswith(self._tampon[j:]):
                        # Peut-être le début d'une balise : on attend la suite.
                        sortie.append(self._tampon[:j])
                        self._tampon = self._tampon[j:]
                    else:
                        sortie.append(self._tampon)
                        self._tampon = ""
                    break
                sortie.append(self._tampon[:i])
                self._tampon = self._tampon[i + len(self.OUVRE):]
                self._dedans = True
        return "".join(sortie)

    def terminer(self) -> str:
        reste = "" if self._dedans else self._tampon
        self._tampon, self._dedans = "", False
        return reste


def _lettres(texte: str) -> str:
    return re.sub(r"[^A-Za-z]", "", texte).upper()


def est_silence(texte: str) -> bool:
    """Vrai si le modèle a répondu exactement SILENCE (à la ponctuation près)."""
    return _lettres(texte) == "SILENCE"


class PorteSilence:
    """Retient le début d'un commentaire spontané tant qu'il pourrait s'agir de « SILENCE ».

    etat : None = pas encore décidé, True = c'est SILENCE (ne rien dire), False = vrai commentaire.
    """

    def __init__(self):
        self._tampon = ""
        self.etat: bool | None = None

    def ajouter(self, texte: str) -> str:
        if self.etat is False:
            return texte
        if self.etat is True:
            return ""
        self._tampon += texte
        lettres = _lettres(self._tampon)
        if lettres.startswith("SILENCE"):
            self.etat = True
            return ""
        if "SILENCE".startswith(lettres):
            return ""
        self.etat = False
        texte, self._tampon = self._tampon, ""
        return texte

    def terminer(self) -> None:
        # Réponse finie sans avoir tranché (vide, « SIL »…) : on considère que c'est un silence.
        if self.etat is None:
            self.etat = True


_EMOJIS = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF️‍⭐⭕]"
)


def nettoyer_pour_voix(texte: str) -> str:
    """Retire ce qui ne doit pas être prononcé (didascalies *…*, markdown, emojis)."""
    t = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", texte)          # **gras** : on garde le texte
    t = re.sub(r"\*[^*\n]{1,80}\*", " ", t)                  # *il rit* : didascalie retirée
    t = re.sub(r"[*_#`~|<>]", " ", t)
    t = _EMOJIS.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if re.search(r"\w", t) else ""


# Phrases que Whisper « entend » parfois dans un enregistrement vide ou bruité.
_HALLUCINATIONS = (
    "amara.org", "sous-titr", "radio-canada", "abonnez-vous", "merci d'avoir regardé",
    "merci de votre attention", "à bientôt pour une nouvelle vidéo",
)


def est_hallucination(texte: str) -> bool:
    t = texte.lower().strip()
    if not re.search(r"\w", t):
        return True
    return any(motif in t for motif in _HALLUCINATIONS)
