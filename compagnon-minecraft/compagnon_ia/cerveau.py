"""Le « cerveau » : transcription (Whisper) et réponses du modèle vision, via l'API Groq."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from typing import AsyncIterator

from .budget import Budget
from .config import RACINE, Config, lire_texte
from .phrases import FiltreReflexion, est_hallucination

log = logging.getLogger("compagnon")

# Au-delà de cette attente imposée par Groq, on n'essaie pas de nouveau : on prévient plutôt le joueur.
ATTENTE_MAX = 12.0

CONSIGNES_TECHNIQUES = """\
## Comment lire les messages
- « [Voix] … » : ce que le seigneur te dit au micro (transcription automatique, il peut y avoir des erreurs de mots).
- « [Chat] … » : ce qu'il t'écrit dans le chat du jeu.
- « [Événement] … » : un événement détecté dans le journal du jeu (mort, progrès…). Réagis-y.
- « [Coup d'œil] … » : une capture prise automatiquement pendant qu'il joue, pour un éventuel commentaire spontané.
La capture d'écran jointe au dernier message montre ce qu'il voit à cet instant. Dans le jeu, son pseudo est {pseudo}.

## Lire la capture d'écran
Ce sont des captures de Minecraft Java Edition en Survie, le plus souvent en vue à la première personne. Repères :
- la petite croix au centre : le bloc ou la créature qu'il vise ;
- en bas au centre : la barre d'inventaire rapide (9 cases), l'objet en main est dans la case encadrée ; sa main
  et l'objet tenu se voient aussi en bas à droite ;
- juste au-dessus : la barre verte d'expérience (avec son niveau), puis les cœurs à gauche (sa vie) et les cuisses
  de poulet à droite (sa faim) ; des icônes d'armure au-dessus des cœurs ; des bulles quand il manque d'air ;
- en bas à gauche : les messages du chat ; en haut au centre : la vie d'un boss ;
- écran teinté de rouge avec « Vous êtes mort » / « You Died! » : il est mort ; image floue ou assombrie avec des
  boutons, ou grande fenêtre grise (inventaire, coffre, four, établi) : un menu.
Indices : couleur du ciel (jour, coucher de soleil, nuit), blocs (sable = désert ou plage, neige, roche sombre =
grotte profonde, netherrack rouge = Nether, pierre jaune pâle = l'End), torches, créatures (creeper vert tacheté,
zombie, squelette, araignée, Enderman noir très grand…), constructions du joueur.

## Format de chaque réponse
Commence TOUJOURS par une observation brève entre <observation> et </observation> ; elle ne sera pas prononcée.
Note-y : le lieu, le moment de la journée, ce qu'il tient et ce qu'il vise, sa vie et sa faim si elles sont basses,
les créatures et dangers visibles, ce qu'il est en train de faire. Seulement ce que tu vois vraiment ; écris
« incertain » quand tu doutes.
Ensuite seulement, ta réponse à voix haute (ou SILENCE pour un coup d'œil sans intérêt), en français courant, en
texte brut destiné à être prononcé : pas de liste, pas de markdown, pas d'emoji.
Exemple : <observation>Prairie, fin de journée, épée en fer en main, vie pleine, faim à moitié, creeper à quelques
blocs sur la droite, il construit un mur en pierre.</observation>Creeper sur ta droite, recule ! Et mange un morceau
avant la nuit."""


def construire_systeme(cfg: Config, personnalite: str, chronique: str) -> str:
    parties = [personnalite.strip(), CONSIGNES_TECHNIQUES.format(pseudo=cfg.pseudo or "inconnu")]
    if chronique.strip():
        parties.append("## Chronique de la partie (ce qui s'est passé jusqu'ici)\n" + chronique.strip())
    return "\n\n".join(parties)


def charger_systeme(cfg: Config) -> str:
    personnalite = lire_texte(RACINE / "personnalite.md")
    if not personnalite:
        log.warning("personnalite.md introuvable ou vide : le compagnon n'aura pas de personnalité.")
    chronique = lire_texte(RACINE / "chronique.md")
    if chronique:
        log.info("Chronique chargée (%d caractères).", len(chronique))
    return construire_systeme(cfg, personnalite, chronique)


class LimiteGroq(Exception):
    """Groq refuse pour l'instant (429). attente = secondes conseillées avant de réessayer."""

    def __init__(self, attente: float | None, message: str):
        super().__init__(message)
        self.attente = attente


class ErreurGroq(Exception):
    """Autre erreur Groq (réseau, clé refusée, modèle introuvable…)."""


def duree_en_secondes(texte: str) -> float | None:
    """« 7.66s », « 2m59.5s », « 1h2m », « 120ms » ou « 12 » -> secondes."""
    texte = (texte or "").strip()
    if not texte:
        return None
    try:
        return float(texte)
    except ValueError:
        pass
    total, trouve = 0.0, False
    for valeur, unite in re.findall(r"([\d.]+)\s*(ms|h|m|s)", texte):
        trouve = True
        total += float(valeur) * {"ms": 0.001, "h": 3600, "m": 60, "s": 1}[unite]
    return total if trouve else None


def attente_conseillee(erreur) -> float | None:
    reponse = getattr(erreur, "response", None)
    entetes = getattr(reponse, "headers", None) or {}
    attente = duree_en_secondes(entetes.get("retry-after", ""))
    if attente is None:
        m = re.search(r"try again in ([\dhms.]+)", str(erreur))
        attente = duree_en_secondes(m.group(1)) if m else None
    return attente


def resumer_erreur(erreur) -> str:
    corps = getattr(erreur, "body", None)
    if isinstance(corps, dict):
        message = (corps.get("error") or {}).get("message") if isinstance(corps.get("error"), dict) else None
        if message:
            return message[:300]
    return str(erreur)[:300]


class Cerveau:
    def __init__(self, cfg: Config, systeme: str, budget: Budget, client=None):
        self.cfg = cfg
        self.systeme = systeme
        self.budget = budget
        if client is None:
            from groq import AsyncGroq

            # Pas de nouvel essai automatique du SDK : on les gère nous-mêmes (logs clairs, priorités).
            client = AsyncGroq(api_key=cfg.cle_api, max_retries=0, timeout=30.0)
        self.client = client
        self.historique: deque[dict] = deque(maxlen=2 * cfg.echanges)
        self.derniers_jetons: int | None = None
        self.derniere_observation = ""

    # --- utilitaires -----------------------------------------------------------------------
    async def lister_modeles(self) -> list[str]:
        reponse = await self.client.models.list()
        return sorted(m.id for m in reponse.data)

    async def _avec_essais(self, action, essais: int, quoi: str):
        import groq

        for n in range(1, essais + 1):
            try:
                return await action()
            except groq.RateLimitError as e:
                attente = attente_conseillee(e)
                if n >= essais or (attente or 0) > ATTENTE_MAX:
                    raise LimiteGroq(attente, resumer_erreur(e)) from e
                pause = attente if attente else 2.0 ** n
                log.warning("[Groq]   limite atteinte (%s), nouvel essai dans %.1f s…", quoi, pause)
                await asyncio.sleep(pause)
            except groq.APIConnectionError as e:  # inclut les délais dépassés
                if n >= essais:
                    raise ErreurGroq(f"connexion impossible ({e})") from e
                pause = 2.0 ** (n - 1)
                log.warning("[Groq]   problème réseau (%s), nouvel essai dans %.0f s…", quoi, pause)
                await asyncio.sleep(pause)
            except groq.APIStatusError as e:
                if e.status_code >= 500 and n < essais:
                    log.warning("[Groq]   erreur serveur %d (%s), nouvel essai…", e.status_code, quoi)
                    await asyncio.sleep(1.0 * n)
                    continue
                raise ErreurGroq(self._expliquer(e)) from e

    def _expliquer(self, e) -> str:
        message = resumer_erreur(e)
        if e.status_code == 401:
            return "clé API refusée par Groq : vérifie GROQ_API_KEY (ou cle_api dans config.toml)."
        if e.status_code == 404 or ("model" in message.lower() and "not" in message.lower()):
            return (f"{message}\n  -> Le modèle n'existe peut-être plus : lance « python compagnon.py --modeles » "
                    "et corrige config.toml.")
        if e.status_code == 400 and "reasoning" in message.lower():
            return f"{message}\n  -> Ce modèle ne connaît pas effort_raisonnement : mets effort_raisonnement = \"\"."
        if e.status_code == 413:
            return f"{message}\n  -> Image trop lourde : baisse largeur_image ou qualite_jpeg."
        return f"erreur {e.status_code} : {message}"

    # --- transcription ---------------------------------------------------------------------
    async def transcrire(self, audio_flac: bytes) -> str:
        options = {"model": self.cfg.modele_transcription, "language": self.cfg.langue,
                   "temperature": 0.0, "response_format": "json"}
        if self.cfg.vocabulaire.strip():
            options["prompt"] = self.cfg.vocabulaire.strip()

        async def action():
            return await self.client.audio.transcriptions.create(file=("voix.flac", audio_flac), **options)

        resultat = await self._avec_essais(action, 3, "transcription")
        texte = (getattr(resultat, "text", "") or "").strip()
        return "" if est_hallucination(texte) else texte

    # --- réponses --------------------------------------------------------------------------
    def _messages(self, entree: str, image_url: str | None) -> list[dict]:
        contenu: list[dict] = []
        if image_url:  # l'image d'abord, puis la consigne : c'est l'ordre attendu par les modèles Qwen
            contenu.append({"type": "image_url", "image_url": {"url": image_url}})
        contenu.append({"type": "text", "text": entree})
        return [{"role": "system", "content": self.systeme}, *self.historique,
                {"role": "user", "content": contenu}]

    async def repondre(self, entree: str, image_url: str | None, spontane: bool = False) -> AsyncIterator[str]:
        """Génère la réponse morceau par morceau (streaming). Les images ne sont jamais gardées
        dans l'historique : seule celle du tour en cours est envoyée."""
        parametres = {
            "model": self.cfg.modele_vision,
            "messages": self._messages(entree, image_url),
            "stream": True,
            "temperature": self.cfg.temperature,
            "max_completion_tokens": self.cfg.max_jetons_reponse,
        }
        effort = self.cfg.effort_raisonnement.strip()
        if effort:
            parametres["reasoning_effort"] = effort
            if effort != "none":
                parametres["reasoning_format"] = "hidden"
                # La réflexion compte dans la limite de jetons : on lui laisse de la place.
                parametres["max_completion_tokens"] += 1500

        async def ouvrir():
            brut = await self.client.chat.completions.with_raw_response.create(**parametres)
            self.budget.noter_entetes(brut.headers)
            return await brut.parse()

        # Un commentaire spontané n'insiste pas en cas d'erreur : il est abandonné.
        flux = await self._avec_essais(ouvrir, 1 if spontane else 3, "réponse")
        filtre = FiltreReflexion()
        jetons = None
        try:
            async for morceau in flux:
                usage = getattr(morceau, "usage", None) or getattr(getattr(morceau, "x_groq", None), "usage", None)
                if usage is not None and getattr(usage, "total_tokens", None):
                    jetons = usage.total_tokens
                if morceau.choices:
                    delta = morceau.choices[0].delta.content
                    if delta:
                        texte = filtre.filtrer(delta)
                        if texte:
                            yield texte
            reste = filtre.terminer()
            if reste:
                yield reste
        finally:
            await flux.close()
            self.derniers_jetons = jetons
            self.derniere_observation = filtre.masque
            # Flux interrompu avant la fin : on compte une estimation pour rester prudent.
            self.budget.enregistrer(jetons if jetons is not None else int(self.budget.cout_spontane), spontane)

    def memoriser(self, entree: str, reponse: str) -> None:
        """Ajoute l'échange (texte seul) à la mémoire courte."""
        self.historique.append({"role": "user", "content": entree})
        self.historique.append({"role": "assistant", "content": reponse})
